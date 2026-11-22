import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import core
from windows import accepts_hotkey


class ConnectionTests(unittest.TestCase):
    def row(self, kind="SSH", **fields):
        return {**core.new_row(core.DEFAULTS, kind), "host": "192.0.2.20", **fields}

    def test_ip_only_and_rdp_defaults(self):
        ssh = core.normalize(self.row())
        rdp = core.normalize(self.row("RDP"))
        self.assertEqual((ssh["name"], ssh["user"], ssh["port"]), ("192.0.2.20", "opc", "22"))
        self.assertEqual((rdp["name"], rdp["user"], rdp["port"]), ("192.0.2.20 (RDP)", "Administrator", "3389"))

    def test_invalid_hosts_ports_and_ini_injection(self):
        for field, value in (("host", "10.0.0.999"), ("host", "host; calc"), ("host", "a%22"),
                             ("port", "0"), ("port", "65536"), ("name", "x\n[Misc]"),
                             ("user", "opc%bad"), ("folder", "x\\..\\y"), ("name", "[Bookmarks]")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                core.normalize(self.row(**{field: value}))

    def test_ipv6_and_domain_login(self):
        row = core.normalize(self.row("RDP", host="[2001:db8::5]", user="EXAMPLE\\operator"))
        self.assertEqual(row["host"], "2001:db8::5")
        self.assertIn("EXAMPLE\\operator", core.session_line(row))

    def test_ssh_gateway_separate_keys(self):
        row = self.row(key_path=r"C:\Keys\target.pem", bastion_host="198.51.100.10",
                       bastion_user="jump", bastion_port="2222", bastion_key_path=r"C:\Keys\jump.ppk")
        fields = core.session_line(row).split("#")[2].split("%")
        self.assertEqual(fields[8:11], ["198.51.100.10", "2222", "jump"])
        self.assertEqual(fields[14:16], [r"C:\Keys\target.pem", r"C:\Keys\jump.ppk"])

    def test_rdp_gateway_layout_matches_exported_25_2(self):
        row = self.row("RDP", bastion_host="198.51.100.5", bastion_port="2200", bastion_user="jump",
                       bastion_key_path=r"C:\Keys\jump.pem")
        record = core.session_line(row)
        self.assertIn("=#91#4%192.0.2.20%3389%Administrator%", record)
        fields = record.split("#")[2].split("%")
        self.assertEqual(len(fields), 32)
        self.assertEqual(fields[13:16], ["198.51.100.5", "2200", "jump"])
        self.assertEqual(fields[18], r"C:\Keys\jump.pem")

    def test_batch_errors_report_row_and_do_not_drop_valid_input(self):
        with self.assertRaisesRegex(ValueError, "2행"):
            core.validate_batch([self.row(), self.row(host="bad value")])
        with self.assertRaisesRegex(ValueError, "같은 연결 이름"):
            core.validate_batch([self.row(), self.row()])
        self.assertEqual(len(core.validate_batch([self.row(), self.row(host="")])), 1)

    def test_missing_key_is_detected_without_reading_contents(self):
        with self.assertRaisesRegex(ValueError, "파일을 찾을 수 없습니다"):
            core.normalize(self.row(key_path=r"C:\NoSuchQCKey\missing.pem"), check_keys=True)

    def test_clipboard_is_tsv_not_executable_text(self):
        matrix = core.parse_clipboard('192.0.2.2\tSSH\t"서버 이름"\r\n192.0.2.3\tRDP\t')
        self.assertEqual(matrix, [["192.0.2.2", "SSH", "서버 이름"], ["192.0.2.3", "RDP", ""]])
        with self.assertRaises(ValueError):
            core.parse_clipboard("x\n" * 2001)

    def test_store_restart_duplicate_conflict_and_original_config_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unrelated = root / "UserMobaXterm.ini"
            unrelated.write_bytes(b"[Bookmarks]\noriginal=opaque\n")
            store = core.Store(root / "quick")
            store.add([self.row(), self.row("RDP", host="192.0.2.30")])
            store.add([self.row()])
            before = store.path.read_bytes()
            with self.assertRaises(ValueError):
                store.add([self.row(user="other")])
            self.assertEqual(before, store.path.read_bytes())
            resumed = core.Store(root / "quick")
            self.assertEqual(len(resumed.state["connections"]), 2)
            ini = resumed.prepare_launch(resumed.state["connections"][1])
            raw = ini.read_bytes()
            self.assertIn(b"[Bookmarks]\r\nSubRep=\r\n", raw)
            self.assertIn(b"AllowMultiInstances=1", raw)
            self.assertIn(b"=#91#", raw)
            self.assertIn(b"=#109#", raw)
            self.assertEqual(unrelated.read_bytes(), b"[Bookmarks]\noriginal=opaque\n")
            self.assertTrue((root / "quick" / "settings.previous.json").is_file())

    def test_corrupt_defaults_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                core.Store(tmp)
            self.assertEqual(path.read_text(), "broken")

    def test_launch_is_argument_array_and_keeps_names_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "MobaXterm Test.exe"
            exe.touch()
            ini = Path(tmp) / "launch.ini"
            args = core.launch_arguments(exe, ini, self.row(name="sample & literal"))
            self.assertEqual(args[-2:], ["-bookmark", "sample & literal"])
            self.assertEqual(args[1:3], ["-i", str(ini)])

    def test_hotkey_scope_and_modifiers(self):
        own = r"C:\Apps\MobaQuickConnect.exe"
        moba = r"C:\Apps\MobaXterm_Personal_25.2.exe"
        self.assertTrue(accepts_hotkey(32, True, True, False, moba, own, moba))
        self.assertTrue(accepts_hotkey(32, True, True, False, own, own, moba))
        for vk, ctrl, shift, alt, foreground in ((32, True, True, False, r"C:\Apps\Notepad.exe"),
                (32, True, False, False, moba), (32, True, True, True, moba), (13, True, True, False, moba)):
            self.assertFalse(accepts_hotkey(vk, ctrl, shift, alt, foreground, own, moba))


if __name__ == "__main__":
    unittest.main()
