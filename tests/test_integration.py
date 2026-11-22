from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import core
import integration as moba


class BookmarkMergeTests(unittest.TestCase):
    def row(self, **values):
        return {**core.new_row(core.DEFAULTS), "host": "192.0.2.90", **values}

    def test_add_preserves_every_original_byte_in_mixed_encoding_file(self):
        old = (b"[SharedSettings]\r\nAllowedEditors=*\r\n[Bookmarks]\r\nSubRep=Keep\r\nImgNum=41\r\n"
               + "보존".encode("cp949") + b"=#105#opaque\x80\xff\r\n\r\n[Unrelated]\r\nKeep=\xff\x80\r\n")
        new, count = moba.merge_bookmarks(old, [self.row(folder="Quick Connect")])
        self.assertEqual(count, 1)
        self.assertTrue(new.startswith(old))
        self.assertIn(b"[Bookmarks_1]\r\nSubRep=Quick Connect", new)
        self.assertEqual(moba.merge_bookmarks(new, [self.row()])[1], 0)

    def test_existing_folder_insertion_does_not_change_following_sections(self):
        old = b"[Bookmarks]\nSubRep=Quick Connect\nImgNum=41\nold=#105#opaque\n[Keep]\nA=B\n"
        new, _ = moba.merge_bookmarks(old, [self.row()])
        self.assertEqual(new.split(b"[Keep]", 1)[1], b"\nA=B\n")
        self.assertIn(b"old=#105#opaque\n", new)
        self.assertEqual(new.count(b"[Bookmarks]"), 1)

    def test_duplicate_is_semantic_and_preserves_original_font_tail(self):
        row = core.normalize(self.row())
        raw = core.export_bytes([row]).replace(b"MobaFont%10", b"MobaFont%15")
        self.assertEqual(moba.merge_bookmarks(raw, [row]), (raw, 0))
        with self.assertRaises(ValueError):
            moba.merge_bookmarks(raw, [self.row(user="another")])

    def test_utf8_bom_and_root_folder(self):
        raw = b"\xef\xbb\xbf[Bookmarks]\r\nSubRep=\r\nImgNum=41\r\n"
        new, _ = moba.merge_bookmarks(raw, [self.row(folder="")])
        self.assertTrue(new.startswith(raw))
        self.assertEqual(new.count(b"[Bookmarks]"), 1)

    def test_rdp_and_gateway_saved_without_touching_original(self):
        row = {**core.new_row(core.DEFAULTS, "RDP"), "host": "192.0.2.21", "bastion_host": "198.51.100.1"}
        before = b"[Misc]\r\nKeep=exact\r\n"
        after, count = moba.merge_bookmarks(before, [row])
        self.assertEqual(count, 1)
        self.assertTrue(after.startswith(before))
        self.assertIn(b"=#91#4%192.0.2.21%3389%", after)
        self.assertEqual(moba.merge_bookmarks(after, [row])[1], 0)

    def test_write_backup_and_concurrent_change_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root / "MobaXterm.ini"
            file.write_bytes(b"old")
            with self.assertRaises(ValueError):
                moba.atomic_replace(file, b"stale", b"new", root / "backups")
            self.assertEqual(file.read_bytes(), b"old")
            backup = moba.atomic_replace(file, b"old", b"new", root / "backups")
            self.assertEqual(Path(backup).read_bytes(), b"old")
            self.assertEqual(file.read_bytes(), b"new")


class RegistrationWorkflowTests(unittest.TestCase):
    def row(self):
        return {**core.new_row(core.DEFAULTS), "host": "192.0.2.9"}

    def test_already_visible_session_does_not_restart_or_rewrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ini = root / "Moba.ini"
            raw = core.export_bytes([self.row()])
            ini.write_bytes(raw)
            target = moba.Target("MobaXterm.exe", str(ini), str(ini))
            with patch.object(moba, "matching_pids", return_value=[1]), patch.object(moba, "request_normal_close") as close, patch.object(moba, "restart") as restart:
                result = moba.register(target, [self.row()], root / "app")
                close.assert_not_called()
                restart.assert_not_called()
            self.assertEqual(result["added"], 0)
            self.assertEqual(ini.read_bytes(), raw)

    def test_existing_ini_restart_uses_exact_profile_no_new_config_or_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ini = root / "User.ini"
            before = b"[Misc]\nExisting=preserve\n"
            ini.write_bytes(before)
            target = moba.Target(str(root / "MobaXterm.exe"), str(ini), str(ini))
            state = {"running": True}
            def pids(_): return [123] if state["running"] else []
            def close(_): state["running"] = False
            def restart(_): state["running"] = True
            with patch.object(moba, "matching_pids", side_effect=pids), patch.object(moba, "request_normal_close", side_effect=close) as closer, patch.object(moba, "restart", side_effect=restart) as restarter:
                receipt = moba.register(target, [self.row()], root / "app")
            self.assertEqual(receipt["added"], 1)
            self.assertTrue(ini.read_bytes().startswith(before))
            closer.assert_called_once_with([123])
            restarter.assert_called_once_with(target)
            self.assertFalse((root / "app" / "launches").exists())
            with patch.object(moba.subprocess, "Popen") as popen:
                moba.restart(target)
                self.assertEqual(popen.call_args.args[0], [target.exe, "-i", target.ini])
                self.assertNotIn("-bookmark", popen.call_args.args[0])

    def test_shared_publisher_flushes_first_then_fresh_source_is_merged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ini, source, view, pending = [root / name for name in ["Moba.ini", "source.mxtsessions", "view.mxtsessions", "pending-edit.json"]]
            initial = b"[SharedSettings]\r\nAllowedEditors=*\r\n[Bookmarks]\r\nSubRep=Keep\r\nImgNum=41\r\n"
            source.write_bytes(initial); view.write_bytes(initial); pending.write_text("{}")
            ini.write_bytes(("[SharedSessions0]\r\nFilePath=" + str(view) + "\r\n").encode())
            target = moba.Target("MobaXterm.exe", str(ini), str(source), pending=str(pending), shared=True)
            state = {"running": True}
            flushed = initial + b"UserEdited=#105#preserved\r\n"
            def pids(_): return [123] if state["running"] else []
            def close(_):
                source.write_bytes(flushed)
                pending.unlink()
                state["running"] = False
            def restart(_):
                view.write_bytes(source.read_bytes())
                state["running"] = True
            with patch.object(moba, "matching_pids", side_effect=pids), patch.object(moba, "request_normal_close", side_effect=close), patch.object(moba, "restart", side_effect=restart):
                receipt = moba.register(target, [self.row()], root / "app")
            self.assertTrue(receipt["active_view_verified"])
            self.assertIn(b"UserEdited=#105#preserved", source.read_bytes())
            self.assertEqual(Path(receipt["backup"]).read_bytes(), flushed)

    def test_stale_pending_and_close_timeout_never_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, pending = root / "file.ini", root / "pending-edit.json"
            source.write_bytes(b"[Misc]\nKeep=1\n"); pending.write_text("{}")
            target = moba.Target("MobaXterm.exe", str(source), str(source), pending=str(pending))
            with patch.object(moba, "matching_pids", return_value=[]), self.assertRaisesRegex(ValueError, "pending"):
                moba.register(target, [self.row()], root / "app")
            pending.unlink()
            with patch.object(moba, "matching_pids", return_value=[1]), patch.object(moba, "request_normal_close"), self.assertRaisesRegex(ValueError, "종료 확인창"):
                moba.register(target, [self.row()], root / "app", timeout=0)
            self.assertEqual(source.read_bytes(), b"[Misc]\nKeep=1\n")

    def test_exe_detection_requires_unambiguous_existing_profile(self):
        records = [(1, r"C:\MobaXterm.exe", r"C:\A.ini"), (2, r"C:\MobaXterm.exe", r"C:\B.ini")]
        with patch.object(moba, "running_moba", return_value=records), self.assertRaisesRegex(ValueError, "여러 MobaXterm"):
            moba.find_target()
        with patch.object(moba, "running_moba", return_value=records), patch.object(moba, "describe_target", return_value="selected") as describe:
            self.assertEqual(moba.find_target(preferred_pid=2), "selected")
            describe.assert_called_once_with(records[1][1], records[1][2])


if __name__ == "__main__":
    unittest.main()
