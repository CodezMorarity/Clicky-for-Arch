import asyncio
import threading
import time
from unittest.mock import Mock

import pytest


@pytest.fixture
def manager(qapp, monkeypatch):
    import companion_manager as cm
    listener = Mock()
    listener.stop_recording.return_value = b"\0\0" * 16000
    monkeypatch.setattr(cm, "AmbientListener", lambda **_: listener)
    monkeypatch.setattr(cm.skills_pkg, "load_all", lambda: None)
    monkeypatch.setattr("audio.playback.stop_audio", lambda: None)
    instance = cm.CompanionManager()
    yield instance
    instance.shutdown()
    assert not instance._thread.is_alive()


def test_loop_ready_for_first_submission(manager):
    async def answer():
        return 42
    assert manager._submit(answer()).result(timeout=1) == 42


def test_stop_cancels_transcription_and_releases_microphone(manager):
    from ui.panel import AppState
    entered, cancelled = threading.Event(), threading.Event()
    class STT:
        async def transcribe(self, pcm):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    manager._stt = STT()
    manager.on_hotkey_press()
    manager._hotkey_pressed_at = time.monotonic() - 1
    manager.on_hotkey_release()
    assert entered.wait(2)
    manager.stop()
    assert cancelled.wait(2)
    async def settled():
        while manager._stopping:
            await asyncio.sleep(0.01)
    manager._submit(settled()).result(timeout=2)
    assert manager._state == AppState.IDLE
    assert manager._listener.stop_recording.call_count == 1
    assert not manager._request_tasks
    manager.on_hotkey_press()
    assert manager._state == AppState.LISTENING
    manager.stop()
    assert manager._listener.stop_recording.call_count == 2


def test_quiz_respects_privacy_before_capture(manager, monkeypatch):
    import companion_manager as cm
    captured = Mock(side_effect=AssertionError("Sensitive screen was captured"))
    monkeypatch.setattr(cm, "active_window_title", lambda: "1Password")
    monkeypatch.setattr(cm, "capture_all_screens", captured)
    images = []
    class LLM:
        async def stream_response(self, **kwargs):
            images.extend(kwargs["screenshots_b64"])
            yield "What did you learn?"
    class TTS:
        async def speak(self, text):
            pass
    manager._llm, manager._tts = LLM(), TTS()
    manager._submit(manager._kickoff_quiz(), request=True).result(timeout=2)
    captured.assert_not_called()
    assert images == []


def test_shutdown_flushes_recording_even_after_capture_failure(manager):
    recorder = Mock(is_recording=False)
    manager._recorder = recorder
    manager.shutdown()
    recorder.stop.assert_called_once()


def test_model_tag_detection_does_not_accept_different_size(monkeypatch):
    from ai import ollama_bootstrap as ob
    monkeypatch.setattr(ob, "list_installed_models", lambda: ["qwen2.5vl:7b", "llama3.2:latest"])
    assert not ob.is_model_installed("qwen2.5vl:3b")
    assert ob.is_model_installed("qwen2.5vl:7b")
    assert ob.is_model_installed("llama3.2")


def test_anchor_preserves_logical_coordinates_and_reuses_capture(manager, monkeypatch):
    from ai import hybrid_pointer
    from screen.capture import ScreenShot
    shot = ScreenShot(1, 1280, 720, "unused", 2560, 1440, -2560, 0, 2, -1280, 0)
    manager._screens_ctx = [shot]
    target = hybrid_pointer.Target(-600, 100, (-620, 80, -580, 120), "Save", "ocr", 1)
    finder = Mock(return_value=target)
    monkeypatch.setattr(hybrid_pointer, "find_target", finder)
    assert manager._resolve_anchor("Save") == (-620, 80, -580, 120)
    assert finder.call_args.kwargs["screenshot"] is shot
