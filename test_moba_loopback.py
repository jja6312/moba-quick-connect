"""Explicit opt-in integration test against local, non-authenticating TCP probes.

No remote customer systems, credentials or original INI files are used. MobaXterm
receives -exitwhendone; this tool never kills/closes any existing application.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time

import core


def probe(exe, root, kind, bastion):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(12)
    port = listener.getsockname()[1]
    result = {"protocol": kind, "bastion": bastion, "received": False, "handshake": None}
    def receive():
        try:
            peer, _ = listener.accept()
            result["received"] = True
            with peer:
                peer.settimeout(3)
                if bastion or kind == "SSH":
                    peer.sendall(b"SSH-2.0-QuickConnect_Probe\r\n")
                data = peer.recv(1024)
                result["handshake"] = "SSH" if data.startswith(b"SSH-") else "RDP" if data.startswith(b"\x03\x00") else "other"
        except (OSError, TimeoutError):
            pass
        finally:
            listener.close()
    worker = threading.Thread(target=receive, daemon=True)
    worker.start()
    row = {**core.new_row(core.DEFAULTS, kind), "host": "127.0.0.1", "port": str(port), "name": "QC-Local-Probe"}
    if bastion:
        row.update(host="192.0.2.20", port="3389" if kind == "RDP" else "22",
                   bastion_host="127.0.0.1", bastion_port=str(port), bastion_user="probe")
    ini = root / (kind + ("-bastion" if bastion else "-direct") + ".ini")
    ini.write_bytes(b"[Misc]\r\nSingleInstance=0\r\nAllowMultiInstances=1\r\n\r\n" + core.export_bytes([row], root_session=row))
    process = subprocess.Popen(core.launch_arguments(exe, ini, row, test_exit=True) + ["-hideterm"], shell=False,
                               cwd=str(Path(exe).parent), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    worker.join(16)
    try:
        result["exit_code"] = process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        result["exit_code"] = None
        result["note"] = "Owned test process still running; not closed by the test."
    result["pass"] = result["received"] and result["handshake"] == ("SSH" if bastion else kind)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print("Plan: four loopback protocol probes; pass --execute to run.")
        return
    with tempfile.TemporaryDirectory(prefix="moba-quick-loopback-") as temporary:
        results = []
        for kind, bastion in (("SSH", False), ("RDP", False), ("SSH", True), ("RDP", True)):
            result = probe(args.exe, Path(temporary), kind, bastion)
            results.append(result)
            print(json.dumps(result), flush=True)
    args.output.write_text(json.dumps({"scope": "loopback handshake only; no authentication", "tests": results}, indent=2), encoding="utf-8")
    if not all(r["pass"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
