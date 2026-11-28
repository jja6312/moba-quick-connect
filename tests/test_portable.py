import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import core
import portable


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.key = self.root / '한글 키'
        self.jump = self.root / 'bastion.ppk'
        self.key.write_bytes(b'SYNTHETIC TARGET KEY')
        self.jump.write_bytes(b'SYNTHETIC BASTION KEY')
        self.rows = [{**core.new_row(core.DEFAULTS), 'name': '  server 01\r\n', 'host': ' 192.0.2.1\n',
                      'key_path': str(self.key), 'bastion_host': '198.51.100.1', 'bastion_key_path': str(self.jump)}]
        self.archive = self.root / 'connections.mobaquick.zip'
        self.store = core.Store(self.root / 'other PC')

    def tearDown(self):
        self.tmp.cleanup()

    def export(self):
        return portable.export_bundle(self.archive, self.rows, [{'name': 'Prod', 'path': str(self.key)}])

    def rewrite(self, mutate, extra=None):
        with zipfile.ZipFile(self.archive) as archive:
            data = {n: archive.read(n) for n in archive.namelist()}
        manifest = json.loads(data['manifest.json'])
        mutate(manifest, data)
        data['manifest.json'] = json.dumps(manifest).encode()
        data.update(extra or {})
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, raw in data.items():
                archive.writestr(name, raw)

    def test_other_pc_round_trip_restores_keys_and_aliases_with_local_paths(self):
        before = (self.key.read_bytes(), self.jump.read_bytes())
        self.assertEqual(self.export(), {'connections': 1, 'keys': 2})
        bundle = portable.read_bundle(self.archive)
        self.assertNotIn(str(self.root), json.dumps(bundle.rows))
        rows = portable.install_bundle(bundle, self.store)
        self.assertEqual(rows[0]['name'], 'server 01')
        self.assertEqual(rows[0]['host'], '192.0.2.1')
        for field, expected in zip(portable.KEY_FIELDS, before):
            path = Path(rows[0][field])
            self.assertTrue(path.is_relative_to(self.store.root))
            self.assertEqual(path.read_bytes(), expected)
        self.assertEqual(self.key.read_bytes(), before[0])
        self.assertEqual(self.jump.read_bytes(), before[1])
        self.assertIn('Prod', [k['name'] for k in self.store.state['favorite_keys']])
        self.assertEqual(portable.install_bundle(bundle, self.store), rows)
        self.assertEqual(len(self.store.state['favorite_keys']), 2)
        self.assertEqual(core.Store(self.store.root).state['favorite_keys'], self.store.state['favorite_keys'])
        self.assertEqual(self.store.state['connections'], [])  # Review before actual registration.

    def test_shared_target_jump_key_is_deduplicated_and_no_unrelated_keys_export(self):
        self.rows[0]['bastion_key_path'] = str(self.key)
        result = portable.export_bundle(self.archive, self.rows, [{'name': 'Unrelated', 'path': str(self.jump)}])
        self.assertEqual(result['keys'], 1)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(len(archive.namelist()), 2)
            self.assertNotIn(b'SYNTHETIC BASTION KEY', b''.join(archive.read(n) for n in archive.namelist()))

    def test_rdp_jump_key_and_no_key_connections_round_trip(self):
        self.rows = [{**core.new_row(core.DEFAULTS, 'RDP'), 'host': '192.0.2.2', 'bastion_host': '198.51.100.1',
                      'bastion_key_path': str(self.jump)}]
        self.export()
        rows = portable.install_bundle(portable.read_bundle(self.archive), self.store)
        self.assertEqual(rows[0]['protocol'], 'RDP')
        self.assertEqual(rows[0]['key_path'], '')
        self.assertEqual(Path(rows[0]['bastion_key_path']).read_bytes(), self.jump.read_bytes())

    def test_corrupt_key_hash_and_external_reference_are_rejected_before_write(self):
        self.export()
        self.rewrite(lambda m,d: d.update({m['keys'][0]['file']: b'CORRUPTED'}))
        with self.assertRaisesRegex(ValueError, '검증'):
            portable.read_bundle(self.archive)
        self.assertFalse((self.store.root / 'imports').exists())
        self.archive.unlink()
        self.export()
        self.rewrite(lambda m,d: m['connections'][0].update(key_path='C:\\outside\\key'))
        with self.assertRaises(ValueError):
            portable.read_bundle(self.archive)

    def test_traversal_absolute_unknown_and_symlink_entries_are_rejected(self):
        for name in ('../outside.key', '/outside.key', 'C:/outside.key', 'keys/../outside.key', 'unknown.txt'):
            if self.archive.exists():
                self.archive.unlink()
            self.export()
            self.rewrite(lambda m,d: None, {name: b'SYNTHETIC'})
            with self.assertRaises(ValueError):
                portable.read_bundle(self.archive)
        self.archive.unlink()
        self.export()
        with zipfile.ZipFile(self.archive, 'a') as archive:
            info = zipfile.ZipInfo('keys/' + '0' * 64 + '.key')
            info.external_attr = 0o120777 << 16
            archive.writestr(info, b'../outside')
        with self.assertRaises(ValueError):
            portable.read_bundle(self.archive)

    def test_missing_key_and_export_failure_preserve_existing_destination(self):
        self.archive.write_bytes(b'PREVIOUS EXPORT')
        with self.assertRaises(FileExistsError):
            self.export()
        self.key.unlink()
        with self.assertRaises(ValueError):
            portable.export_bundle(self.archive, self.rows, overwrite=True)
        self.assertEqual(self.archive.read_bytes(), b'PREVIOUS EXPORT')

    def test_failed_import_save_rolls_back_only_new_import(self):
        self.export()
        bundle = portable.read_bundle(self.archive)
        self.store.save()
        before = self.store.path.read_bytes()
        with patch.object(self.store, 'save', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                portable.install_bundle(bundle, self.store)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.state['favorite_keys'], [])
        self.assertEqual(list((self.store.root / 'imports').iterdir()), [])

    def test_changed_previously_imported_key_is_preserved(self):
        self.export()
        bundle = portable.read_bundle(self.archive)
        rows = portable.install_bundle(bundle, self.store)
        path = Path(rows[0]['key_path'])
        path.write_bytes(b'LOCAL USER EDIT')
        with self.assertRaises(ValueError):
            portable.install_bundle(bundle, self.store)
        self.assertEqual(path.read_bytes(), b'LOCAL USER EDIT')

    def test_oversized_key_and_unsupported_schema_are_rejected(self):
        with patch.object(portable, 'KEY_LIMIT', 4):
            with self.assertRaises(ValueError):
                self.export()
        self.assertFalse(self.archive.exists())
        self.export()
        self.rewrite(lambda m,d: m.update(schema=999))
        with self.assertRaises(ValueError):
            portable.read_bundle(self.archive)


if __name__ == '__main__':
    unittest.main()
