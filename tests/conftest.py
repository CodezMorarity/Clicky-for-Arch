import os
import tempfile
from pathlib import Path

# Isolate all test data and avoid touching the real desktop or settings.
_root = tempfile.TemporaryDirectory(prefix="clicky-tests-")
os.environ["CLICKY_DATA_DIR"] = str(Path(_root.name) / "data")
os.environ["CLICKY_CONFIG_FILE"] = str(Path(_root.name) / ".env")
os.environ["CLICKY_QT_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("CLICKY_DATA_DIR", str(tmp_path / "data"))
