"""Render the actual Qt widgets using only synthetic data; no desktop input."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import argparse
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
import app as ui
import core


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    ui.configure_application(app)
    with tempfile.TemporaryDirectory() as temporary:
        store = core.Store(temporary)
        store.state["moba_exe"] = r"C:\Programs\MobaXterm.exe"
        store.state["favorite_keys"] = [
            {"name": "운영 서버", "path": r"C:\Keys\production-key"},
            {"name": "Bastion", "path": r"C:\Keys\bastion.ppk"}]
        window = ui.MainWindow(store, dry_run=True, no_tray=True)
        window.show()
        app.processEvents()
        window.grab().save(str(args.output / "01-single-ssh.png"))
        window.single_protocol.setCurrentText("RDP")
        window.single_form.jump.setChecked(True)
        window.single_form.fields["bastion_host"].setText("198.51.100.10")
        app.processEvents()
        window.grab().save(str(args.output / "02-rdp-bastion.png"))
        window.select_page(1)
        window.grid.setCurrentCell(0, 0)
        window.grid.paste_text("192.0.2.11\n192.0.2.12\n192.0.2.13\n192.0.2.14")
        rows = window.grid.rows()
        for index, row in enumerate(rows[:4]):
            row.update(name=f"server-{index + 1:02}", bastion_host="198.51.100.10")
        window.grid.set_rows(rows)
        window.grid.setCurrentCell(0, 0)
        app.processEvents()
        window.grab().save(str(args.output / "03-bulk.png"))
        window.bastion_rows.click()
        app.processEvents()
        window.grab().save(str(args.output / "07-bulk-expanded.png"))
        window.bastion_rows.click()
        window.details.setChecked(False)
        app.processEvents()
        window.grab().save(str(args.output / "04-bulk-basic.png"))
        window.select_page(2)
        app.processEvents()
        window.grab().save(str(args.output / "05-defaults.png"))
        window.select_page(0)
        window.single_protocol.setCurrentText("SSH")
        window.resize(760, 420)
        app.processEvents()
        window.grab().save(str(args.output / "06-compact.png"))
        window.resize(860, 440)
        window.single_form.fields["key_path"].combo.showPopup()
        app.processEvents()
        window.grab().save(str(args.output / "08-key-selector.png"))
        window.single_form.fields["key_path"].combo.view().window().grab().save(str(args.output / "09-key-dropdown.png"))
        window.single_form.fields["key_path"].combo.hidePopup()
        from key_picker import FavoriteKeysDialog
        manager = FavoriteKeysDialog(window.key_library, window)
        manager.show()
        app.processEvents()
        manager.grab().save(str(args.output / "10-favorite-manager.png"))
        manager.close()
        window.quitting = True
        window.close()


if __name__ == "__main__":
    main()
