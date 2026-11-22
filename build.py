"""Build the Windows executable; all generated files stay under ignored paths."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import subprocess
import sys

from PySide6.QtWidgets import QApplication
from app import icon, configure_application
from core import VERSION

root = Path(__file__).resolve().parent
build = root / "build"
build.mkdir(exist_ok=True)
app = QApplication([])
configure_application(app)
icon_file = build / "app.ico"
if not icon().pixmap(256, 256).save(str(icon_file), "ICO"):
    raise RuntimeError("Icon generation failed")
build_env = os.environ.copy()
# A desktop host can put unrelated native libraries on PATH. In particular an
# application-local ucrtbase.dll must never be bundled instead of the OS UCRT.
build_env["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), sys.base_prefix,
    str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"), os.environ.get("WINDIR", r"C:\Windows")))
for name in ("PYTHONPATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
    build_env.pop(name, None)
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                "--name", "MobaQuickConnect", "--icon", str(icon_file), "--distpath", str(root / "dist" / VERSION),
                "--workpath", str(build / "pyinstaller"), "--specpath", str(build),
                "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
                "--exclude-module", "PySide6.QtOpenGL", "--exclude-module", "PySide6.QtSql",
                "--exclude-module", "PySide6.QtTest", str(root / "app.py")], cwd=root, check=True, env=build_env)
