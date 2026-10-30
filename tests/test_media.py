import io
import threading

import av
import numpy as np
from PIL import Image


def test_whisper_decoder_matches_installed_av():
    from faster_whisper.audio import decode_audio
    from audio.capture import pcm16_to_wav
    samples = (np.sin(np.arange(1600) * 0.05) * 1000).astype(np.int16)
    decoded = decode_audio(io.BytesIO(pcm16_to_wav(samples.tobytes())), sampling_rate=16000)
    assert len(decoded) == 1600
    assert np.isfinite(decoded).all()


def test_lesson_recorder_flushes_playable_video(monkeypatch):
    from tutor_features import lesson_recorder as lr
    captured = threading.Event()
    count = 0
    def frame():
        nonlocal count
        count += 1
        if count >= 3:
            captured.set()
        return Image.new("RGB", (321, 241), "blue")
    monkeypatch.setattr(lr, "capture_primary_image", frame)
    recorder = lr.LessonRecorder()
    path = recorder.start()
    try:
        assert path is not None
        recorder.log_question("Test question")
        recorder.log_answer("Test answer")
        assert captured.wait(3)
    finally:
        recorder.stop()
    assert not recorder.is_recording
    assert not recorder.last_error
    with av.open(str(path / "lesson.mp4")) as video:
        frames = list(video.decode(video=0))
        assert len(frames) >= 3
        assert (frames[0].width, frames[0].height) == (320, 240)
    transcript = (path / "transcript.md").read_text()
    assert "Test question" in transcript and "Test answer" in transcript


def test_lesson_capture_failure_is_reported_and_flushed(monkeypatch):
    from tutor_features import lesson_recorder as lr
    failed = threading.Event()
    count = 0
    def frame():
        nonlocal count
        count += 1
        if count > 1:
            raise RuntimeError("Output disconnected")
        return Image.new("RGB", (320, 240), "blue")
    monkeypatch.setattr(lr, "capture_primary_image", frame)
    recorder = lr.LessonRecorder()
    recorder.on_error = lambda _: failed.set()
    path = recorder.start()
    assert failed.wait(3)
    recorder.stop()
    assert "Output disconnected" in recorder.last_error
    assert (path / "transcript.md").exists()
    with av.open(str(path / "lesson.mp4")) as video:
        assert len(list(video.decode(video=0))) == 1
