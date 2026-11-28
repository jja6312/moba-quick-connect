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

    def test_duplicate_click_activates_injected_app_without_touching_active_data(self):
        before={p:p.read_bytes() for p in (self.pending,self.view,self.ini,self.source)}
        activated=self.base/'activated'
        result=self.ps('if(-not (Invoke-MobaExistingInstance -Directory '+q(self.device)+" -LauncherPath 'fixture' -OwnerProbe {[pscustomobject]@{Apps=1;Publishers=1}} -Activator {[IO.File]::WriteAllText("+q(activated)+",'activated')})){throw 'Existing app not handled'}")
        self.assertTrue(result['ok'],result);self.assertTrue(activated.exists())
        for p,data in before.items():self.assertEqual(p.read_bytes(),data)

    def test_publisher_only_click_defers_without_activating_or_touching_data(self):
        before={p:p.read_bytes() for p in (self.pending,self.view,self.ini,self.source)}
        result=self.ps('if(-not (Invoke-MobaExistingInstance -Directory '+q(self.device)+" -LauncherPath 'fixture' -OwnerProbe {[pscustomobject]@{Apps=0;Publishers=1}} -Activator {throw 'Unexpected UI activation'})){throw 'Publisher not handled'}")
        self.assertTrue(result['ok'],result)
        for p,data in before.items():self.assertEqual(p.read_bytes(),data)

    def test_no_active_owner_allows_normal_launch_without_activation(self):
        result=self.ps('if(Invoke-MobaExistingInstance -Directory '+q(self.device)+" -LauncherPath 'fixture' -OwnerProbe {[pscustomobject]@{Apps=0;Publishers=0}} -Activator {throw 'Unexpected UI activation'}){throw 'Normal launch was blocked'}")
        self.assertTrue(result['ok'],result)

    def test_actual_ps5_sharing_violation_is_busy_but_other_io_errors_are_not(self):
        body='$first=Enter-MobaRunLock '+q(self.device)+";try{try{$second=Enter-MobaRunLock "+q(self.device)+";throw 'Lock was not exclusive'}catch{if(-not $_.Exception.Data['MobaLauncherBusy']){throw 'Real sharing violation was not classified busy'}}}finally{$first.Dispose()}"
        result=self.ps(body);self.assertTrue(result['ok'],result)
        other=self.base/'bad-device';other.mkdir();(other/'session-run.lock').mkdir()
        result=self.ps("$failed=$false;try{$unexpected=Enter-MobaRunLock "+q(other)+";$unexpected.Dispose()}catch{$failed=$true;if($_.Exception.Data['MobaLauncherBusy']){throw 'Non-sharing IO error was hidden'}};if(-not $failed){throw 'Expected a real file error'}")
        self.assertTrue(result['ok'],result)

    def test_attempt_ignore_requires_exact_cim_identity_and_contender_stage(self):
        body='$attempt=Register-MobaAttempt '+q(self.device)+";$current=Get-CimInstance Win32_Process -Filter ('ProcessId='+$PID);$dir=Split-Path $attempt; & (Get-Module Session-Lifecycle) {param($entry,$dir) if(-not (Test-MobaContender $entry $dir)){throw 'Current contender was not recognized'};$fake=[pscustomobject]@{ProcessId=$entry.ProcessId;CreationDate=$entry.CreationDate.AddTicks(10)};if(Test-MobaContender $fake $dir){throw 'Reused PID identity was ignored'}} $current $dir;Set-MobaAttemptPublishing $attempt;& (Get-Module Session-Lifecycle) {param($entry,$dir) if(Test-MobaContender $entry $dir){throw 'Actual publisher was ignored'}} $current $dir"
        result=self.ps(body);self.assertTrue(result['ok'],result)

    def fixture_deployment(self):
        sync=self.base/'synthetic-sync';app=sync/'convinient/MobaXterm';app.mkdir(parents=True)
        for name in ('Start-MobaXterm.ps1','Session-Lifecycle.psm1','Portable-SessionPaths.psm1'):shutil.copy2(SCRIPTS/name,app/name)
        canonical=app.parent/'mobaxterm-sessions.mxtsessions';canonical.write_bytes(self.source.read_bytes())
        (app.parent/'portable-keys.json').write_text('{"schema":1,"aliases":{}}')
        (app/'MobaXterm.ini').write_bytes(b'[Misc]\r\nHomeDir=old\r\nAutoRefreshSharedSessions=0\r\n[SharedSessions0]\r\nFilePath=old\r\n')
        local=self.base/'local-data'
        # PowerShell resolves the script root through its Windows provider. A
        # runner's short-name/junction path can differ from Python's spelling.
        # Ask the read-only launcher for its device directory instead of
        # reproducing its namespace calculation with a different path spelling.
        probe=subprocess.run([PS,'-NoLogo','-NoProfile','-Command',
            '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);& '+q(app/'Start-MobaXterm.ps1')+' -ValidateOnly 3>$null'],
            env={**os.environ,'LOCALAPPDATA':str(local)},capture_output=True,timeout=30)
        self.assertEqual(probe.returncode,0,probe.stderr.decode(errors='replace'))
        device=Path(json.loads(probe.stdout.decode('utf-8-sig'))['DeviceDirectory']).resolve()
        self.assertTrue(device.is_relative_to(local.resolve()),f'Fixture {device} escaped isolated data {local.resolve()}')
        device.mkdir(parents=True)
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
        self.assertNotEqual(result.returncode,0,result.stdout.decode(errors='replace'))
        for p,content in before.items():self.assertEqual(p.read_bytes(),content)

    def test_real_launcher_recovers_then_completes_an_owned_synthetic_process(self):
        import psutil
        if any(p.info['name'].lower().startswith('mobaxterm') for p in psutil.process_iter(['name']) if p.info['name']):
            self.skipTest('A real user MobaXterm is active; whole-launcher fixture runs in clean Windows CI')
        app,canonical,local,device=self.fixture_deployment()
        shutil.copy2(Path(os.environ['WINDIR'])/'System32/where.exe',app/'MobaXterm_Test.exe')
        result=subprocess.run([PS,'-NoLogo','-NoProfile','-File',str(app/'Start-MobaXterm.ps1'),'-NoDialogs'],env={**os.environ,'LOCALAPPDATA':str(local)},capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        self.assertFalse((device/'pending-edit.json').exists(),result.stdout.decode(errors='replace'))
        self.assertEqual(canonical.read_bytes(),self.source.read_bytes())
        events=[json.loads(line)['event'] for line in (device/'lifecycle.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events,['unchanged-pending-archived','run-started','application-started','application-exited','run-completed'])

    def test_late_contender_retries_until_one_fresh_launcher_starts(self):
        import psutil
        if any(p.info['name'].lower().startswith('mobaxterm') for p in psutil.process_iter(['name']) if p.info['name']):
            self.skipTest('Real MobaXterm is active; synchronized full launcher race runs in clean Windows CI')
        app,canonical,local,device=self.fixture_deployment()
        self.pending.unlink()  # Main recovery fixtures are unrelated to this fresh startup.
        (device/'pending-edit.json').unlink()
        script=app/'Start-MobaXterm.ps1'
        text=script.read_text(encoding='utf-8-sig')
        root=q(self.base)
        text=text.replace('if(-not $PrepareOnly){$attempt=Register-MobaAttempt $localDir}',
            "if($env:MOBA_FIXTURE_ROLE -eq 'B'){[IO.File]::WriteAllText((Join-Path "+root+" 'b-ready'),'ready');while(-not [IO.File]::Exists((Join-Path "+root+" 'release-b'))){Start-Sleep -Milliseconds 30}}\nif(-not $PrepareOnly){$attempt=Register-MobaAttempt $localDir}")
        text=text.replace("if(-not $PrepareOnly -and $_.Exception.Data['MobaLauncherBusy']){",
            "if(-not $PrepareOnly -and $_.Exception.Data['MobaLauncherBusy']){if($env:MOBA_FIXTURE_ROLE -eq 'B'){[IO.File]::WriteAllText((Join-Path "+root+" 'b-busy'),'busy')}")
        text=text.replace("if($PrepareOnly){throw 'MobaXterm or its shared-session publisher is active. No files were replaced.'}",
            "if($PrepareOnly){throw 'MobaXterm or its shared-session publisher is active. No files were replaced.'};if($env:MOBA_FIXTURE_ROLE -eq 'A'){[IO.File]::WriteAllText((Join-Path "+root+" 'a-returning'),'ready');while(-not [IO.File]::Exists((Join-Path "+root+" 'release-a'))){Start-Sleep -Milliseconds 30}}")
        script.write_text(text,encoding='utf-8-sig')
        exe=app/'MobaXterm_Fixture.exe'
        compiled=self.ps("Add-Type -TypeDefinition 'using System.IO;using System.Threading;public static class Fixture{public static void Main(){File.AppendAllText(\"starts.fixture\",\"started\\n\");Thread.Sleep(1500);}}' -OutputAssembly "+q(exe)+' -OutputType WindowsApplication')
        self.assertTrue(compiled['ok'],compiled)
        children=[]
        def start(role):
            child=subprocess.Popen([PS,'-NoLogo','-NoProfile','-File',str(script),'-NoDialogs'],env={**os.environ,'LOCALAPPDATA':str(local),'MOBA_FIXTURE_ROLE':role},stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            children.append(child);return child
        def wait_file(name):
            end=time.monotonic()+12
            while not (self.base/name).exists() and time.monotonic()<end:time.sleep(.03)
            self.assertTrue((self.base/name).exists(),name)
        try:
            b=start('B');wait_file('b-ready')
            a=start('A');wait_file('a-returning')
            (self.base/'release-b').touch();wait_file('b-busy')
            (self.base/'release-a').touch()
            for child in children:
                out,err=child.communicate(timeout=20)
                self.assertEqual(child.returncode,0,(out+err).decode(errors='replace'))
            self.assertEqual((app/'starts.fixture').read_text().splitlines(),['started'])
            self.assertFalse((device/'pending-edit.json').exists())
            self.assertEqual(canonical.read_bytes(),self.source.read_bytes())
        finally:
            for name in ('release-a','release-b'):(self.base/name).touch(exist_ok=True)
            for child in children:
                if child.poll() is None:
                    try:child.communicate(timeout=10)
                    except subprocess.TimeoutExpired:child.kill();child.communicate()

    def test_simultaneous_fresh_clicks_start_exactly_one_fixture_app(self):
        import psutil
        if any(p.info['name'].lower().startswith('mobaxterm') for p in psutil.process_iter(['name']) if p.info['name']):
            self.skipTest('Real MobaXterm is active; fresh concurrent start runs in clean Windows CI')
        app,canonical,local,device=self.fixture_deployment()
        (device/'pending-edit.json').unlink()
        script=app/'Start-MobaXterm.ps1'
        text=script.read_text(encoding='utf-8-sig')
        text=text.replace('if(-not $PrepareOnly){$attempt=Register-MobaAttempt $localDir}',
            'if(-not $PrepareOnly){$attempt=Register-MobaAttempt $localDir};[IO.File]::WriteAllText((Join-Path '+q(self.base)+" ('ready-'+$env:MOBA_FIXTURE_ROLE)),'ready');while(-not [IO.File]::Exists((Join-Path "+q(self.base)+" 'go'))){Start-Sleep -Milliseconds 30}")
        script.write_text(text,encoding='utf-8-sig')
        compiled=self.ps("Add-Type -TypeDefinition 'using System.IO;using System.Threading;public static class Fixture{public static void Main(){File.AppendAllText(\"starts.fixture\",\"started\\n\");Thread.Sleep(3500);}}' -OutputAssembly "+q(app/'MobaXterm_Fixture.exe')+' -OutputType WindowsApplication')
        self.assertTrue(compiled['ok'],compiled)
        children=[]
        try:
            for role in ('A','B'):
                children.append(subprocess.Popen([PS,'-NoLogo','-NoProfile','-File',str(script),'-NoDialogs'],env={**os.environ,'LOCALAPPDATA':str(local),'MOBA_FIXTURE_ROLE':role},stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW))
            end=time.monotonic()+12
            while not all((self.base/('ready-'+role)).exists() for role in ('A','B')) and time.monotonic()<end:time.sleep(.03)
            self.assertTrue(all((self.base/('ready-'+role)).exists() for role in ('A','B')))
            (self.base/'go').touch()
            for child in children:
                out,err=child.communicate(timeout=20)
                self.assertEqual(child.returncode,0,(out+err).decode(errors='replace'))
            self.assertEqual((app/'starts.fixture').read_text().splitlines(),['started'])
            self.assertFalse((device/'pending-edit.json').exists())
            self.assertEqual(canonical.read_bytes(),self.source.read_bytes())
        finally:
            (self.base/'go').touch(exist_ok=True)
            for child in children:
                if child.poll() is None:
                    try:child.communicate(timeout=10)
                    except subprocess.TimeoutExpired:child.kill();child.communicate()


if __name__=='__main__':unittest.main()
