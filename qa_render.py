"""Render actual Qt widgets with synthetic connections and no desktop input."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import argparse
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import app as ui
import core
from key_picker import FavoriteKeysDialog, KeyPicker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    ui.configure_application(app)
    with tempfile.TemporaryDirectory() as temporary:
        store = core.Store(temporary)
        store.state['moba_exe'] = r'C:\Programs\MobaXterm.exe'
        store.state['favorite_keys'] = [
            {'name': '운영 서버', 'path': r'C:\Keys\production-key'},
            {'name': '운영 예비', 'path': r'C:\Keys\production-backup'},
            {'name': 'Bastion', 'path': r'C:\Keys\bastion.ppk'}]
        window = ui.MainWindow(store, dry_run=True, no_tray=True)
        rows = window.grid.rows()
        for index, row in enumerate(rows[:4]):
            row.update(name=f'server-{index + 1:02}', host=f'192.0.2.{index + 11}',
                       bastion_host='198.51.100.10', key_path=r'C:\Keys\production-key',
                       bastion_key_path=r'C:\Keys\bastion.ppk')
        rows[3]['key_path'] = r'C:\Keys\unregistered-key.pem'
        window.grid.set_rows(rows)
        window.grid.setCurrentCell(0, 0)
        window.show()
        app.processEvents()
        window.grab().save(str(args.output / '01-bulk-purple.png'))
        window.grid.toggle_current_bastion()
        app.processEvents()
        window.grab().save(str(args.output / '02-bastion.png'))
        window.bastion_rows.click()
        app.processEvents()
        window.grab().save(str(args.output / '03-all-bastion.png'))
        window.bastion_rows.click()
        window.grid.select_connection_rows(0, 2)
        app.processEvents()
        window.grab().save(str(args.output / '04-row-selection.png'))
        window.grid.leave_row_mode()
        for theme in ('blue', 'teal', 'amber', 'rose', 'slate', 'light'):
            window.theme_picker.setCurrentIndex(window.theme_picker.findData(theme))
            app.processEvents()
            window.grab().save(str(args.output / ('theme-' + theme + '.png')))
        window.theme_picker.setCurrentIndex(window.theme_picker.findData('purple'))
        window.grid.setCurrentCell(0, 5)
        window.grid.editItem(window.grid.item(0, 5))
        app.processEvents()
        picker = next(p for p in window.grid.viewport().findChildren(KeyPicker) if p.isVisible() and not p.closed)
        QTest.keyClicks(picker.combo, 'prod')
        app.processEvents()
        window.grab().save(str(args.output / '05-key-search.png'))
        picker.combo.completer().popup().grab().save(str(args.output / '06-ranked-keys.png'))
        picker.combo.completer().popup().hide()
        window.grid.commit_editor()
        window.select_page(1)
        app.processEvents()
        window.grab().save(str(args.output / '07-defaults.png'))
        manager = FavoriteKeysDialog(window.key_library, window)
        manager.show()
        app.processEvents()
        manager.grab().save(str(args.output / '08-favorite-manager.png'))
        manager.close()
        window.quitting = True
        window.close()


if __name__ == '__main__':
    main()
