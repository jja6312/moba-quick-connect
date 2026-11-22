import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import core

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'windows/shared-launcher'
PS=str(Path(os.environ.get('WINDIR','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe')


def q(path):return "'"+str(path).replace("'","''")+"'"


@unittest.skipUnless(os.name=='nt','Windows file sharing and PowerShell required')
class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name);self.device=self.base/"한글 & O'Neil";self.device.mkdir()
        row=core.normalize({**core.new_row(core.DEFAULTS),'host':'192.0.2.1','name':'fixture','folder':'demo'})
        self.source=self.base/'source.mxtsessions';self.source.write_bytes(core.render_sessions([row]).encode('ascii'))
        self.view=self.device/'sessions-local.mxtsessions';self.view.write_bytes(self.source.read_bytes())
        self.ini=self.device/'MobaXterm.ini';self.ini.write_bytes(b'[Misc]\r\nPrivateSetting=preserve-opaque-bytes\r\n')
        self.pending=self.device/'pending-edit.json'
        digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.record={'SourceHash':digest,'InitialViewHash':digest,'CreatedUtc':'2026-11-22T00:00:00Z'}
        self.pending.write_text(json.dumps(self.record),encoding='utf-8')

    def tearDown(self):self.temp.cleanup()

    def ps(self,body):
        code='[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$ErrorActionPreference=\'Stop\';Import-Module '+q(SCRIPTS/'Session-Lifecycle.psm1')+' -Force -DisableNameChecking;'
        code+="try{"+body+";Write-Output 'RESULT:{\"ok\":true}'}catch{Write-Output ('RESULT:'+(@{ok=$false;error=$_.Exception.Message;stack=$_.ScriptStackTrace}|ConvertTo-Json -Compress))}"
        result=subprocess.run([PS,'-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        return json.loads(next(line[7:] for line in result.stdout.decode('utf-8',errors='replace').splitlines() if line.startswith('RESULT:')))

    def recover(self,apps=0,publishers=0,hook=''):
        code='$lease=Enter-MobaRunLock '+q(self.device)+';try{Recover-MobaUnchangedPending -Directory '+q(self.device)+' -Source '+q(self.source)+" -LauncherPath 'fixture.ps1' -OwnerProbe { [pscustomobject]@{Apps="+str(apps)+';Publishers='+str(publishers)+'} }'
        if hook:code+=' -BeforeRecheck {'+hook+'}'
        return self.ps(code+'|Out-Null}finally{$lease.Dispose()}')

    def test_unchanged_legacy_marker_is_archived_with_verified_data_backups(self):
        before={p:p.read_bytes() for p in (self.source,self.view,self.ini,self.pending)}
        result=self.recover();self.assertTrue(result['ok'],result)
        self.assertFalse(self.pending.exists())
        archive=next((self.device/'recovery').iterdir())
        for p in (self.ini,self.view):self.assertEqual((archive/(p.name+'.before')).read_bytes(),before[p]);self.assertEqual(p.read_bytes(),before[p])
        self.assertEqual((archive/'pending-edit.recovered.json').read_bytes(),before[self.pending])
        self.assertEqual(self.source.read_bytes(),before[self.source])

    def test_unpublished_changes_are_not_archived_or_overwritten(self):
        self.view.write_bytes(b'local edited sessions')
        result=self.recover();self.assertFalse(result['ok']);self.assertIn('Unpublished',result['error'])
        self.assertTrue(self.pending.exists());self.assertFalse((self.device/'recovery').exists())
        self.assertEqual(self.view.read_bytes(),b'local edited sessions')

    def test_other_device_change_with_unedited_view_keeps_latest_source(self):
        self.source.write_bytes(b'new other-device version')
        self.assertTrue(self.recover()['ok'])
        self.assertEqual(self.source.read_bytes(),b'new other-device version')

    def test_app_or_publisher_presence_blocks_even_with_unchanged_files(self):
        for apps,publishers in ((1,0),(0,1)):
            result=self.recover(apps,publishers);self.assertFalse(result['ok']);self.assertTrue(self.pending.exists())
        self.assertFalse((self.device/'recovery').exists())

    def test_live_recorded_publisher_blocks_independently_of_probe(self):
        code='$record=Get-Content -LiteralPath '+q(self.pending)+" -Raw|ConvertFrom-Json;$record|Add-Member Schema 2;$record|Add-Member RunId ([Guid]::NewGuid().ToString('N'));$record|Add-Member PublisherPid $PID;$record|Add-Member PublisherStartedUtc ([Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime().ToString('o'));[IO.File]::WriteAllText("+q(self.pending)+",($record|ConvertTo-Json));Recover-MobaUnchangedPending -Directory "+q(self.device)+' -Source '+q(self.source)+" -LauncherPath 'fixture' -OwnerProbe {[pscustomobject]@{Apps=0;Publishers=0}}"
        result=self.ps(code);self.assertFalse(result['ok']);self.assertIn('still active',result['error']);self.assertTrue(self.pending.exists())

    def test_invalid_or_partial_records_are_preserved(self):
        for content in ('{','{}',json.dumps({**self.record,'SourceHash':'bad'}),json.dumps({**self.record,'CreatedUtc':'not-a-date'})):
            self.pending.write_text(content,encoding='utf-8')
            self.assertFalse(self.recover()['ok']);self.assertEqual(self.pending.read_text(encoding='utf-8'),content)

    def test_unknown_schema_and_incomplete_owner_are_preserved(self):
        for extra in ({'Schema':99},{'Schema':2},{'PublisherPid':123},{'Schema':2,'RunId':'0'*32,'PublisherPid':123}):
            self.pending.write_text(json.dumps({**self.record,**extra}),encoding='utf-8')
            result=self.recover();self.assertFalse(result['ok']);self.assertTrue(self.pending.exists())

    def test_legacy_publisher_case_and_relative_paths_block_recovery(self):
        path=r'C:\App\Start-MobaXterm.ps1'
        for command in (r'powershell.exe -File "c:\APP\START-MOBAXTERM.PS1"',r'powershell.exe -File .\Start-MobaXterm.ps1',r'pwsh.exe -Command "& .\Start-MobaXterm.ps1"'):
            result=self.ps('if(-not (Test-MobaPublisherCommand '+q(command)+' '+q(path)+")){throw 'Legacy publisher was missed'}")
            self.assertTrue(result['ok'],result)

    def test_concurrent_source_change_after_backup_aborts_recovery(self):
        result=self.recover(hook='[IO.File]::WriteAllText('+q(self.source)+",'concurrent update')")
        self.assertFalse(result['ok']);self.assertIn('Files changed',result['error'])
        self.assertTrue(self.pending.exists());self.assertEqual(self.source.read_text(),'concurrent update')

    def test_view_edit_during_backup_is_preserved(self):
        result=self.recover(hook='[IO.File]::WriteAllText('+q(self.view)+",'new unsaved edit')")
        self.assertFalse(result['ok']);self.assertTrue(self.pending.exists())
        self.assertEqual(self.view.read_text(),'new unsaved edit')

    def test_abnormally_ended_fixture_owner_releases_lease_and_recovers_next_start(self):
        ready=self.base/'ready'
        code='Import-Module '+q(SCRIPTS/'Session-Lifecycle.psm1')+' -DisableNameChecking;$lock=Enter-MobaRunLock '+q(self.device)+';$r=Get-Content -LiteralPath '+q(self.pending)+" -Raw|ConvertFrom-Json;$r|Add-Member Schema 2;$r|Add-Member RunId ([Guid]::NewGuid().ToString('N'));$r|Add-Member PublisherPid $PID;$r|Add-Member PublisherStartedUtc ([Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime().ToString('o'));[IO.File]::WriteAllText("+q(self.pending)+",($r|ConvertTo-Json));[IO.File]::WriteAllText("+q(ready)+",'ready');Start-Sleep -Seconds 60"
        child=subprocess.Popen([PS,'-NoLogo','-NoProfile','-NonInteractive','-Command',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+10
            while not ready.exists() and time.monotonic()<deadline:time.sleep(0.05)
            self.assertTrue(ready.exists())
            self.assertFalse(self.recover()['ok'])
            # Only this test-owned fixture process is terminated to reproduce a
            # supervisor crash. No MobaXterm or user application is targeted.
            child.kill();child.wait(timeout=10)
            result=self.recover();self.assertTrue(result['ok'],result)
            self.assertFalse(self.pending.exists())
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=10)

    def test_second_owner_check_blocks_starting_writer(self):
        marker=self.base/'writer-started'
        code='$probe={if([IO.File]::Exists('+q(marker)+')){[pscustomobject]@{Apps=0;Publishers=1}}else{[pscustomobject]@{Apps=0;Publishers=0}}};$lease=Enter-MobaRunLock '+q(self.device)+';try{Recover-MobaUnchangedPending -Directory '+q(self.device)+' -Source '+q(self.source)+" -LauncherPath 'fixture' -OwnerProbe $probe -BeforeRecheck {[IO.File]::WriteAllText("+q(marker)+",'ready')}|Out-Null}finally{$lease.Dispose()}"
        result=self.ps(code);self.assertFalse(result['ok']);self.assertIn('became active',result['error']);self.assertTrue(self.pending.exists())

    def test_os_lease_blocks_concurrent_open_and_releases_without_deleting_file(self):
        body='$first=Enter-MobaRunLock '+q(self.device)+";$blocked=$false;try{try{$second=Enter-MobaRunLock "+q(self.device)+";$second.Dispose()}catch{$blocked=$true}}finally{$first.Dispose()};if(-not $blocked){throw 'Concurrent writer was allowed'};$third=Enter-MobaRunLock "+q(self.device)+';$third.Dispose()'
        self.assertTrue(self.ps(body)['ok']);self.assertTrue((self.device/'session-run.lock').exists())

    def fixture_deployment(self):
        sync=self.base/'synthetic-sync';app=sync/'convinient/MobaXterm';app.mkdir(parents=True)
        for name in ('Start-MobaXterm.ps1','Session-Lifecycle.psm1','Portable-SessionPaths.psm1'):shutil.copy2(SCRIPTS/name,app/name)
        canonical=app.parent/'mobaxterm-sessions.mxtsessions';canonical.write_bytes(self.source.read_bytes())
        (app.parent/'portable-keys.json').write_text('{"schema":1,"aliases":{}}')
        (app/'MobaXterm.ini').write_bytes(b'[Misc]\r\nHomeDir=old\r\nAutoRefreshSharedSessions=0\r\n[SharedSessions0]\r\nFilePath=old\r\n')
        local=self.base/'local-data';ns=hashlib.sha256(str(sync).lower().encode()).hexdigest()[:16]
        device=local/'MobaXtermPortable'/ns;device.mkdir(parents=True)
        shutil.copy2(app/'MobaXterm.ini',device/'MobaXterm.ini')
        (device/'sessions-local.mxtsessions').write_bytes(canonical.read_bytes())
        (device/'pending-edit.json').write_text(json.dumps(self.record))
        return app,canonical,local,device

    def test_validate_is_read_only_and_prepare_preserves_pending(self):
        app,canonical,local,device=self.fixture_deployment()
        before={p:p.read_bytes() for p in device.iterdir()}
        env={**os.environ,'LOCALAPPDATA':str(local)}
        result=subprocess.run([PS,'-NoLogo','-NoProfile','-File',str(app/'Start-MobaXterm.ps1'),'-ValidateOnly'],env=env,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        self.assertEqual({p:p.read_bytes() for p in device.iterdir()},before)
        result=subprocess.run([PS,'-NoLogo','-NoProfile','-File',str(app/'Start-MobaXterm.ps1'),'-PrepareOnly'],env=env,capture_output=True,timeout=30)
        self.assertNotEqual(result.returncode,0)
        for p,content in before.items():self.assertEqual(p.read_bytes(),content)

    def test_real_launcher_recovers_then_completes_an_owned_synthetic_process(self):
        app,canonical,local,device=self.fixture_deployment()
        shutil.copy2(Path(os.environ['WINDIR'])/'System32/where.exe',app/'MobaXterm_Test.exe')
        result=subprocess.run([PS,'-NoLogo','-NoProfile','-File',str(app/'Start-MobaXterm.ps1'),'-NoDialogs'],env={**os.environ,'LOCALAPPDATA':str(local)},capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        self.assertFalse((device/'pending-edit.json').exists())
        self.assertEqual(canonical.read_bytes(),self.source.read_bytes())
        events=[json.loads(line)['event'] for line in (device/'lifecycle.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events,['unchanged-pending-archived','run-started','application-started','application-exited','run-completed'])


if __name__=='__main__':unittest.main()
