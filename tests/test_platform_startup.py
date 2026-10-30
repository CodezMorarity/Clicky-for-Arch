from pathlib import Path
from unittest.mock import Mock

from desktop import paths
from ai import ollama_bootstrap as ob


def test_linux_and_windows_data_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("CLICKY_DATA_DIR")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(paths, "is_windows", lambda: False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.data_dir() == tmp_path / "xdg/clicky"
    (tmp_path / "Clicky").mkdir()
    assert paths.data_dir() == tmp_path / "Clicky"
    monkeypatch.setattr(paths, "is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "windows"))
    assert paths.data_dir() == tmp_path / "windows/Clicky"


def test_settings_persist_to_writable_config(monkeypatch):
    from config import Config
    config = Config()
    monkeypatch.delenv("CLICKY_ACTIVE_LLM", raising=False)
    config.set_active_llm("ollama")
    config.set_api_key("GOOGLE_API_KEY", "test-only")
    assert "CLICKY_ACTIVE_LLM=ollama" in config.env_path().read_text()
    assert "GOOGLE_API_KEY=test-only" in config.env_path().read_text()
    config.set_api_key("GOOGLE_API_KEY", "")
    assert "GOOGLE_API_KEY" not in config.env_path().read_text()


def test_ollama_process_flags_are_platform_specific(monkeypatch):
    monkeypatch.setattr(ob, "find_ollama_binary", lambda: Path("/usr/bin/ollama"))
    monkeypatch.setattr(ob.cfg, "ollama_host", "http://127.0.0.1:11434")
    popen = Mock()
    monkeypatch.setattr(ob.subprocess, "Popen", popen)
    monkeypatch.setattr(ob, "is_windows", lambda: False)
    assert ob.start_ollama_server()
    assert popen.call_args.kwargs["start_new_session"] is True
    assert "creationflags" not in popen.call_args.kwargs
    monkeypatch.setattr(ob, "is_windows", lambda: True)
    assert ob.start_ollama_server()
    assert popen.call_args.kwargs["creationflags"] == 0x208
    assert "start_new_session" not in popen.call_args.kwargs


def test_remote_ollama_never_starts_local_process(monkeypatch):
    monkeypatch.setattr(ob.cfg, "ollama_host", "https://models.example:11434")
    monkeypatch.setattr(ob, "find_ollama_binary", lambda: Path("/usr/bin/ollama"))
    popen = Mock()
    monkeypatch.setattr(ob.subprocess, "Popen", popen)
    assert not ob.start_ollama_server()
    popen.assert_not_called()


def test_linux_never_downloads_exe(monkeypatch):
    import pytest
    monkeypatch.setattr(ob, "is_windows", lambda: False)
    with pytest.raises(RuntimeError, match="omarchy pkg add"):
        ob.download_ollama_installer()


def test_setup_and_panel_construct(qapp):
    from ui.panel import CompanionPanel
    from ui.setup_wizard import SetupWizard
    panel, wizard = CompanionPanel(), SetupWizard()
    wizard._set_step("install")
    assert "omarchy pkg add" in wizard.subtitle.text()
    panel.close()
    wizard.close()
