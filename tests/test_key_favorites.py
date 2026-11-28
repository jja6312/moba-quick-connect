import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import app as ui
import core
from key_picker import FavoriteKeysDialog, KeyPicker


class FavoriteStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'state')
        self.key = self.root / '한글 키 without extension'
        self.key.write_bytes(b'SYNTHETIC KEY FIXTURE')

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_settings_migrate_without_rewriting_defaults_or_connections(self):
        old = core.default_state()
        del old['favorite_keys']
        old['profiles']['기본 설정']['SSH']['key_path'] = str(self.key)
        self.store.path.write_text(json.dumps(old), encoding='utf-8')
        before = self.store.path.read_bytes()
        store = core.Store(self.store.root)
        self.assertEqual(store.state['favorite_keys'], [])
        self.assertEqual(store.profile, old['profiles']['기본 설정'])
        self.assertEqual(store.path.read_bytes(), before)

    def test_favorite_persists_deduplicates_and_never_opens_key_contents(self):
        original = self.key.read_bytes()
        real_open = Path.open
        def guarded(path, *args, **kwargs):
            if path == self.key:
                raise AssertionError('Key contents were opened')
            return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            self.assertTrue(self.store.add_favorite_key(self.key))
            self.assertFalse(self.store.add_favorite_key(self.key.parent / '.' / self.key.name))
            self.store.rename_favorite_key(self.key, 'Production')
            restored = core.Store(self.store.root)
        self.assertEqual(restored.state['favorite_keys'], [{'name': 'Production', 'path': str(self.key)}])
        self.assertEqual(self.key.read_bytes(), original)
        self.assertEqual(core.key_identity(r'C:\Keys\A.key'), core.key_identity('c:/keys/a.KEY'))

    def test_remove_is_metadata_only_and_keeps_configured_paths(self):
        self.store.profile['SSH']['key_path'] = str(self.key)
        self.store.add_favorite_key(self.key)
        self.store.remove_favorite_key(self.key)
        self.assertTrue(self.key.is_file())
        restored = core.Store(self.store.root)
        self.assertEqual(restored.state['favorite_keys'], [])
        self.assertEqual(restored.profile['SSH']['key_path'], str(self.key))

    def test_failed_save_rolls_back_favorite_changes(self):
        self.store.save()
        before = self.store.path.read_bytes()
        with patch.object(self.store, 'save', side_effect=OSError('fixture disk error')):
            with self.assertRaises(OSError):
                self.store.add_favorite_key(self.key)
        self.assertEqual(self.store.state['favorite_keys'], [])
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_missing_files_and_invalid_metadata_are_preserved(self):
        with self.assertRaises(ValueError):
            self.store.add_favorite_key(self.root / 'missing')
        invalid = {**core.default_state(), 'favorite_keys': 'not a list'}
        self.store.path.write_text(json.dumps(invalid), encoding='utf-8')
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            core.Store(self.store.root)
        self.assertEqual(self.store.path.read_bytes(), before)


class FavoriteInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui.configure_application(cls.app)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'state')
        self.store.state['moba_exe'] = r'C:\Programs\MobaXterm.exe'
        self.key = self.root / 'target-key'
        self.key.write_bytes(b'SYNTHETIC KEY FIXTURE')
        self.window = ui.MainWindow(self.store, dry_run=True, no_tray=True)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.quitting = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def add_favorite(self, path=None, name='Production'):
        self.store.add_favorite_key(path or self.key, name)
        self.window.key_library.changed.emit()
        self.app.processEvents()

    def test_browse_accept_prompts_once_and_shares_choices_across_forms(self):
        picker = self.window.single_form.fields['key_path']
        with patch.object(ui.QFileDialog, 'getOpenFileName', return_value=(str(self.key), '')) as dialog, \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes) as ask:
            picker.browse()
            self.assertEqual(dialog.call_args.args[3], '모든 파일 (*)')
            self.window.settings_form.fields['bastion_key_path'].browse()
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(picker.text(), str(self.key))
        self.assertEqual(core.Store(self.store.root).state['favorite_keys'][0]['path'], str(self.key))
        for form in (self.window.single_form, self.window.settings_form):
            for field in ('key_path', 'bastion_key_path'):
                self.assertEqual(form.fields[field].combo.count(), 1)

    def test_decline_and_cancel_keep_selection_separate_from_favorites(self):
        picker = self.window.single_form.fields['bastion_key_path']
        with patch.object(ui.QFileDialog, 'getOpenFileName', return_value=(str(self.key), '')), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            picker.browse()
        self.assertEqual(picker.text(), str(self.key))
        self.assertEqual(self.store.state['favorite_keys'], [])
        with patch.object(ui.QFileDialog, 'getOpenFileName', return_value=('', '')), patch.object(QMessageBox, 'question') as ask:
            picker.browse()
        self.assertFalse(ask.called)
        self.assertEqual(picker.text(), str(self.key))

    def test_search_matches_alias_and_path_and_enter_selects_real_path(self):
        self.add_favorite()
        picker = self.window.single_form.fields['key_path']
        for query in ('DUCT', 'target-key'):
            picker.setText('')
            picker.combo.setFocus()
            QTest.keyClicks(picker.combo.lineEdit(), query)
            self.app.processEvents()
            completer = picker.combo.completer()
            self.assertEqual(completer.completionCount(), 1)
            QTest.keyClick(completer.popup(), Qt.Key.Key_Down)
            QTest.keyClick(completer.popup(), Qt.Key.Key_Return)
            self.app.processEvents()
            self.assertEqual(picker.text(), str(self.key))
            self.assertEqual(self.window.single_form.get_row()['key_path'], str(self.key))

    def test_same_filename_choices_keep_their_own_paths(self):
        other = self.root / 'other' / self.key.name
        other.parent.mkdir()
        other.write_bytes(b'ANOTHER SYNTHETIC FIXTURE')
        self.add_favorite(name='Same name')
        self.add_favorite(other, 'Same name')
        picker = self.window.single_form.fields['key_path']
        picker.choose_index(1)
        self.assertEqual(picker.text(), str(other))
        self.store.rename_favorite_key(self.key, 'Renamed')
        self.window.key_library.changed.emit()
        self.assertEqual(picker.text(), str(other))
        self.assertIn('Renamed', picker.combo.itemText(0))

    def open_grid_key(self, row):
        self.window.select_page(1)
        self.app.processEvents()
        grid = self.window.grid
        if row % 2:
            grid.toggle_bastion(row // 2)
        grid.setCurrentCell(row, 5)
        grid.scrollToItem(grid.item(row, 5))
        grid.editItem(grid.item(row, 5))
        self.app.processEvents()
        return grid, next(e for e in grid.viewport().findChildren(KeyPicker) if e.isVisible() and not e.closed)

    def test_bulk_and_bastion_enter_commit_paths_and_move_same_layer(self):
        self.add_favorite()
        for row, field in ((0, 'key_path'), (1, 'bastion_key_path')):
            grid, picker = self.open_grid_key(row)
            picker.choose_index(0)
            QTest.keyClick(picker.combo, Qt.Key.Key_Return)
            self.app.processEvents()
            self.assertEqual(grid.rows()[0][field], str(self.key))
            self.assertEqual((grid.currentRow(), grid.currentColumn()), (row + 2, 5))
        grid.undo()
        self.assertEqual(grid.rows()[0]['bastion_key_path'], '')
        self.assertEqual(grid.rows()[0]['key_path'], str(self.key))

    def test_bulk_ctrl_enter_commits_composite_editor_before_registration(self):
        self.add_favorite()
        grid, picker = self.open_grid_key(0)
        grid.item(0, 1).setText('192.0.2.10')
        picker.choose_index(0)
        self.window.register_bulk()
        self.assertEqual(self.store.state['connections'][0]['key_path'], str(self.key))

    def test_bulk_folder_button_browses_without_premature_focus_commit(self):
        self.window.select_page(1)
        grid = self.window.grid
        grid.toggle_bastion(0)
        grid.setCurrentCell(1, 1)
        grid.scrollToItem(grid.item(1, 5))
        self.app.processEvents()
        rect = grid.visualRect(grid.model().index(1, 5))
        with patch.object(ui.QFileDialog, 'getOpenFileName', return_value=(str(self.key), '')) as browse, \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             QPoint(rect.right() - 12, rect.center().y()))
            self.app.processEvents()
            self.assertEqual(browse.call_count, 1)
        picker = next(e for e in grid.viewport().findChildren(KeyPicker) if e.isVisible() and not e.closed)
        self.assertEqual(picker.text(), str(self.key))
        QTest.keyClick(picker.combo, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(grid.rows()[0]['bastion_key_path'], str(self.key))
        self.assertEqual(grid.rows()[0]['key_path'], '')

    def test_manager_remove_refreshes_choices_but_keeps_current_input(self):
        self.add_favorite()
        picker = self.window.single_form.fields['key_path']
        picker.choose_index(0)
        dialog = FavoriteKeysDialog(self.window.key_library, self.window)
        dialog.table.setCurrentCell(0, 0)
        dialog.remove()
        self.assertEqual(picker.combo.count(), 0)
        self.assertEqual(picker.text(), str(self.key))
        self.assertTrue(self.key.is_file())
        dialog.deleteLater()

    def test_bulk_search_enter_selects_then_next_enter_moves_down(self):
        self.add_favorite()
        grid, picker = self.open_grid_key(1)
        QTest.keyClicks(picker.combo, 'DUCT')
        self.app.processEvents()
        popup = picker.combo.completer().popup()
        QTest.keyClick(popup, Qt.Key.Key_Down)
        QTest.keyClick(popup, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(picker.text(), str(self.key))
        self.assertEqual(grid.currentRow(), 1)
        QTest.keyClick(picker.combo, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(grid.rows()[0]['bastion_key_path'], str(self.key))
        self.assertEqual(grid.currentRow(), 3)

    def test_existing_missing_favorite_remains_available_but_registration_validates(self):
        self.add_favorite()
        self.key.unlink()
        picker = self.window.single_form.fields['key_path']
        picker.choose_index(0)
        self.window.host.setText('192.0.2.9')
        self.window.connect_single()
        self.assertFalse(self.store.state['connections'])
        self.assertIn('파일을 찾을 수 없습니다', self.window.status.text())
        self.assertEqual(picker.combo.count(), 1)

    def test_loaded_long_paths_keep_window_compact(self):
        self.store.state['favorite_keys'] = [{'name': 'Long alias', 'path': 'C:\\' + 'nested\\' * 35 + 'key'}]
        other = ui.MainWindow(self.store, dry_run=True, no_tray=True)
        other.show()
        self.app.processEvents()
        self.assertLessEqual(other.width(), 860)
        other.quitting = True
        other.close()
        other.deleteLater()


if __name__ == '__main__':
    unittest.main()
