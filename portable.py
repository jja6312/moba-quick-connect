"""Explicit user-requested connection bundles, including referenced key files."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

import core

FORMAT = 'moba-quick-connect-bundle'
KEY_FIELDS = ('key_path', 'bastion_key_path')
KEY_LIMIT = 1024 * 1024
TOTAL_LIMIT = 64 * 1024 * 1024
KEY_NAME = re.compile(r'keys/[0-9a-f]{64}\.key\Z')


@dataclass
class Bundle:
    rows: list
    keys: dict
    names: dict
    identity: str


def _read_key(path):
    expanded = Path(os.path.expandvars(os.path.expanduser(path)))
    with expanded.open('rb') as stream:
        data = stream.read(KEY_LIMIT + 1)
    if not data or len(data) > KEY_LIMIT:
        raise ValueError('키 파일은 비어 있지 않은 1MB 이하 파일이어야 합니다.')
    return data


def export_bundle(target, rows, favorites=(), *, overwrite=False):
    rows = core.validate_batch(rows, check_keys=True)
    keys, names, packed, paths = {}, {}, [], {}
    aliases = {core.key_identity(item['path']): item['name'] for item in favorites}
    for row in rows:
        copy = dict(row)
        for field in KEY_FIELDS:
            if not row[field]:
                continue
            identity = core.key_identity(row[field])
            if identity not in paths:
                data = _read_key(row[field])
                name = 'keys/' + hashlib.sha256(data).hexdigest() + '.key'
                keys[name] = data
                if sum(map(len, keys.values())) > TOTAL_LIMIT:
                    raise ValueError('키 파일 합계가 64MB를 넘습니다.')
                names.setdefault(name, aliases.get(identity, Path(row[field]).name))
                paths[identity] = name
            copy[field] = paths[identity]
        packed.append(copy)
    if sum(map(len, keys.values())) > TOTAL_LIMIT:
        raise ValueError('키 파일 합계가 64MB를 넘습니다.')
    manifest = {'format': FORMAT, 'schema': 1, 'connections': packed,
                'keys': [{'file': name, 'sha256': hashlib.sha256(data).hexdigest(), 'name': names[name]}
                         for name, data in sorted(keys.items())]}
    raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    target = Path(target)
    if target.exists() and not overwrite:
        raise FileExistsError('같은 이름의 내보내기 파일이 있습니다.')
    fd, temporary = tempfile.mkstemp(prefix='.moba-export-', dir=target.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', raw)
            for name, data in sorted(keys.items()):
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(info, data)
        if not overwrite and target.exists():
            raise FileExistsError('같은 이름의 내보내기 파일이 생겼습니다.')
        if overwrite:
            os.replace(temporary, target)
        elif os.name == 'nt':
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
            os.unlink(temporary)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {'connections': len(rows), 'keys': len(keys)}


def read_bundle(path):
    if Path(path).stat().st_size > TOTAL_LIMIT * 2:
        raise ValueError('가져오기 파일이 너무 큽니다.')
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 4001 or len({i.filename for i in entries}) != len(entries):
                raise ValueError('중복되거나 너무 많은 파일이 들어 있습니다.')
            if sum(i.file_size for i in entries) > TOTAL_LIMIT + 8 * 1024 * 1024:
                raise ValueError('가져오기 파일이 너무 큽니다.')
            for entry in entries:
                if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError('암호화된 ZIP이나 링크 파일은 가져올 수 없습니다.')
                if entry.filename != 'manifest.json' and not KEY_NAME.fullmatch(entry.filename):
                    raise ValueError('허용되지 않은 파일 경로가 들어 있습니다.')
                limit = 8 * 1024 * 1024 if entry.filename == 'manifest.json' else KEY_LIMIT
                if entry.file_size > limit:
                    raise ValueError('개별 파일 크기 제한을 넘었습니다.')
            raw = archive.read('manifest.json')
            manifest = json.loads(raw.decode('utf-8'))
            if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or type(manifest.get('schema')) is not int or manifest['schema'] != 1:
                raise ValueError('지원하지 않는 연결 파일 형식입니다.')
            source = manifest['connections']
            metadata = manifest['keys']
            if not isinstance(source, list) or not 1 <= len(source) <= 2000 or not all(isinstance(r, dict) for r in source):
                raise ValueError('연결 목록은 1~2,000개여야 합니다.')
            if not isinstance(metadata, list) or len(metadata) > 4000:
                raise ValueError('키 목록 형식이 올바르지 않습니다.')
            rows = core.validate_batch(source)
            if len(rows) != len(source):
                raise ValueError('IP가 없는 연결이 들어 있습니다.')
            keys, names = {}, {}
            for item in metadata:
                name = item['file']
                if not isinstance(name, str) or not KEY_NAME.fullmatch(name) or name in keys:
                    raise ValueError('키 파일 목록이 올바르지 않습니다.')
                data = archive.read(name)
                digest = hashlib.sha256(data).hexdigest()
                if not data or digest != item['sha256'] or name != 'keys/' + digest + '.key':
                    raise ValueError('키 파일 검증에 실패했습니다.')
                keys[name] = data
                names[name] = core.Store.favorite_key_name(item['name'])
            used = {row[field] for row in rows for field in KEY_FIELDS if row[field]}
            if used != set(keys) or {i.filename for i in entries} != {'manifest.json', *keys}:
                raise ValueError('연결의 키 참조와 파일 목록이 일치하지 않습니다.')
            return Bundle(rows, keys, names, hashlib.sha256(raw).hexdigest()[:24])
    except (zipfile.BadZipFile, KeyError, TypeError, UnicodeError, json.JSONDecodeError, RuntimeError, NotImplementedError, EOFError) as exc:
        raise ValueError('연결 파일이 손상됐거나 지원하지 않는 형식입니다.') from exc


def install_bundle(bundle, store):
    imports = store.root / 'imports'
    imports.mkdir(exist_ok=True)
    target = imports / ('bundle-' + bundle.identity)
    if target.resolve().parent != imports.resolve() or target.is_symlink():
        raise ValueError('가져오기 저장 경로를 확인할 수 없습니다.')
    created = False
    if target.exists():
        if not target.is_dir():
            raise ValueError('가져오기 경로에 다른 파일이 있습니다.')
        for name, data in bundle.keys.items():
            if (target / Path(name).name).is_symlink() or _read_key(target / Path(name).name) != data:
                raise ValueError('이전에 가져온 키 파일이 변경됐습니다. 기존 파일을 보존했습니다.')
    else:
        with tempfile.TemporaryDirectory(prefix='.incoming-', dir=imports) as temporary:
            for name, data in bundle.keys.items():
                path = Path(temporary) / Path(name).name
                with path.open('xb') as output:
                    output.write(data)
                os.chmod(path, 0o600)
            os.rename(temporary, target)
            created = True
    rows = [{**row, **{field: str(target / Path(row[field]).name) if row[field] else '' for field in KEY_FIELDS}}
            for row in bundle.rows]
    favorites = list(store.state['favorite_keys'])
    for name in bundle.keys:
        path = str(target / Path(name).name)
        if not store.favorite_key(path):
            favorites.append({'name': bundle.names[name], 'path': path})
    try:
        core.validate_batch(rows, check_keys=True)
        store._save_favorites(favorites)
    except Exception:
        if created and target.resolve().parent == imports.resolve():
            shutil.rmtree(target)
        raise
    return rows
