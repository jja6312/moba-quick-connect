# Shared-session launcher recovery

Maintenance source for an existing portable shared-session installation. This is
separate from the Quick Connect desktop executable. It is not an installer for a
new MobaXterm installation and does not contain MobaXterm, configuration, sessions,
key files, or credentials.

The expected layout is an existing `MobaXterm` application directory containing
`Start-MobaXterm.ps1`, `Portable-SessionPaths.psm1`, the application executable and
an INI template. Its parent contains `mobaxterm-sessions.mxtsessions` and
`portable-keys.json`. The existing launcher derives the local device directory
from the synchronization root. Retain the actual installation's device profile;
this maintenance change does not migrate profiles or recreate shortcuts.

`Session-Lifecycle.psm1` adds an exclusive OS file lease for the whole run, owner
identity in new pending records, and local `lifecycle.jsonl` events. A persistent
`session-run.lock` filename is normal; the open OS handle determines ownership.
Do not delete that file to bypass an active publisher.

On startup, an old pending record can be archived automatically only when:

- No MobaXterm app or shared-session publisher is active.
- The marker is a valid legacy record or a supported version 2 record whose
  recorded publisher has exited.
- The current local view still matches its recorded initial hash.
- Private backups of the INI, view and marker have verified hashes, and the
  process state and all relevant files are unchanged on a second check.

Recovery moves only the marker into the local device's `recovery` directory.
It does not publish an old view over a newer shared source. Edited views,
unknown records, active owners, backup failures and races remain blocked for
review. Normal exit keeps the existing compare-and-swap publication and conflict
preservation behavior. Key references continue to use the installation's original
key files; this change does not create or migrate a key cache.

Before replacing launcher code, close MobaXterm normally and verify that its
publisher has exited. Back up the old launcher. Install `Session-Lifecycle.psm1`
beside the script, then replace `Start-MobaXterm.ps1`. Existing CMD and shortcuts
that invoke that script keep working. Do not overwrite live session or INI data.
Rollback restores launcher code only after both app and publisher have exited.

## Verification

Run `python -m unittest discover -s tests -q` on Windows. The lifecycle tests use
Windows PowerShell 5.1 and temporary synthetic sessions. They cover unchanged
recovery, edited and malformed markers, live owners, process command variants,
file and process races, concurrent leases, an intentionally terminated test-owned
publisher, read-only validation, and the whole launcher with a harmless fixture
executable. They never terminate the user's MobaXterm or connect to a server.

`Test-InstalledPackage.ps1 -PackageDirectory <existing-windows-setup> -MobaXtermExe
<existing-executable> -ScratchDirectory <temporary-directory>` exercises an
existing versioned installation package using synthetic data and `-NoShortcuts`.
Its original-key assertion reflects the current path module's behavior.

These tests cannot establish why an earlier publisher process disappeared. For
the actual installation, verify startup, normal UI close, publisher completion,
and another startup. Inspect local lifecycle events if a future interruption
occurs. Do not publish private INI files, session views, recovery copies or error
logs to GitHub.
