"""Local connection model. Never reads key contents or saved credentials."""
from __future__ import annotations

import copy
import csv
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

from vendor import mobaxterm_sessions as codec

VERSION = "1.3.1"
FIELDS = ("host", "protocol", "name", "user", "port", "key_path", "folder",
          "bastion_host", "bastion_user", "bastion_port", "bastion_key_path")
HEADERS = ("접속 IP", "방식", "연결 이름", "사용자", "포트", "SSH 키 경로", "저장 폴더",
           "Bastion 호스트", "Bastion 사용자", "Bastion 포트", "Bastion 키 경로")
DEFAULTS = {
    "SSH": {"user": "opc", "port": "22", "key_path": "", "folder": "Quick Connect",
            "bastion_host": "", "bastion_user": "opc", "bastion_port": "22", "bastion_key_path": ""},
    "RDP": {"user": "Administrator", "port": "3389", "key_path": "", "folder": "Quick Connect",
            "bastion_host": "", "bastion_user": "opc", "bastion_port": "22", "bastion_key_path": ""},
}


def default_state():
    return {"version": 1, "moba_exe": "", "active_profile": "기본 설정",
            "profiles": {"기본 설정": copy.deepcopy(DEFAULTS)}, "connections": []}


def local_root():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "MobaQuickConnect"


def safe_text(value, label, *, folder=False):
    value = str(value or "").strip()
    if any(ord(c) < 32 for c in value) or any(c in value for c in "#%=\r\n"):
        raise ValueError(f"{label}: 줄바꿈과 #, %, = 문자는 사용할 수 없습니다.")
    if label == "연결 이름" and any(c in value for c in "[]"):
        raise ValueError("연결 이름에 [ 또는 ] 문자는 사용할 수 없습니다.")
    if folder:
        value = value.replace("/", "\\").strip("\\")
        if any(p in (".", "..") for p in value.split("\\")):
            raise ValueError("저장 폴더에 . 또는 .. 경로는 사용할 수 없습니다.")
    if len(value) > 1024:
        raise ValueError(f"{label}: 입력이 너무 깁니다.")
    return value


def host_value(value, label="IP / 호스트"):
    value = safe_text(value, label)
    if not value:
        raise ValueError(f"{label}를 입력하세요.")
    value = value.removeprefix("[").removesuffix("]")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if re.fullmatch(r"[\d.]+", value) or not re.fullmatch(
            r"(?=.{1,253}\.?$)[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\.?", value):
        raise ValueError(f"{label}: 올바른 IP 주소 또는 호스트 이름을 입력하세요.")
    return value


def port_value(value, label="포트"):
    try:
        port = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValueError(f"{label}는 1~65535 사이 숫자여야 합니다.") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"{label}는 1~65535 사이 숫자여야 합니다.")
    return str(port)


def new_row(profile, protocol="SSH"):
    return {"host": "", "protocol": protocol, "name": "", **copy.deepcopy(profile[protocol])}


def normalize(row, *, check_keys=False):
    protocol = str(row.get("protocol", "SSH")).strip().upper()
    if protocol not in DEFAULTS:
        raise ValueError("방식은 SSH 또는 RDP를 선택하세요.")
    result = {f: safe_text(row.get(f, ""), HEADERS[FIELDS.index(f)], folder=f == "folder") for f in FIELDS}
    result["protocol"] = protocol
    result["host"] = host_value(result["host"])
    result["port"] = port_value(result["port"] or DEFAULTS[protocol]["port"])
    result["name"] = result["name"] or result["host"] + (" (RDP)" if protocol == "RDP" else "")
    if not result["user"]:
        raise ValueError("사용자를 입력하세요.")
    if protocol == "RDP":
        result["key_path"] = ""
    if result["bastion_host"]:
        result["bastion_host"] = host_value(result["bastion_host"], "Bastion 호스트")
        result["bastion_port"] = port_value(result["bastion_port"] or "22", "Bastion 포트")
        if not result["bastion_user"]:
            raise ValueError("Bastion 사용자를 입력하세요.")
        if not result["bastion_key_path"] and protocol == "SSH":
            result["bastion_key_path"] = result["key_path"]
    else:
        for field in FIELDS[7:]:
            result[field] = ""
    if check_keys:
        for field in ("key_path", "bastion_key_path"):
            if result[field] and not Path(os.path.expandvars(os.path.expanduser(result[field]))).is_file():
                raise ValueError(f"{HEADERS[FIELDS.index(field)]}: 파일을 찾을 수 없습니다. 경로를 확인하세요.")
    return result


def validate_batch(rows, *, check_keys=False):
    valid, errors, seen = [], [], set()
    for index, row in enumerate(rows, 1):
        if not str(row.get("host", "")).strip():
            continue
        try:
            item = normalize(row, check_keys=check_keys)
            identity = (item["folder"].casefold(), item["name"].casefold())
            if identity in seen:
                raise ValueError("같은 폴더에 같은 연결 이름이 있습니다.")
            seen.add(identity)
            valid.append(item)
        except ValueError as exc:
            errors.append(f"{index}행: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    if not valid:
        raise ValueError("IP / 호스트를 한 개 이상 입력하세요.")
    return valid


def session_line(row):
    row = normalize(row)
    if row["protocol"] == "SSH":
        return codec.build_line(codec.make_session(row))
    # RDP #91# field layout verified against a local 25.2 exported bookmark.
    # Only public numeric defaults remain; no original names, hosts or paths.
    fields = ["4", row["host"], row["port"], row["user"], "0", "0", "0", "0", "-1", "0",
              "0", "-1", "", row["bastion_host"], row["bastion_port"], row["bastion_user"],
              "0", "0", row["bastion_key_path"], "-1", "", "-1", "-1", "0", "-1", "0",
              "-1", "0", "0", "0", "0", ""]
    tail = codec.build_line(codec.make_session({"host": "192.0.2.1", "name": "template"})).split("#MobaFont", 1)[1]
    return row["name"] + "=#91#" + "%".join(fields) + "#MobaFont" + tail


def render_sessions(rows, *, root_session=None):
    grouped = {}
    if root_session is not None:
        grouped[""] = [normalize({**root_session, "folder": ""})]
    for row in rows:
        row = normalize(row)
        if root_session is not None and row == normalize(root_session):
            continue
        grouped.setdefault(row["folder"], []).append(row)
    lines = []
    for index, (folder, items) in enumerate(grouped.items()):
        lines += ["[Bookmarks]" if index == 0 else f"[Bookmarks_{index}]", f"SubRep={folder}", "ImgNum=41"]
        lines.extend(session_line(item) for item in items)
        lines.append("")
    return "\r\n".join(lines)


def export_bytes(rows, *, root_session=None):
    # 25.x uses the Windows ANSI code page for session files.
    import locale
    encoding = locale.getencoding() if os.name == "nt" else "cp949"
    try:
        return render_sessions(rows, root_session=root_session).encode(encoding, errors="strict")
    except UnicodeEncodeError:
        raise ValueError("현재 Windows 문자셋에 없는 문자가 있습니다. 연결 이름과 폴더 이름을 확인하세요.") from None


def parse_clipboard(text):
    if len(text) > 2_000_000:
        raise ValueError("한 번에 붙여넣을 수 있는 크기를 초과했습니다.")
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if len(rows) > 2000 or any(len(r) > len(FIELDS) for r in rows):
        raise ValueError("한 번에 최대 2,000행과 표의 열 개수까지 붙여넣을 수 있습니다.")
    return rows


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else local_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "settings.json"
        self.state = default_state()
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or not isinstance(loaded.get("profiles"), dict) or not loaded["profiles"]:
                    raise ValueError("invalid profile data")
                self.state.update(loaded)
                for profile in self.state["profiles"].values():
                    for kind in DEFAULTS:
                        profile[kind] = {**DEFAULTS[kind], **profile.get(kind, {})}
                if self.state["active_profile"] not in self.state["profiles"]:
                    self.state["active_profile"] = next(iter(self.state["profiles"]))
            except (ValueError, KeyError, TypeError):
                raise ValueError("기본값 파일을 읽을 수 없습니다. 기존 파일은 보존했습니다.") from None

    @property
    def profile(self):
        return self.state["profiles"][self.state["active_profile"]]

    def save(self):
        raw = json.dumps(self.state, ensure_ascii=False, indent=2).encode("utf-8")
        if self.path.exists():
            old = self.path.read_bytes()
            self._atomic(self.root / "settings.previous.json", old)
        self._atomic(self.path, raw)

    def _atomic(self, target, raw):
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def add(self, rows):
        rows = validate_batch(rows, check_keys=True)
        existing = {(c["folder"].casefold(), c["name"].casefold()): c for c in self.state["connections"]}
        for row in rows:
            identity = (row["folder"].casefold(), row["name"].casefold())
            if identity in existing and existing[identity] != row:
                raise ValueError(f"{row['name']}: 같은 이름의 연결이 이미 있습니다. 연결 이름을 바꿔주세요.")
        candidate = {**existing, **{(r["folder"].casefold(), r["name"].casefold()): r for r in rows}}
        raw = export_bytes(list(candidate.values()))
        previous = self.state["connections"]
        self.state["connections"] = list(candidate.values())
        try:
            self.save()
        except Exception:
            self.state["connections"] = previous
            raise
        self._atomic(self.root / "Quick Connect.mxtsessions", raw)
        return rows

    def prepare_launch(self, row=None):
        rows = self.state["connections"]
        if not rows:
            raise ValueError("등록한 연결이 없습니다.")
        launches = self.root / "launches"
        launches.mkdir(exist_ok=True)
        ini = launches / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:10] + ".ini")
        with ini.open("xb") as output:
            output.write(b"[Misc]\r\nSingleInstance=0\r\nAllowMultiInstances=1\r\n\r\n")
            output.write(export_bytes(rows, root_session=row))
        return ini


def launch_arguments(exe, ini, row=None, *, test_exit=False):
    path = Path(exe)
    if not path.is_file() or path.suffix.lower() != ".exe" or "mobaxterm" not in path.name.lower():
        raise ValueError("설정에서 MobaXterm 실행 파일을 선택하세요.")
    args = [str(path), "-i", str(ini)]
    if row is not None:
        args += ["-bookmark", normalize(row)["name"]]
    if test_exit:
        args += ["-exitwhendone"]
    return args


def launch(exe, ini, row=None):
    args = launch_arguments(exe, ini, row)
    return subprocess.Popen(args, shell=False, cwd=str(Path(exe).parent))
