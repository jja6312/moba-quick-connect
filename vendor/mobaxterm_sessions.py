#!/usr/bin/env python3
"""Validate, generate, and safely apply MobaXterm SSH bookmark sessions."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ALIASES = {
    "folder": ("folder", "폴더"),
    "name": ("name", "session", "session_name", "세션명", "이름"),
    "host": ("host", "hostname", "ip", "호스트", "IP", "아이피"),
    "port": ("port", "포트"),
    "user": ("user", "username", "사용자", "계정"),
    "key_path": ("key_path", "key", "private_key", "키경로", "키"),
    "bastion_host": ("bastion_host", "bastion", "jump_host", "점프호스트", "배스천호스트"),
    "bastion_port": ("bastion_port", "jump_port", "점프포트", "배스천포트"),
    "bastion_user": ("bastion_user", "jump_user", "점프사용자", "배스천사용자"),
    "bastion_key_path": ("bastion_key_path", "bastion_key", "jump_key", "점프키경로", "배스천키경로"),
}
FORBIDDEN_KEYS = {"password", "passwd", "pwd", "비밀번호", "암호"}
SESSION_MARKER = "=#109#"


@dataclass(frozen=True)
class Session:
    folder: str
    name: str
    host: str
    port: int = 22
    user: str = "opc"
    key_path: str = ""
    bastion_host: str = ""
    bastion_port: int = 22
    bastion_user: str = "opc"
    bastion_key_path: str = ""


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def canonicalize(row: dict[str, Any]) -> dict[str, str]:
    normalized = {str(k).strip(): v for k, v in row.items() if k is not None}
    lowered = {k.lower(): v for k, v in normalized.items()}
    if any(k.lower() in FORBIDDEN_KEYS for k in normalized):
        raise ValueError("password columns are not supported")
    result: dict[str, str] = {}
    for field, aliases in ALIASES.items():
        result[field] = ""
        for alias in aliases:
            if alias in normalized:
                result[field] = clean(normalized[alias]); break
            if alias.lower() in lowered:
                result[field] = clean(lowered[alias.lower()]); break
    return result


def validate_component(value: str, label: str) -> None:
    if any(ch in value for ch in "\r\n=[]"):
        raise ValueError(f"{label} contains a forbidden INI character")


def validate_host(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
    validate_component(value, label)
    if len(value) > 253 or any(part == "" for part in value.strip(".").split(".")):
        raise ValueError(f"{label} is not a valid host")


def parse_port(value: str, default: int, label: str) -> int:
    try:
        result = int(value or default)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if not 1 <= result <= 65535:
        raise ValueError(f"{label} must be between 1 and 65535")
    return result


def normalize_folder(value: str) -> str:
    value = value.replace("/", "\\").strip(" \\")
    parts = [part.strip() for part in value.split("\\") if part.strip()]
    for part in parts:
        validate_component(part, "folder")
    return "\\".join(parts)


def make_session(row: dict[str, Any]) -> Session:
    data = canonicalize(row)
    for field in ("name", "user", "key_path", "bastion_user", "bastion_key_path"):
        validate_component(data[field], field)
    if not data["name"]:
        raise ValueError("name is required")
    validate_host(data["host"], "host")
    if data["bastion_host"]:
        validate_host(data["bastion_host"], "bastion_host")
    return Session(
        folder=normalize_folder(data["folder"]), name=data["name"], host=data["host"],
        port=parse_port(data["port"], 22, "port"), user=data["user"] or "opc",
        key_path=data["key_path"], bastion_host=data["bastion_host"],
        bastion_port=parse_port(data["bastion_port"], 22, "bastion_port"),
        bastion_user=(data["bastion_user"] or "opc") if data["bastion_host"] else "",
        bastion_key_path=(data["bastion_key_path"] or data["key_path"]) if data["bastion_host"] else "",
    )


def load_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = payload.get("sessions") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("JSON must be an array or an object with a sessions array")
        return rows
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise ValueError("Excel support requires openpyxl; use JSON/CSV or install openpyxl") from exc
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        headers = [clean(v) for v in next(values, ())]
        return [dict(zip(headers, row)) for row in values if any(clean(v) for v in row)]
    raise ValueError("input must be .json, .csv, or .xlsx")


def load_sessions(path: Path) -> list[Session]:
    errors: list[str] = []
    sessions: list[Session] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(load_rows(path), start=2):
        if not any(clean(v) for v in row.values()):
            continue
        try:
            session = make_session(row)
            identity = (session.folder.casefold(), session.name.casefold())
            if identity in seen:
                raise ValueError("duplicate folder/name in input")
            seen.add(identity); sessions.append(session)
        except ValueError as exc:
            errors.append(f"row {index}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    if not sessions:
        raise ValueError("no sessions found")
    return sessions


def build_line(session: Session) -> str:
    bip = session.bastion_host
    bport = str(session.bastion_port) if bip else ""
    buser = session.bastion_user if bip else ""
    bkey = session.bastion_key_path if bip else ""
    return (
        f"{session.name}=#109#0%{session.host}%{session.port}%{session.user}%%-1%-1%%"
        f"{bip}%{bport}%{buser}%0%0%0%{session.key_path}%{bkey}"
        "%-1%0%0%0%%1080%%0%0%1%%0%%%%0%-1%-1%0"
        "#MobaFont%10%0%0%-1%15%236,236,236%30,30,30%180,180,192%0%-1%0%"
        "%xterm%-1%0%_Std_Colors_0_%80%24%0%1%-1%<none>%%0%0%-1%0%#0# #-1"
    )


def render_export(sessions: Iterable[Session]) -> str:
    grouped: dict[str, list[Session]] = {}
    for session in sessions:
        grouped.setdefault(session.folder, []).append(session)
    lines: list[str] = []
    for index, (folder, items) in enumerate(grouped.items()):
        lines.extend(["[Bookmarks]" if index == 0 else f"[Bookmarks_{index}]", f"SubRep={folder}", "ImgNum=41"])
        lines.extend(build_line(item) for item in items); lines.append("")
    return "\r\n".join(lines)


def encoding_for(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949", "cp1252"):
        try:
            raw.decode(encoding); return encoding
        except UnicodeDecodeError:
            pass
    raise ValueError("INI encoding is not supported")


def section_ranges(lines: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r"\[Bookmarks(?:_\d+)?\]", line.strip())]
    return [(start, starts[i + 1] if i + 1 < len(starts) else len(lines)) for i, start in enumerate(starts)]


def folder_of(section: list[str]) -> str:
    line = next((line for line in section if line.startswith("SubRep=")), "SubRep=")
    return line.split("=", 1)[1]


def next_section_number(lines: list[str]) -> int:
    numbers = [int(m.group(1)) for line in lines if (m := re.fullmatch(r"\[Bookmarks_(\d+)\]", line.strip()))]
    return max(numbers, default=0) + 1


def merge_ini(text: str, sessions: list[Session], conflict: str) -> tuple[str, int, int]:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    grouped: dict[str, list[Session]] = {}
    for session in sessions:
        grouped.setdefault(session.folder, []).append(session)
    added = replaced = 0
    for folder, items in grouped.items():
        ranges = section_ranges(lines)
        found = next(((start, end) for start, end in ranges if folder_of(lines[start:end]).casefold() == folder.casefold()), None)
        if found is None:
            if lines and lines[-1] != "": lines.append("")
            header = "[Bookmarks]" if not ranges and folder == "" else f"[Bookmarks_{next_section_number(lines)}]"
            lines.extend([header, f"SubRep={folder}", "ImgNum=41"] + [build_line(item) for item in items] + [""])
            added += len(items); continue
        start, end = found
        insert_at = end
        while insert_at > start and lines[insert_at - 1] == "": insert_at -= 1
        existing = {line.split("=", 1)[0].casefold(): i for i, line in enumerate(lines[start:end], start=start) if SESSION_MARKER in line}
        for item in items:
            key = item.name.casefold()
            if key in existing:
                if conflict == "error": raise ValueError(f"session already exists: {folder or '<root>'}/{item.name}")
                if conflict == "skip": continue
                lines[existing[key]] = build_line(item); replaced += 1
            else:
                lines.insert(insert_at, build_line(item)); insert_at += 1; added += 1
    return newline.join(lines) + newline, added, replaced


def moba_running() -> bool:
    if os.name != "nt": return False
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MobaXterm.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False)
    return "MobaXterm.exe" in result.stdout


def default_ini() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata: raise ValueError("APPDATA is not set; pass --ini explicitly")
    return Path(appdata) / "MobaXterm" / "MobaXterm.ini"


def print_summary(sessions: list[Session]) -> None:
    print(f"OK: {len(sessions)} sessions, {len({s.folder for s in sessions})} folders, {sum(bool(s.bastion_host) for s in sessions)} via bastion")


def write_new(path: Path, text: str, overwrite: bool) -> None:
    if path.exists() and not overwrite: raise ValueError(f"output already exists: {path} (use --overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(text.encode("cp949"))


def template(path: Path, fmt: str, overwrite: bool) -> None:
    headers = list(ALIASES)
    sample = ["wizocm\\production", "app-01", "10.0.1.10", 22, "opc", r"C:\keys\wizocm.key", "203.0.113.10", 22, "opc", r"C:\keys\bastion.key"]
    if path.exists() and not overwrite: raise ValueError(f"output already exists: {path} (use --overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        path.write_text(json.dumps({"sessions": [dict(zip(headers, sample))]}, ensure_ascii=False, indent=2), encoding="utf-8")
    elif fmt == "csv":
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle); writer.writerow(headers); writer.writerow(sample)
    else:
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise ValueError("Excel support requires openpyxl") from exc
        workbook = Workbook(); sheet = workbook.active; sheet.title = "sessions"
        sheet.append(headers); sheet.append(sample); sheet.freeze_panes = "A2"; sheet.auto_filter.ref = "A1:J2"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(36, max(len(clean(cell.value)) for cell in column) + 2)
        workbook.save(path)
    print(f"created template: {path}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__); sub = root.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate an input inventory"); validate.add_argument("input", type=Path)
    generate = sub.add_parser("generate", help="create an importable .mxtsessions file")
    generate.add_argument("input", type=Path); generate.add_argument("--output", type=Path, required=True); generate.add_argument("--overwrite", action="store_true")
    apply_cmd = sub.add_parser("apply", help="backup and merge into MobaXterm.ini")
    apply_cmd.add_argument("input", type=Path); apply_cmd.add_argument("--ini", type=Path); apply_cmd.add_argument("--on-conflict", choices=("error", "replace", "skip"), default="error")
    make_template = sub.add_parser("template", help="create an input template")
    make_template.add_argument("--format", choices=("json", "csv", "xlsx"), default="xlsx"); make_template.add_argument("--output", type=Path, required=True); make_template.add_argument("--overwrite", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "template": template(args.output, args.format, args.overwrite); return 0
        sessions = load_sessions(args.input); print_summary(sessions)
        if args.command == "validate": return 0
        if args.command == "generate":
            write_new(args.output, render_export(sessions), args.overwrite); print(f"created import file: {args.output}"); return 0
        ini = args.ini or default_ini()
        if moba_running(): raise ValueError("MobaXterm.exe is running; close it before apply")
        if not ini.is_file(): raise ValueError(f"INI not found: {ini}")
        raw = ini.read_bytes(); encoding = encoding_for(raw); current = raw.decode(encoding)
        merged, added, replaced = merge_ini(current, sessions, args.on_conflict)
        backup = ini.with_name(f"{ini.name}.bak_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(ini, backup); ini.write_bytes(merged.encode(encoding))
        print(f"backup: {backup}"); print(f"applied: {ini} ({added} added, {replaced} replaced)"); return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
