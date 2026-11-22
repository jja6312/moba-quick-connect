import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PS = str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


def quote(path):
    return "'" + str(path).replace("'", "''") + "'"


@unittest.skipUnless(os.name == 'nt', 'Actual Windows PowerShell and shortcuts required')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "한글 & O'Neil [install]"
        self.base.mkdir()
        self.local, self.menu, self.startup = [self.base / name for name in ('local', 'menu', 'startup')]
        self.startup.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, script):
        r = subprocess.run([PS, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True)
        out = r.stdout.decode('utf-8', errors='replace')
        self.assertEqual(r.returncode, 0, out + r.stderr.decode(errors='replace'))
        return json.loads(next(line[7:] for line in out.splitlines() if line.startswith('RESULT:')))

    def install(self, extra=None, expected=None):
        # ShellLink on Windows Server validates executable metadata. Use an OS
        # PE file as fixture bytes and always suppress application launch.
        data = {'app/MobaQuickConnect.exe': (Path(os.environ['WINDIR']) / 'System32/where.exe').read_bytes(), 'app/version.txt': b'1.3.0',
                'app/Shortcuts.ps1': (ROOT / 'windows/Shortcuts.ps1').read_bytes(),
                'app/AutoStart.ps1': (ROOT / 'windows/AutoStart.ps1').read_bytes()}
        data.update(extra or {})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            for name, value in data.items(): z.writestr(name, value)
        payload = self.base / 'payload.zip'; payload.write_bytes(buf.getvalue())
        digest = expected or hashlib.sha256(buf.getvalue()).hexdigest()
        script = '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);. ' + quote(ROOT / 'windows/Install.Core.ps1')
        script += ';try{$r=Install-MobaQuickConnect -Payload ([IO.File]::ReadAllBytes(' + quote(payload) + ')) -ExpectedHash ' + quote(digest)
        script += ' -LocalData ' + quote(self.local) + ' -MenuDirectory ' + quote(self.menu) + ' -StartupDirectory ' + quote(self.startup) + ' -NoLaunch;'
        script += "Write-Output ('RESULT:'+(@{ok=$true;result=$r}|ConvertTo-Json -Compress))}catch{Write-Output ('RESULT:'+(@{ok=$false;error=$_.Exception.Message;stack=$_.ScriptStackTrace;errorId=$_.FullyQualifiedErrorId}|ConvertTo-Json -Compress))}"
        return self.invoke(script)

    def startup_action(self, action):
        script = '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);try{& ' + quote(ROOT / 'windows/AutoStart.ps1')
        script += ' -Action ' + action + ' -LocalData ' + quote(self.local) + ' -StartupDirectory ' + quote(self.startup)
        script += ";Write-Output 'RESULT:{\"ok\":true}'}catch{Write-Output ('RESULT:'+(@{ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Compress))}"
        return self.invoke(script)

    def test_install_and_optional_startup_enable_disable_in_real_ps51(self):
        result = self.install(); self.assertTrue(result['ok'], result)
        self.assertFalse(list(self.startup.iterdir()))
        self.assertTrue((self.menu / 'Moba Quick Connect.lnk').exists())
        self.assertTrue(self.startup_action('Enable')['ok'])
        self.assertTrue((self.startup / 'Moba Quick Connect.lnk').exists())
        self.assertTrue(self.startup_action('Disable')['ok'])
        self.assertFalse(list(self.startup.iterdir()))
        self.assertTrue(Path(result['result']['executable']).exists())

    def test_reinstall_retains_enabled_startup_and_extra_data(self):
        self.assertTrue(self.install()['ok']); self.assertTrue(self.startup_action('Enable')['ok'])
        note = self.local / 'Cloudragon/MobaQuickConnect/note.txt'; note.write_text('keep')
        result = self.install(); self.assertTrue(result['ok'], result); self.assertTrue((self.startup / 'Moba Quick Connect.lnk').exists())
        self.assertEqual(note.read_text(), 'keep')

    def test_modified_version_and_bad_checksum_are_preserved(self):
        result = self.install(); self.assertTrue(result['ok'])
        exe = Path(result['result']['executable']); exe.write_bytes(b'my file')
        self.assertFalse(self.install()['ok']); self.assertEqual(exe.read_bytes(), b'my file')
        self.assertFalse(self.install(expected='0' * 64)['ok'])

    def test_traversal_is_blocked(self):
        self.assertFalse(self.install({'app/../../escape.txt': b'bad'})['ok'])
        self.assertFalse(self.local.exists())

    def test_unowned_folder_is_preserved(self):
        root = self.local / 'Cloudragon/MobaQuickConnect'; root.mkdir(parents=True)
        note = root / 'original'; note.write_text('keep')
        self.assertFalse(self.install()['ok']); self.assertEqual(note.read_text(), 'keep')

    def test_unrelated_startup_link_is_not_removed(self):
        self.assertTrue(self.install()['ok'])
        script = '. ' + quote(ROOT / 'windows/Shortcuts.ps1') + ';[Cloudragon.Moba.Shortcuts]::Save(' + quote(self.startup / 'Moba Quick Connect.lnk') + ',' + quote(Path(os.environ['WINDIR']) / 'System32/cmd.exe') + ",'','','unrelated fixture',1);Write-Output 'RESULT:{\"ok\":true}'"
        self.invoke(script)
        self.assertTrue((self.startup / 'Moba Quick Connect.lnk').exists())
        self.assertFalse(self.startup_action('Disable')['ok'])
        self.assertTrue((self.startup / 'Moba Quick Connect.lnk').exists())


if __name__ == '__main__':
    unittest.main()
