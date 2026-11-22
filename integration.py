"""Add bookmarks to the user's existing MobaXterm deployment.

No private key/password content is read. Existing file bytes are preserved;
only new bookmark lines/sections are inserted. Running INIs are never written.
Portable shared-session publishers must finish before their source is edited.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
from dataclasses import asdict, dataclass
import hashlib
import locale
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

import psutil
import core


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    for enc in ("utf-8-sig", locale.getencoding(), "cp949", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            pass
    raise ValueError("MobaXterm 파일의 인코딩을 확인하세요.")


def sections(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw:
        raise ValueError("이 설정 파일의 인코딩은 직접 편집할 수 없습니다.")
    matches = list(re.finditer(rb"(?m)^(?:\xef\xbb\xbf)?\[([^\r\n\]]+)\][ \t]*(?:\r?\n|$)", raw))
    return [(m.group(1).decode("ascii", errors="replace"), m.start(),
             matches[i + 1].start() if i + 1 < len(matches) else len(raw)) for i, m in enumerate(matches)]


def section_values(raw, section):
    found = next(((s, e) for name, s, e in sections(raw) if name.casefold() == section.casefold()), None)
    if not found:
        return {}
    values = {}
    for line in raw[found[0]:found[1]].splitlines()[1:]:
        if b"=" in line and not line.startswith((b";", b"#")):
            key, value = line.split(b"=", 1)
            values[key.decode("ascii", errors="replace").strip()] = decode(value).strip()
    return values


def shared_files(ini):
    raw = Path(ini).read_bytes()
    result = []
    for name, _, _ in sections(raw):
        if re.fullmatch(r"SharedSessions\d+", name, re.I):
            value = section_values(raw, name).get("FilePath", "")
            if value and "://" not in value:
                result.append((name, Path(value)))
    return result


def same_connection(record, row):
    try:
        parts = record.split(b"#")
        fields = [decode(v) for v in parts[2].split(b"%")]
        if row["protocol"] == "SSH" and fields[0] == "0":
            actual = (fields[1], fields[2], fields[3], fields[14], fields[8], fields[9], fields[10], fields[15])
        elif row["protocol"] == "RDP" and fields[0] == "4":
            actual = (fields[1], fields[2], fields[3], "", fields[13], fields[14], fields[15], fields[18])
        else:
            return False
        expected = tuple(row[f] for f in ("host", "port", "user", "key_path", "bastion_host", "bastion_port", "bastion_user", "bastion_key_path"))
        # Empty unused gateway port/user fields are semantically irrelevant.
        if not expected[4]:
            actual = actual[:4] + ("", "", "", "")
        return actual == expected
    except (IndexError, ValueError, UnicodeError):
        return False


def merge_bookmarks(raw, rows):
    """Preserve mixed-encoding original bytes and every unrelated section."""
    rows = core.validate_batch(rows)
    parsed = sections(raw)
    folders, identifiers = {}, set()
    for name, start, end in parsed:
        identifiers.add(name.casefold())
        if not re.fullmatch(r"Bookmarks(?:_\d+)?", name, re.I):
            continue
        folder = section_values(raw, name).get("SubRep", "").casefold()
        existing = {}
        for line in raw[start:end].splitlines()[1:]:
            if b"=#" in line:
                label, record = line.split(b"=", 1)
                existing[decode(label).casefold()] = record
        folders.setdefault(folder, (end, existing))
    grouped = {}
    for row in rows:
        folder = row["folder"].casefold()
        if folder in folders and row["name"].casefold() in folders[folder][1]:
            if not same_connection(folders[folder][1][row["name"].casefold()], row):
                raise ValueError(f"{row['name']}: 같은 이름의 기존 세션이 있습니다.")
            continue
        grouped.setdefault(folder, []).append(row)
    newline = b"\r\n" if b"\r\n" in raw or not raw else b"\n"
    encoding = "utf-8" if raw.startswith(b"\xef\xbb\xbf") else locale.getencoding() if os.name == "nt" else "cp949"
    inserts = {}
    suffix = bytearray()
    for folder, items in grouped.items():
        try:
            lines = newline.join(core.session_line(row).encode(encoding, errors="strict") for row in items) + newline
            if folder in folders:
                at = folders[folder][0]
                inserts[at] = inserts.get(at, b"") + (newline if at and raw[at-1:at] != b"\n" else b"") + lines
            else:
                index = 0
                while ("bookmarks" if index == 0 else f"bookmarks_{index}") in identifiers:
                    index += 1
                section = "Bookmarks" if index == 0 else f"Bookmarks_{index}"
                identifiers.add(section.casefold())
                suffix += (b"[" + section.encode() + b"]" + newline + b"SubRep=" +
                           items[0]["folder"].encode(encoding) + newline + b"ImgNum=41" + newline + lines + newline)
        except UnicodeEncodeError:
            raise ValueError("이름이나 폴더에 현재 Windows 문자셋으로 저장할 수 없는 문자가 있습니다.") from None
    output = raw
    for at, data in sorted(inserts.items(), reverse=True):
        output = output[:at] + data + output[at:]
    if suffix:
        output += (newline if output and not output.endswith(b"\n") else b"") + bytes(suffix)
    return output, sum(len(v) for v in grouped.values())


@dataclass
class Target:
    exe: str
    ini: str
    session_file: str
    launcher: str = ""
    launcher_sha256: str = ""
    pending: str = ""
    shared: bool = False

    def to_dict(self):
        return asdict(self)


def process_ini(exe, command):
    for i, value in enumerate(command[:-1]):
        if value.lower() == "-i":
            return str(Path(command[i + 1]).resolve())
    portable = Path(exe).parent / "MobaXterm.ini"
    if portable.is_file():
        return str(portable.resolve())
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Mobatek\MobaXterm") as handle:
                path = winreg.QueryValueEx(handle, "LastIniPath")[0]
                if Path(path).is_file():
                    return str(Path(path).resolve())
        except OSError:
            pass
    return str(Path(os.environ.get("APPDATA", "")) / "MobaXterm/MobaXterm.ini")


def running_moba():
    result = []
    for process in psutil.process_iter(["pid", "name"]):
        if not str(process.info.get("name", "")).lower().startswith("mobaxterm"):
            continue
        try:
            exe, args = process.exe(), process.cmdline()
            if exe:
                result.append((process.pid, exe, process_ini(exe, args)))
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    return result


def describe_target(exe, ini):
    ini = Path(ini).resolve()
    if not ini.is_file():
        raise ValueError("MobaXterm 설정 파일을 찾을 수 없습니다.")
    shares = shared_files(ini)
    if len(shares) > 1:
        raise ValueError("공유 세션 파일이 여러 개입니다. 등록할 설정 파일을 확인하세요.")
    if not shares:
        return Target(str(exe), str(ini), str(ini))
    section, view = shares[0]
    pending = ini.parent / "pending-edit.json"
    # Known existing portable deployment: source and view must never be edited
    # independently while its exit-time publisher is active.
    directory = Path(exe).parent
    launcher = directory / "Start-MobaXterm.cmd"
    script = directory / "Start-MobaXterm.ps1"
    template = directory / "MobaXterm.ini"
    source = directory.parent / "mobaxterm-sessions.mxtsessions"
    if view.resolve() == (ini.parent / "sessions-local.mxtsessions").resolve() and all(
            p.is_file() for p in (launcher, script, template, source)):
        script_text = script.read_text(encoding="utf-8-sig")
        declared = dict(shared_files(template)).get(section)
        if (declared and declared.resolve() == source.resolve() and "Publish-MobaSource" in script_text
                and "pending-edit.json" in script_text):
            return Target(str(exe), str(ini), str(source.resolve()), str(launcher),
                          digest(launcher.read_bytes()), str(pending), True)
    if pending.exists():
        raise ValueError("공유 세션 실행기의 원본 경로를 확인하지 못했습니다. 기존 편집은 보존했습니다.")
    if not view.is_file():
        raise ValueError("공유 세션 파일을 찾을 수 없습니다.")
    return Target(str(exe), str(ini), str(view.resolve()), shared=True)


def find_target(exe="", remembered=None, preferred_pid=None):
    candidates = running_moba()
    # Old Quick Connect scratch windows are not the user's original profile.
    candidates = [c for c in candidates if not Path(c[2]).is_relative_to(core.local_root() / "launches")]
    if preferred_pid:
        exact = [c for c in candidates if c[0] == preferred_pid]
        if exact:
            return describe_target(exact[0][1], exact[0][2])
    if exe:
        selected = [c for c in candidates if os.path.normcase(c[1]) == os.path.normcase(exe)]
        if selected:
            candidates = selected
    contexts = {(os.path.normcase(c[1]), os.path.normcase(c[2])): c for c in candidates}
    if len(contexts) == 1:
        current = next(iter(contexts.values()))
        return describe_target(current[1], current[2])
    if len(contexts) > 1:
        raise ValueError("여러 MobaXterm 설정이 열려 있습니다. 대상 MobaXterm에서 단축키로 열어주세요.")
    if remembered:
        target = Target(**remembered)
        if all(Path(p).is_file() for p in (target.exe, target.ini, target.session_file)):
            return target
    if exe and Path(exe).is_file():
        return describe_target(exe, process_ini(exe, []))
    raise ValueError("MobaXterm을 먼저 실행해주세요.")


def matching_pids(target):
    return [pid for pid, exe, ini in running_moba() if os.path.normcase(exe) == os.path.normcase(target.exe)
            and os.path.normcase(ini) == os.path.normcase(target.ini)]


def request_normal_close(pids):
    """Application feature: WM_CLOSE only. Never terminate a MobaXterm process."""
    if not pids or os.name != "nt":
        return
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    user.EnumWindows.argtypes = [callback_type, W.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
    user.GetWindow.argtypes = [W.HWND, W.UINT]
    user.GetWindow.restype = W.HWND
    user.GetWindowTextLengthW.argtypes = [W.HWND]
    user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    @callback_type
    def close_window(hwnd, _):
        pid = W.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and not user.GetWindow(hwnd, 4) and user.GetWindowTextLengthW(hwnd) > 0:
            user.PostMessageW(hwnd, 0x10, 0, 0)
        return True
    user.EnumWindows(close_window, 0)


def restart(target):
    if target.launcher:
        if digest(Path(target.launcher).read_bytes()) != target.launcher_sha256:
            raise ValueError("MobaXterm 실행기가 변경됐습니다. 경로를 다시 확인하세요.")
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.ShellExecuteW.argtypes = [W.HWND, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, ctypes.c_int]
        shell.ShellExecuteW.restype = ctypes.c_ssize_t
        if shell.ShellExecuteW(None, "open", target.launcher, None, str(Path(target.launcher).parent), 0) <= 32:
            raise OSError("기존 MobaXterm 실행기를 열지 못했습니다.")
    else:
        subprocess.Popen([target.exe, "-i", target.ini], shell=False, cwd=str(Path(target.exe).parent))


def active_view_contains(target, rows):
    views = list(dict(shared_files(target.ini)).values()) if target.shared else [Path(target.ini)]
    for view in views:
        try:
            if view.is_file() and merge_bookmarks(view.read_bytes(), rows)[1] == 0:
                return True
        except ValueError:
            continue
    return False


@contextmanager
def registration_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stream = (root / "registration.lock").open("a+b")
    try:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        yield
    finally:
        stream.close()


def atomic_replace(path, before, after, backup_root):
    path, backup_root = Path(path), Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:10] + "-" + path.name + ".bak")
    with backup.open("xb") as output:
        output.write(before)
    if path.read_bytes() != before:
        raise ValueError("등록 대상이 다른 작업에서 변경됐습니다. 기존 파일을 보존했습니다.")
    fd, temporary = tempfile.mkstemp(prefix=".quick-connect-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(after)
            output.flush()
            os.fsync(output.fileno())
        if path.read_bytes() != before:
            raise ValueError("등록 대상이 변경됐습니다. 다시 시도해주세요.")
        os.replace(temporary, path)
        if path.read_bytes() != after:
            raise OSError("세션 저장 결과가 일치하지 않습니다.")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(backup)


def register(target, rows, root, progress=lambda message: None, *, timeout=25):
    rows = core.validate_batch(rows, check_keys=True)
    source = Path(target.session_file)
    with registration_lock(root):
        # Detect conflicts before interrupting an existing window.
        if target.shared and section_values(source.read_bytes(), "SharedSettings").get("AllowedEditors", "") != "*":
            raise ValueError("공유 세션이 읽기 전용입니다. 기존 편집 허용 설정을 확인해주세요.")
        original = source.read_bytes()
        _, requested_additions = merge_bookmarks(original, rows)
        pids = matching_pids(target)
        if not requested_additions and pids and active_view_contains(target, rows):
            return {"added": 0, "requested": len(rows), "target": target.to_dict(), "backup": None,
                    "source_sha256": digest(original), "active_view_verified": True}
        pending = Path(target.pending) if target.pending else None
        conflicts = pending.parent / "conflicts" if pending else None
        prior_conflicts = set(conflicts.glob("*")) if conflicts and conflicts.exists() else set()
        if pending and pending.exists() and not pids:
            raise ValueError("기존 공유 세션 편집이 마무리되지 않았습니다. pending 파일을 보존했습니다.")
        closed = False
        try:
            if pids:
                progress("MobaXterm을 종료합니다. 확인창이 뜨면 확인해주세요.")
                request_normal_close(pids)
                deadline = time.monotonic() + timeout
                while matching_pids(target):
                    if time.monotonic() > deadline:
                        raise ValueError("MobaXterm 종료 확인창을 처리한 뒤 다시 등록해주세요.")
                    time.sleep(0.15)
                closed = True
            if pending:
                deadline = time.monotonic() + 15
                while pending.exists() and time.monotonic() < deadline:
                    time.sleep(0.15)
                if pending.exists():
                    raise ValueError("기존 공유 세션 게시가 끝나지 않았습니다. 파일은 변경하지 않았습니다.")
                if conflicts and conflicts.exists() and set(conflicts.glob("*")) - prior_conflicts:
                    raise ValueError("기존 공유 세션에 동기화 충돌이 있습니다. 충돌 사본을 보존했습니다.")
            if matching_pids(target):
                raise ValueError("MobaXterm이 다시 실행됐습니다. 실행 중 설정은 변경하지 않았습니다.")
            progress("기존 세션에 추가합니다.")
            before = source.read_bytes()
            after, count = merge_bookmarks(before, rows)
            backup = atomic_replace(source, before, after, Path(root) / "backups") if after != before else None
            restart(target)
            deadline = time.monotonic() + 20
            while not matching_pids(target) and time.monotonic() < deadline:
                time.sleep(0.2)
            if not matching_pids(target):
                raise ValueError("세션은 저장됐으나 기존 MobaXterm의 재실행을 확인하지 못했습니다.")
            # Prove the refreshed active shared view contains the requested records.
            if not active_view_contains(target, rows):
                raise ValueError("세션은 저장됐으나 현재 MobaXterm 목록의 반영을 확인하지 못했습니다.")
            return {"added": count, "requested": len(rows), "target": target.to_dict(), "backup": backup,
                    "source_sha256": digest(after), "active_view_verified": True}
        except Exception:
            if closed and not matching_pids(target) and not (pending and pending.exists()):
                restart(target)
            raise
