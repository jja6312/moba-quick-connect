import copy
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetSelectionRange

import app as ui
import core


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui.configure_application(cls.app)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = core.Store(self.tmp.name)
        self.store.state["moba_exe"] = r"C:\Programs\MobaXterm.exe"
        self.window = ui.MainWindow(self.store, dry_run=True, no_tray=True)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.quitting = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_ip_only_bulk_registers_with_profile_defaults(self):
        self.window.grid.setCurrentCell(0, 1)
        self.window.grid.paste_text("192.0.2.8")
        self.window.register_bulk()
        self.assertEqual(len(self.store.state["connections"]), 1)
        self.assertEqual(self.store.state["connections"][0]["user"], "opc")
        self.assertFalse((Path(self.tmp.name) / "launches").exists())

    def test_protocol_defaults_and_bastion_fields(self):
        self.window.select_page(1)
        self.window.settings_protocol.setCurrentText("RDP")
        form = self.window.settings_form
        self.assertEqual(form.fields["port"].text(), "3389")
        self.assertEqual(form.fields["user"].text(), "Administrator")
        self.assertFalse(form.key_widget.isVisible())
        form.jump.setChecked(True)
        self.app.processEvents()
        self.assertTrue(form.jump_panel.isVisible())
        form.fields["bastion_host"].setText("198.51.100.2")
        self.window.grid.set_rows([{**form.get_row(), "host": "192.0.2.50"}])
        self.window.register_bulk()
        self.assertEqual(self.store.state["connections"][0]["bastion_host"], "198.51.100.2")

    def test_multi_ip_paste_inherits_profile_and_grows_table(self):
        grid = self.window.grid
        self.store.profile["SSH"]["user"] = "operator"
        grid.set_rows([core.new_row(self.store.profile)])
        grid.setCurrentCell(0, 1)
        grid.paste_text("192.0.2.1\n192.0.2.2\n192.0.2.3")
        self.assertEqual(grid.logical_count(), 3)
        self.assertTrue(all(r["user"] == "operator" for r in grid.rows()))
        self.window.register_bulk()
        self.assertEqual(len(self.store.state["connections"]), 3)

    def test_paste_protocol_updates_only_unpasted_defaults(self):
        grid = self.window.grid
        grid.setCurrentCell(0, 1)
        grid.setCurrentCell(0, 0)
        grid.paste_text("Windows Server\t192.0.2.40\tRDP\tDOMAIN\\user\t3390")
        row = grid.rows()[0]
        self.assertEqual((row["protocol"], row["user"], row["port"]), ("RDP", "DOMAIN\\user", "3390"))
        grid.setCurrentCell(2, 1)
        grid.paste_text("192.0.2.41\tRDP")
        row = grid.rows()[1]
        self.assertEqual((row["user"], row["port"]), ("Administrator", "3389"))

    def test_fill_down_duplicate_and_undo(self):
        grid = self.window.grid
        grid.set_rows([{**core.new_row(self.store.profile), "host": "192.0.2.1", "user": "operator"},
                       core.new_row(self.store.profile), core.new_row(self.store.profile)])
        grid.clearSelection()
        grid.setRangeSelected(QTableWidgetSelectionRange(0, 3, 4, 3), True)
        grid.fill_down()
        self.assertEqual([r["user"] for r in grid.rows()], ["operator"] * 3)
        grid.undo()
        self.assertEqual(grid.rows()[1]["user"], "opc")
        grid.clearSelection()
        grid.setCurrentCell(0, 1)
        grid.duplicate_rows()
        self.assertEqual(grid.logical_count(), 4)
        self.assertEqual(grid.rows()[1]["host"], "192.0.2.1")

    def test_default_save_switch_restart_and_bulk_draft_preservation(self):
        self.window.select_page(1)
        self.window.settings_form.fields["user"].setText("operator")
        self.window.settings_protocol.setCurrentText("RDP")
        self.window.settings_form.fields["port"].setText("3390")
        self.window.exe_field.clear()
        self.window.save_settings()
        restored = core.Store(self.tmp.name)
        self.assertEqual(restored.profile["SSH"]["user"], "operator")
        self.assertEqual(restored.profile["RDP"]["port"], "3390")
        self.window.grid.setCurrentCell(0, 1)
        self.window.grid.paste_text("192.0.2.70")
        original = self.window.grid.rows()[0]
        self.store.state["profiles"]["다른 기본값"] = copy.deepcopy(core.DEFAULTS)
        self.window.change_profile("다른 기본값")
        self.assertEqual(self.window.grid.rows()[0], original)

    def test_invalid_bulk_is_atomic_and_visible_error(self):
        grid = self.window.grid
        grid.setCurrentCell(0, 1)
        grid.paste_text("192.0.2.1\n999.9.9.9")
        self.window.register_bulk()
        self.assertEqual(self.store.state["connections"], [])
        self.assertIn("2행", self.window.status.text())

    def test_rdp_bulk_default_applies_to_empty_and_new_rows_only(self):
        grid = self.window.grid
        grid.setCurrentCell(0, 1)
        grid.paste_text("192.0.2.90")
        self.window.bulk_protocol.setCurrentText("RDP")
        self.assertEqual(grid.rows()[0]["protocol"], "SSH")
        self.assertEqual((grid.rows()[1]["protocol"], grid.rows()[1]["port"]), ("RDP", "3389"))
        grid.append_rows()
        self.assertEqual(grid.rows()[-1]["user"], "Administrator")

    def test_ctrl_enter_commits_active_cell_before_registering(self):
        grid = self.window.grid
        self.window.select_page(0)
        self.app.processEvents()
        grid.setCurrentCell(0, 1)
        grid.editItem(grid.item(0, 1))
        self.app.processEvents()
        editor = self.app.focusWidget()
        QTest.keyClicks(editor, "192.0.2.91")
        self.window.register_bulk()
        self.assertTrue(self.store.state["connections"], self.window.status.text())
        self.assertEqual(self.store.state["connections"][0]["host"], "192.0.2.91")

    def test_compact_table_and_short_labels(self):
        self.assertEqual(self.window.grid.horizontalHeaderItem(0).text(), "연결 이름")
        self.assertEqual(self.window.grid.horizontalHeaderItem(1).text(), "접속 IP")
        self.assertLessEqual(self.window.width(), 860)

    def test_key_picker_starts_with_all_files_for_target_and_bastion(self):
        for field in ("key_path", "bastion_key_path"):
            with patch.object(ui.QFileDialog, "getOpenFileName", return_value=("", "")) as dialog:
                self.window.settings_form.pick_key(field)
                self.assertEqual(dialog.call_args.args[3], "모든 파일 (*)")

    def test_enter_commits_cell_and_moves_down_same_column(self):
        self.window.select_page(0)
        self.app.processEvents()
        grid = self.window.grid
        grid.setCurrentCell(0, 1)
        grid.editItem(grid.item(0, 1))
        self.app.processEvents()
        editor = self.app.focusWidget()
        QTest.keyClicks(editor, "192.0.2.45")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(grid.rows()[0]["host"], "192.0.2.45")
        self.assertEqual((grid.currentRow(), grid.currentColumn()), (2, 1))
        QTest.keyClick(grid, Qt.Key.Key_1)
        self.app.processEvents()
        editor = self.app.focusWidget()
        QTest.keyClicks(editor, "92.0.2.46")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(grid.rows()[1]["host"], "192.0.2.46")
        self.assertEqual((grid.currentRow(), grid.currentColumn()), (4, 1))

    def test_enter_on_last_row_creates_next_input_row(self):
        grid = self.window.grid
        grid.setCurrentCell(grid.rowCount() - 2, 1)
        count = grid.logical_count()
        QTest.keyClick(grid, Qt.Key.Key_Return)
        self.assertEqual(grid.logical_count(), count + 1)
        self.assertEqual((grid.currentRow(), grid.currentColumn()), (count * 2, 1))

    def mouse_drag_handle(self, seed, final_row, *, ctrl=False, layer=0):
        grid = self.window.grid
        if layer:
            grid.set_bastion(True)
        grid.clearSelection()
        grid.setCurrentCell(seed[0] * 2 + layer, seed[1])
        grid.clearSelection()
        grid.setRangeSelected(QTableWidgetSelectionRange(seed[0] * 2 + layer, seed[1], seed[2] * 2 + layer, seed[3]), True)
        self.app.processEvents()
        start = grid.fill_handle().center()
        grid.scrollToItem(grid.item(final_row * 2 + layer, seed[3]))
        self.app.processEvents()
        # Keep the start handle on screen as well as the destination.
        grid.scrollToItem(grid.item(seed[2] * 2 + layer, seed[3]))
        self.app.processEvents()
        start = grid.fill_handle().center()
        end = grid.visualRect(grid.model().index(final_row * 2 + layer, seed[3])).center()
        modifiers = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
        for event_type, position, clicked, held in (
                (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
                (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
                (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)):
            event = QMouseEvent(event_type, QPointF(position), QPointF(grid.viewport().mapToGlobal(position)), clicked, held, modifiers)
            self.app.sendEvent(grid.viewport(), event)
            self.app.processEvents()

    def test_handle_mouse_drag_copies_multi_cell_block_then_undoes_as_one_change(self):
        self.window.select_page(0)
        self.app.processEvents()
        grid = self.window.grid
        rows = grid.rows()
        rows[0].update(host="192.0.2.1", name="A")
        rows[1].update(host="192.0.2.2", name="B")
        grid.set_rows(rows)
        self.mouse_drag_handle((0, 0, 1, 2), 5)
        self.assertEqual([r["host"] for r in grid.rows()[:6]], ["192.0.2.1", "192.0.2.2"] * 3)
        self.assertEqual([r["name"] for r in grid.rows()[:6]], ["A", "B"] * 3)
        grid.undo()
        self.assertEqual(grid.rows(), rows)

    def test_handle_ctrl_mouse_drag_increments_ip_and_number(self):
        self.window.select_page(0)
        self.app.processEvents()
        grid = self.window.grid
        rows = grid.rows()
        rows[0].update(host="192.0.2.254", name="node-009")
        grid.set_rows(rows)
        self.mouse_drag_handle((0, 0, 0, 2), 3, ctrl=True)
        self.assertEqual([r["host"] for r in grid.rows()[:4]], ["192.0.2.254", "192.0.2.255", "192.0.3.0", "192.0.3.1"])
        self.assertEqual([r["name"] for r in grid.rows()[:4]], ["node-009", "node-010", "node-011", "node-012"])

    def test_registered_list_removed_but_saved_history_is_preserved(self):
        self.store.add([{**core.new_row(self.store.profile), "host": "192.0.2.6"}])
        saved = copy.deepcopy(self.store.state["connections"])
        self.window.change_profile(self.store.state["active_profile"])
        self.assertFalse(hasattr(self.window, "recent"))
        self.assertEqual(core.Store(self.tmp.name).state["connections"], saved)

    def test_single_menu_removed_and_table_is_default(self):
        self.assertFalse(hasattr(self.window, "single_form"))
        self.assertEqual(self.window.pages.count(), 2)
        self.assertEqual(self.window.pages.currentIndex(), 0)
        self.assertLessEqual(self.window.width(), 860)
        self.assertLessEqual(self.window.height(), 560)

    def test_bastion_is_colored_lower_row_and_roundtrips_to_same_connection(self):
        self.window.select_page(0)
        grid = self.window.grid
        self.assertEqual(grid.columnCount(), 7)
        self.assertEqual(grid.item(1, 0).text(), "Bastion")
        self.assertNotEqual(grid.item(0, 0).background(), grid.item(1, 0).background())
        grid.setCurrentCell(0, 1)
        grid.paste_text("192.0.2.51\n192.0.2.52")
        grid.item(1, 1).setText("198.51.100.5")
        grid.item(1, 3).setText("jumpuser")
        self.window.register_bulk()
        records = self.store.state["connections"]
        self.assertEqual(records[0]["bastion_host"], "198.51.100.5")
        self.assertEqual(records[0]["bastion_user"], "jumpuser")
        self.assertEqual(records[1]["bastion_host"], "")

    def test_jump_paste_and_enter_stay_in_jump_rows(self):
        self.window.select_page(0)
        grid = self.window.grid
        grid.set_bastion(True)
        grid.setCurrentCell(1, 1)
        grid.paste_text("198.51.100.1\n198.51.100.2")
        QTest.keyClick(grid, Qt.Key.Key_Return)
        self.assertEqual(grid.currentRow(), 3)
        self.assertEqual([row["bastion_host"] for row in grid.rows()[:2]], ["198.51.100.1", "198.51.100.2"])
        self.assertTrue(all(not row["host"] for row in grid.rows()))

    def test_ctrl_drag_bastion_increments_without_touching_target_ip(self):
        self.window.select_page(0)
        grid = self.window.grid
        rows = grid.rows()
        rows[0].update(host="192.0.2.1", bastion_host="198.51.100.1")
        grid.set_rows(rows)
        self.mouse_drag_handle((0, 1, 0, 1), 3, ctrl=True, layer=1)
        self.assertEqual([row["bastion_host"] for row in grid.rows()[:4]], ["198.51.100.1", "198.51.100.2", "198.51.100.3", "198.51.100.4"])
        self.assertEqual([row["host"] for row in grid.rows()[:4]], ["192.0.2.1", "", "", ""])

    def test_pair_duplicate_delete_and_hide_preserve_bastion_data(self):
        grid = self.window.grid
        grid.item(0, 1).setText("192.0.2.61")
        grid.item(1, 1).setText("198.51.100.6")
        grid.set_bastion(True)
        grid.setCurrentCell(1, 1)
        grid.duplicate_rows()
        self.assertEqual(grid.rows()[1]["bastion_host"], "198.51.100.6")
        grid.delete_rows()
        self.assertEqual(grid.logical_count(), 8)
        self.window.bastion_rows.setChecked(False)
        self.assertTrue(grid.isRowHidden(1))
        self.assertEqual(grid.rows()[0]["bastion_host"], "198.51.100.6")
        self.window.bastion_rows.setChecked(True)
        self.assertFalse(grid.isRowHidden(1))

    def test_async_registration_updates_ui_on_completion(self):
        self.window.dry_run = False
        self.window.grid.item(0, 1).setText("192.0.2.50")
        target = ui.integration.Target("MobaXterm.exe", "profile.ini", "sessions.mxtsessions")
        with patch.object(ui.integration, "find_target", return_value=target), patch.object(ui.integration, "register", return_value={"target": target.to_dict()}):
            self.window.register_bulk()
            for _ in range(100):
                time.sleep(0.01)
                self.app.processEvents()
                if self.window.registration_thread is None:
                    break
            self.assertIsNone(self.window.registration_thread)
        self.assertEqual(self.store.state["connections"][0]["host"], "192.0.2.50")
        self.assertIn("기존 MobaXterm", self.window.status.text())
        self.assertTrue(self.window.bulk_action.isEnabled())

    def test_async_registration_failure_preserves_history(self):
        self.window.dry_run = False
        self.window.grid.item(0, 1).setText("192.0.2.51")
        target = ui.integration.Target("MobaXterm.exe", "profile.ini", "sessions.mxtsessions")
        with patch.object(ui.integration, "find_target", return_value=target), patch.object(ui.integration, "register", side_effect=ValueError("종료 취소")):
            self.window.register_bulk()
            for _ in range(100):
                time.sleep(0.01)
                self.app.processEvents()
                if self.window.registration_thread is None:
                    break
            self.assertIsNone(self.window.registration_thread)
        self.assertEqual(self.store.state["connections"], [])
        self.assertEqual(self.window.status.text(), "종료 취소")
        self.assertTrue(self.window.bulk_action.isEnabled())


if __name__ == "__main__":
    unittest.main()
