import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

import app as ui
import core
from key_picker import KeyPicker, ranked_keys


class KeyboardThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui.configure_application(cls.app)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'data')
        self.store.state['moba_exe'] = r'C:\Programs\MobaXterm.exe'
        self.key = self.root / 'prod.key'
        self.key.write_bytes(b'SYNTHETIC KEY')
        self.window = ui.MainWindow(self.store, dry_run=True, no_tray=True)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.quitting = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_alt_enter_toggles_current_bastion_and_focuses_its_ip(self):
        grid = self.window.grid
        grid.setCurrentCell(2, 0)
        grid.setFocus()
        QTest.keyClick(grid, Qt.Key.Key_Return, Qt.KeyboardModifier.AltModifier)
        self.app.processEvents()
        self.assertFalse(grid.isRowHidden(3))
        self.assertTrue(grid.isRowHidden(1))
        self.assertEqual((grid.currentRow(), grid.currentColumn()), (3, 1))
        grid.item(3, 1).setText('198.51.100.1')
        QTest.keyClick(grid, Qt.Key.Key_Return, Qt.KeyboardModifier.AltModifier)
        self.app.processEvents()
        self.assertTrue(grid.isRowHidden(3))
        self.assertEqual(grid.currentRow(), 2)
        self.assertEqual(grid.rows()[1]['bastion_host'], '198.51.100.1')

    def test_left_enters_row_selection_shift_extends_and_right_returns_to_name(self):
        grid = self.window.grid
        grid.setCurrentCell(0, 1)
        grid.setFocus()
        QTest.keyClick(grid, Qt.Key.Key_Left)
        self.assertEqual(grid.currentColumn(), 0)
        QTest.keyClick(grid, Qt.Key.Key_Left)
        self.assertTrue(grid.row_mode)
        self.assertEqual(grid.whole_rows, {0})
        QTest.keyClick(grid, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClick(grid, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(grid.whole_rows, {0, 1, 2})
        QTest.keyClick(grid, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(grid.whole_rows, {0, 1})
        QTest.keyClick(grid, Qt.Key.Key_Right)
        self.assertFalse(grid.row_mode)
        self.assertEqual((grid.currentRow(), grid.currentColumn()), (2, 0))

    def test_keyboard_multirow_copy_retains_hidden_bastion_and_actual_key_paths(self):
        grid = self.window.grid
        rows = grid.rows()
        rows[0].update(name='node-1', host='192.0.2.1', key_path=str(self.key), bastion_host='198.51.100.1')
        rows[1].update(name='node-2', host='192.0.2.2', bastion_host='198.51.100.2')
        self.store.add_favorite_key(self.key, 'Production')
        grid.set_rows(rows)
        grid.setCurrentCell(0, 0)
        grid.setFocus()
        QTest.keyClick(grid, Qt.Key.Key_Left)
        QTest.keyClick(grid, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClick(grid, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        text = QApplication.clipboard().text()
        self.assertIn(str(self.key), text)
        self.assertNotIn('Production', text)
        self.assertIn('198.51.100.1', text)
        self.assertIn('198.51.100.2', text)
        self.assertEqual(len(core.parse_clipboard(text)), 2)

    def test_favorites_show_alias_but_store_paths_and_unknown_keys_keep_full_path(self):
        self.store.add_favorite_key(self.key, 'Production')
        self.window.key_library.changed.emit()
        picker = self.window.settings_form.fields['key_path']
        picker.setText(str(self.key))
        self.assertEqual(picker.combo.currentText(), 'Production')
        self.assertEqual(picker.text(), str(self.key))
        unknown = str(self.root / 'unregistered-key')
        picker.setText(unknown)
        self.assertEqual(picker.combo.currentText(), unknown)
        grid = self.window.grid
        grid.item(0, 5).setText(str(self.key))
        self.assertEqual(grid.item(0, 5).text(), str(self.key))
        self.assertEqual(grid.item(0, 5).data(Qt.ItemDataRole.AccessibleTextRole), 'Production')
        self.store.rename_favorite_key(self.key, 'Renamed')
        self.window.key_library.changed.emit()
        self.assertEqual(grid.item(0, 5).data(Qt.ItemDataRole.AccessibleTextRole), 'Renamed')

    def test_search_highlights_best_alias_and_enter_alone_selects_without_advancing(self):
        other = self.root / 'other.key'
        other.write_bytes(b'OTHER SYNTHETIC KEY')
        self.store.add_favorite_key(other, 'Production backup')
        self.store.add_favorite_key(self.key, 'Production')
        self.window.key_library.changed.emit()
        grid = self.window.grid
        grid.setCurrentCell(0, 5)
        grid.editItem(grid.item(0, 5))
        self.app.processEvents()
        picker = next(p for p in grid.viewport().findChildren(KeyPicker) if p.isVisible() and not p.closed)
        QTest.keyClicks(picker.combo, 'production')
        self.app.processEvents()
        popup = picker.combo.completer().popup()
        self.assertTrue(popup.isVisible())
        self.assertEqual(popup.currentIndex().data(Qt.ItemDataRole.UserRole), str(self.key))
        QTest.keyClick(picker.combo, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(picker.text(), str(self.key))
        self.assertEqual(picker.combo.currentText(), 'Production')
        self.assertEqual(grid.currentRow(), 0)
        QTest.keyClick(picker.combo, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(grid.rows()[0]['key_path'], str(self.key))
        self.assertEqual(grid.currentRow(), 2)

    def test_rank_exact_prefix_substring_and_typo_choices_deterministically(self):
        items = [{'name':'Production backup','path':r'C:\keys\backup'},
                 {'name':'Production','path':r'C:\keys\prod'},
                 {'name':'Development','path':r'C:\keys\dev'}]
        for query in ('production', 'prod', 'duct', 'prodction'):
            self.assertEqual(ranked_keys(items, query)[0]['name'], 'Production')
        self.assertEqual(ranked_keys(items, r'keys\dev')[0]['name'], 'Development')
        self.assertEqual(ranked_keys(items, 'unrelated full path'), [])

    def test_themes_persist_and_custom_colors_apply_without_changing_connections(self):
        before = list(self.store.state['connections'])
        self.window.theme_picker.setCurrentIndex(self.window.theme_picker.findData('blue'))
        self.assertEqual(core.Store(self.store.root).state['theme'], 'blue')
        self.assertEqual(self.window.property('mobaTheme')['accent'], '#5c9dff')
        self.window.theme_picker.setCurrentIndex(self.window.theme_picker.findData('light'))
        self.assertTrue(self.window.property('mobaTheme')['light'])
        with patch.object(ui.QColorDialog, 'getColor', return_value=QColor('#34ba95')):
            self.window.pick_theme_color()
        restored = core.Store(self.store.root)
        self.assertEqual((restored.state['theme'], restored.state['custom_accent']), ('custom', '#34ba95'))
        self.assertEqual(self.window.property('mobaTheme')['accent'], '#34ba95')
        self.assertEqual(self.store.state['connections'], before)

    def test_theme_save_failure_rolls_back(self):
        with patch.object(self.store, 'save', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                self.store.set_theme('blue')
        self.assertEqual(self.store.state['theme'], 'purple')

    def test_bulk_is_default_and_single_menu_is_absent(self):
        self.assertEqual(self.window.pages.currentIndex(), 0)
        self.assertFalse(hasattr(self.window, 'single_form'))
        self.assertNotIn('단건 입력', [button.text() for button in self.window.findChildren(QPushButton)])


if __name__ == '__main__':
    unittest.main()
