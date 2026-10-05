# PyInstaller spec for AzerothQuantBrain.exe (#115): one file, no console window.
# Build from brain/:  pyinstaller AzerothQuantBrain.spec
# CI builds it on a v* tag (the brain-exe job in .github/workflows/ci.yml).

import io
import shutil
import subprocess
import tarfile
from pathlib import Path

ADDON = "addon/AzerothQuant"
repo = Path(SPECPATH).parent

# The Addon comes from the last commit, not the working tree: on the dev PC the Brain
# writes addon/AzerothQuant/Recommendations.lua, and the exe has to carry the stub.
addon_copy = Path(workpath) / "committed"
shutil.rmtree(addon_copy, ignore_errors=True)
archive = subprocess.run(
    ["git", "archive", "HEAD", ADDON], cwd=repo, capture_output=True, check=True
).stdout
with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
    tar.extractall(addon_copy, filter="data")
if not (addon_copy / ADDON / "AzerothQuant.toc").is_file():
    raise SystemExit(f"No {ADDON}/AzerothQuant.toc in HEAD")

a = Analysis(
    ["src/brain/app.py"],
    pathex=[str(Path(SPECPATH) / "src")],
    datas=[
        # brain.app reads it from sys._MEIPASS/AzerothQuant.
        (str(addon_copy / ADDON), "AzerothQuant"),
        # brain.disenchant reads it next to its own module.
        ("src/brain/data/*.toml", "brain/data"),
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="AzerothQuantBrain",
    console=False,
    upx=False,
)
