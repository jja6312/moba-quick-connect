import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import app as ui
import core
import portable


class CompactRowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        ui.configure_application(cls.app)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.store=core.Store(self.root/'state')
        self.store.state['moba_exe']=r'C:\Programs\MobaXterm.exe'
        self.window=ui.MainWindow(self.store,dry_run=True,no_tray=True)
        self.window.show();self.app.processEvents()

    def tearDown(self):
        self.window.quitting=True;self.window.close();self.window.deleteLater()
        self.app.processEvents();self.tmp.cleanup()

    def test_name_is_first_column_and_trims_only_outer_whitespace(self):
        grid=self.window.grid
        self.assertEqual(grid.horizontalHeaderItem(0).text(),'연결 이름')
        grid.item(0,0).setText(' \r\n server 01\t ')
        grid.item(0,1).setText('\r\n 192.0.2.1 \t')
        grid.item(1,1).setText('\n 198.51.100.1 ')
        row=grid.rows()[0]
        self.assertEqual((row['name'],row['host'],row['bastion_host']),('server 01','192.0.2.1','198.51.100.1'))
        with self.assertRaises(ValueError):
            core.normalize({**row,'host':'192.0.2. 1'})

    def test_individual_collapse_and_expand_all_keep_bastion_values(self):
        self.window.select_page(0);self.app.processEvents()
        grid=self.window.grid
        grid.item(1,1).setText('198.51.100.1')
        self.assertTrue(all(grid.isRowHidden(r) for r in range(1,grid.rowCount(),2)))
        rect=grid.visualRect(grid.model().index(0,0))
        QTest.mouseClick(grid.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(rect.right()-12,rect.center().y()))
        self.app.processEvents()
        self.assertFalse(grid.isRowHidden(1));self.assertTrue(grid.isRowHidden(3))
        self.window.bastion_rows.click()
        self.assertTrue(all(not grid.isRowHidden(r) for r in range(1,grid.rowCount(),2)))
        self.window.bastion_rows.click()
        self.assertTrue(all(grid.isRowHidden(r) for r in range(1,grid.rowCount(),2)))
        self.assertEqual(grid.rows()[0]['bastion_host'],'198.51.100.1')

    def test_profile_bastion_is_collapsed_but_still_enabled(self):
        self.window.select_page(1)
        form=self.window.settings_form
        form.set_row({**core.new_row(self.store.profile),'bastion_host':'198.51.100.1'})
        self.assertTrue(form.jump.isChecked())
        self.assertFalse(form.jump_panel.isVisible())
        self.assertEqual(form.get_row()['bastion_host'],'198.51.100.1')
        form.jump_expand.click();self.app.processEvents()
        self.assertTrue(form.jump_panel.isVisible())

    def test_row_header_selection_copy_and_paste_include_hidden_bastion(self):
        self.window.select_page(0);self.app.processEvents()
        grid=self.window.grid
        rows=grid.rows();rows[0].update(name='node 01',host='192.0.2.1',bastion_host='198.51.100.1',bastion_user='jump')
        grid.set_rows(rows)
        header=grid.verticalHeader()
        self.assertFalse(header.viewport().cursor().pixmap().isNull())
        QTest.mouseClick(header.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(header.width()//2,grid.rowHeight(0)//2))
        self.app.processEvents()
        self.assertEqual(grid.whole_rows,{0})
        grid.copy();text=QApplication.clipboard().text()
        self.assertTrue(text.startswith('node 01\t192.0.2.1\tSSH'))
        self.assertIn('198.51.100.1',text)
        grid.setCurrentCell(2,0);grid.paste_text(text)
        self.assertEqual(grid.rows()[0],grid.rows()[1])

    def test_whole_connection_fill_copies_collapsed_bastion_and_undoes(self):
        grid=self.window.grid;rows=grid.rows()
        rows[0].update(name='node',host='192.0.2.1',bastion_host='198.51.100.1')
        grid.set_rows(rows);grid.select_connection_rows(0,0)
        grid.apply_fill((0,0,0,6),(0,0,2,6))
        self.assertTrue(all(r['bastion_host']=='198.51.100.1' for r in grid.rows()[:3]))
        grid.undo();self.assertEqual(grid.rows(),rows)

    def test_bundle_ui_import_rewrites_keys_and_leaves_registration_for_review(self):
        key=self.root/'fake-key';key.write_bytes(b'SYNTHETIC UI KEY')
        archive=self.root/'transfer.mobaquick.zip'
        portable.export_bundle(archive,[{**core.new_row(self.store.profile),'host':'192.0.2.1','key_path':str(key)}])
        with patch.object(ui.QFileDialog,'getOpenFileName',return_value=(str(archive),'')), \
             patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.window.import_package()
        self.assertEqual(self.window.pages.currentIndex(),0)
        imported=self.window.grid.rows()[0]
        self.assertNotEqual(imported['key_path'],str(key))
        self.assertEqual(Path(imported['key_path']).read_bytes(),b'SYNTHETIC UI KEY')
        self.assertEqual(self.store.state['connections'],[])
        self.assertTrue(self.window.grid.isRowHidden(1))
        exported=self.root/'again.mobaquick.zip'
        with patch.object(ui.QFileDialog,'getSaveFileName',return_value=(str(exported),'')):
            self.window.export_current_package()
        self.assertEqual(len(portable.read_bundle(exported).keys),1)

    def test_import_cancel_leaves_draft_and_favorites_unchanged(self):
        archive=self.root/'transfer.zip'
        portable.export_bundle(archive,[{**core.new_row(self.store.profile),'host':'192.0.2.1'}])
        before=self.window.grid.rows()
        with patch.object(ui.QFileDialog,'getOpenFileName',return_value=(str(archive),'')), \
             patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):
            self.window.import_package()
        self.assertEqual(self.window.grid.rows(),before)
        self.assertEqual(self.store.state['favorite_keys'],[])
        self.assertFalse((self.store.root/'imports').exists())


if __name__=='__main__':unittest.main()
