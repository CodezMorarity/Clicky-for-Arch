# Phase 1: Clicky on Omarchy

## Baseline audit (before application changes)

Reviewed all 79 tracked files at `6b76142`, including all 57 Python modules
(11,004 lines), both dependency manifests, environment/debug configuration,
Windows packaging, documentation and repository metadata. The remaining asset
is the demonstration GIF. There are no AGENTS.md files, automated tests, CI
workflows, lint settings or type-check settings. The initial working tree was
clean. All Python source parses on Python 3.14 (one invalid-escape warning in
the icon generator).

Host: Omarchy 4.0.1, Arch packages, Python 3.14.7, Hyprland 0.56.2,
Wayland with XWayland, 1920x1080 output at 1.25 scale, 16 GB RAM, NVIDIA
RTX 4050 laptop GPU. PortAudio, PipeWire, grim, slurp, wl-clipboard, wtype,
Tesseract plus English data, FFmpeg and Qt native libraries are installed.
No project virtual environment or .env existed. Ollama was absent from PATH.

## Architecture and execution

* `main.py`: fixes frozen-build streams, creates QApplication, manager, panel,
  overlay and tray; connects Qt signals, hooks shortcuts, starts listening,
  opens first-run setup, then enters the Qt event loop.
* `config.py`: dotenv configuration, provider priority, mutable singleton,
  persisted settings, system prompt and annotation syntax.
* `companion_manager.py`: QObject state machine (idle/listening/thinking/
  speaking), separate asyncio thread; lazy provider creation, microphone
  lifecycle, silence detection, context assembly, streaming, narration and
  cancellation. UI updates mostly use queued Qt signals.
* `audio/`: PortAudio capture, PCM noise gate/gain/resampling, local/cloud STT,
  wake-word Whisper, TTS downloads, PyAV decoding and cancellable playback.
* `screen/`: monitor capture plus physical, logical and JPEG coordinate metadata.
* `ai/`: six interchangeable LLM backends; OAuth and model caches; Ollama
  bootstrap/pull; search; UIA/OCR/vision pointing; local OpenCV figure detection.
* `tutor.py`, `tutor_features/`: window context, privacy/classification,
  documents, journal/review, language/IDE hints, recordings and workflow capture.
* `ui/`: existing PyQt6 panel, transparent QPainter overlay, tray, setup and API
  dialogs. No web frontend or application server.
* `skills/`: bundled/user Python trigger plugins. `assets/`, `clicky.spec`,
  `build.bat`, `installer.iss`: icon generation and Windows distribution.

Request flow: shortcut/wake -> record PCM -> transcribe -> local commands or
window/privacy check -> screenshots -> figures/search/point locator -> prompt
and per-app history -> streamed LLM text -> normalize tags to screen coordinates
-> journal/transcript -> speech synchronized with annotation signals -> idle.

## Dependency inventory

| Dependencies | Role / portability |
| --- | --- |
| PyQt6, bundled Qt6, PyQt6-sip | Widgets, painting, tray; needs xcb native libraries for positioned overlay |
| Pillow, mss | Image processing and Windows/X11 capture; mss is unsuitable for native Wayland windows |
| keyboard | Windows global hooks; Linux implementation requires root/raw input access |
| pynput (and platform-specific transitive backends) | Workflow events; XWayland sees only XWayland applications |
| uiautomation, comtypes | Windows-only accessibility tree; unguarded student requirement prevents Linux installation |
| rapidocr-onnxruntime, onnxruntime, OpenCV, NumPy | Offline text localization / figure detection; native wheel compatibility matters |
| sounddevice, CFFI, PortAudio | Cross-platform capture/playback; PortAudio must exist on Linux |
| soundfile, libsndfile, NumPy, av/FFmpeg | Audio containers, samples and decoding; most are native wheels |
| faster-whisper, ctranslate2, tokenizers, huggingface-hub, onnxruntime | CPU int8 STT and wake word; model downloads required once; wheel availability varies by Python version |
| pywhispercpp | Optional alternative STT; wheel/build and acceleration depend on platform |
| edge-tts, aiohttp | Free online Microsoft speech; not an offline TTS engine |
| openai, anthropic | SDKs used by cloud providers; keys required only for selected providers |
| httpx | Gemini, Ollama, LM Studio, Copilot, Deepgram, ElevenLabs, Tavily REST/SSE |
| ollama, elevenlabs, tavily-python | Listed SDKs, but current providers use httpx directly |
| python-dotenv | Read and persist settings |
| ddgs | Maintained free search; only student manifest originally included it |
| pypdf, python-docx (lxml) | PDF/DOCX context extraction |
| pytesseract, Tesseract binary and language data | Fine-print OCR; absent from student manifest |
| langdetect | Language hints and speech voice selection |
| imageio, imageio-ffmpeg | MP4 lessons; capture backend was hardcoded to mss |
| aiortc | Commented optional requirement; collaboration is an unimplemented skeleton |
| PyInstaller, Inno Setup, PowerShell, Windows SDK signing tools | Windows-only build/release tooling, not Linux runtime prerequisites |

Standard-library dependencies include asyncio, threading, SQLite, ctypes,
subprocess, pathlib, tempfile, wave, urllib, JSON, regex and importlib. Native
Linux additions are grim and Hyprland IPC; XWayland retains the Qt rendering.
Exact resolved transitive versions belong in a Linux validation lock after
installation, rather than guessing versions from the unbounded manifests.

## Platform audit and replacements

| Files / assumptions | Failure or risk | Replacement |
| --- | --- | --- |
| `hotkey.py`: keyboard hooks and F24 Start-menu suppression | Raw Linux keyboard hooks need root; X11 hooks miss Wayland | Separate Hyprland shortcuts and same-user local control channel; retain Windows implementation |
| `screen/capture.py`: mss, user32 DPI | Native windows absent/black; incorrect scaling | grim per output + Hyprland monitor metadata; preserve mss elsewhere |
| `tutor.py`: GetForegroundWindow/GetWindowTextW | Empty title silently disables privacy, IDE detection and per-app memory | Hyprland activewindow metadata; fail clearly when unavailable |
| `ai/hybrid_pointer.py`: UIA, direct mss, pixel-only OCR results | Windows imports and extra capture; missing origin/scale | Guard UIA; use existing screenshot for Linux Tesseract/OCR; one logical-coordinate contract |
| Both vision locators + manager | Divide global origin by one DPI factor | Separate logical origin from local physical pixels, including negative/mixed-scale outputs |
| `ui/overlay.py`, `ui/panel.py` | Wayland XDG-shell cannot position global top-level windows; QCursor is not global there | Existing painter via xcb/XWayland, explicit non-focusing click-through overlay; map compositor coordinates to Qt output geometry |
| `ui/design.py`, overlay, grid font loader | Segoe UI/Arial not generally installed | Linux sans-serif fallback; retain Windows family |
| `companion_manager.py`: tasklist / DETACHED_PROCESS; bootstrap creationflags | AttributeError or invalid Popen flags; ignores configured server URL | One platform-aware bootstrap, localhost-only process startup |
| `ai/ollama_bootstrap.py`, setup wizard | Downloads/executes OllamaSetup.exe, UAC/Start-menu instructions | Linux package installation instructions and native `ollama serve`; Windows installer remains guarded |
| main, journal, model caches, Copilot token, wizard | LOCALAPPDATA falls back to loose ~/Clicky; inconsistent paths | Central XDG helpers, preserve existing Windows and legacy data |
| config + manager setting writers | Assumes writable install directory; inconsistent .env paths | Central writable Linux config path and explicit override; preserve source .env input |
| main journal/diagnostics | os.startfile, explorer | Qt desktop-services file URLs |
| lesson recorder | mss plus hardcoded ~/Documents; errors swallowed | Shared native capture, writable data directory, surfaced recording failures |
| workflow capture | pynput claims success while missing native input | Explicit unsupported capability on Wayland until a consented input backend exists; retain Windows/X11 behavior |
| requirements | Student unconditionally installs UIA; full misses ddgs/OpenCV; broad version bounds | Common requirements plus platform markers and optional extras |
| .vscode config | `.venv/Scripts/python.exe` | Portable virtual-environment interpreter selection |
| build.bat, installer.iss, clicky.spec, icon generator | Windows distribution paths/commands | Preserve Windows packaging; document source-based Linux launch |
| prompts, examples and manuals | Windows instructions on Linux; false fully-offline claim | Platform-neutral runtime wording and dedicated tested Linux instructions |
| web search User-Agent | Claims Windows | HTTP compatibility string, not an OS API; no Linux runtime failure |
| `skills/` | ~/.clicky user path and example calc.exe in README | Preserve legacy skill discovery; document that arbitrary user plugins need their own platform guards |

## Existing limitations distinguished from migration

Collaboration and workflow replay are stubs. The example self-mode sets a flag
but never clicks. Voice-picker command parsing advertised in README is absent.
Review grading is optimistic, not implemented grading. Edge TTS and enabled
web search use the network even with local LLM/STT. Privacy is an active-window
title heuristic, not redaction of other visible windows/monitors. Lessons record
video/transcript, not a mixed microphone/TTS audio track. Several older manual
test expectations and model/cost claims are stale. These are not AccessPath work.

Reliability defects relevant to baseline: unwired panel PTT, asyncio startup
race, untracked request cancellation, microphone remaining open after Stop,
unfinished recorder on Quit, LM Studio panel selecting an Ollama model, and
privacy bypass in quiz kickoff. Fix with focused regression tests, retaining
the existing UI and provider interfaces.

## Incremental implementation plan and files

1. Dependencies and startup: `requirements*.txt`, `config.py`, shared
   `desktop/` helpers, `main.py`, bootstrap, all storage call sites, setup copy,
   `.env.example`, `.vscode`, regression tests. Resolve native wheel support;
   verify imports, dependency consistency and startup diagnostics.
2. Desktop integration: `hotkey.py`, new desktop adapters, capture, tutor,
   pointer/vision coordinate mapping, overlay integration, recorder/workflow.
   Verify capture content/dimensions, scale/origin transforms, shortcut cleanup,
   focused-window lookup, overlay placement and click-through on live Hyprland.
3. Reliability and local-model validation: manager lifecycle/cancellation,
   existing panel button/model wiring, Linux launcher/diagnostics and setup docs.
   Unit/integration tests, Python compilation, lint for errors, import sweep,
   offscreen startup then live startup; actual microphone, local STT, Ollama
   vision/text, TTS and MP4 probes where the environment permits.

Each step records passed checks and outstanding limits. Windows paths receive
mocked regression coverage; actual Windows execution requires a Windows host.
No UI redesign, automatic input/replay feature, or AccessPath implementation.

## References checked during audit

* [Qt window positioning and Wayland](https://doc.qt.io/QT-6/application-windows.html)
* [Qt window flags](https://doc.qt.io/qt-6.12/qt.html)
* [pynput platform limitations](https://pynput.readthedocs.io/en/latest/limitations.html)
* [Hyprland Lua bindings](https://wiki.hypr.land/Configuring/Basics/Binds/)
* [Hyprland window rules](https://wiki.hypr.land/Configuring/Basics/Window-Rules/)
* [grim](https://github.com/emersion/grim)


## Implementation and validation results

Phase 1 implementation completed on this host on 2026-10-14/15. The original
panel, tray, painter, providers and teaching flow remain in place. New platform
code is isolated in `desktop/`; Windows hooks, paths and installer are retained.

### Increment 1 — dependencies, storage, bootstrap

* Common requirements now install on Linux, with Windows-only hooks/UIA/OCR
  guarded by markers. The exact Linux environment is recorded in
  `requirements-linux.lock.txt`. PyAV 18.1.0 is used: PyAV 19 removed
  `metadata_errors`, breaking the released faster-whisper 1.2.1 decoder.
* XDG storage/configuration, legacy data compatibility, native Ollama process
  startup, Linux setup instructions, portable file opening and editor paths.
* Six initial regression checks passed; all 57 original Python modules imported;
  dependency consistency and error-focused lint passed. A pre-existing undefined
  search HTML helper was repaired after lint exposed it.

### Increment 2 — desktop integration

* Native `grim` screenshots, Hyprland window titles, output-to-Qt geometry
  mapping, a non-focusing XWayland canvas, Linux font fallback, Tesseract local
  pointing, and shared native recording capture. Both vision locators accept
  independent logical origins. Hybrid pointer targets are no longer scaled twice.
* Session-only Hyprland Lua shortcuts use private same-user Unix sockets and
  queued Qt callbacks. Conflicts are preserved, reloads are detected, and stale
  bindings from terminated Clicky processes can be reclaimed.
* Live 1920×1080 / 125% capture passed. A calibrated overlay marker landed at
  the expected physical pixel coordinates. The canvas did not become the
  focused application. Callback delivery and removal of all test bindings passed.
* Automated coordinate tests cover different scales and negative origins.
  Fourteen tests passed at this increment.
* The `wtype` synthetic-key probe produced inconsistent keymaps/modifiers in
  this session and was not counted as successful keyboard validation. The user
  subsequently confirmed **physical Ctrl+Alt+Space starts listening and Escape
  returns to idle** in the running application.

### Increment 3 — lifecycle and complete application

* Wired the existing panel talk button; corrected local automatic model
  selection; synchronized asyncio startup; scoped cancellation to active
  requests; stopped capture on Escape; canceled outstanding locator/search
  tasks; finalized recordings and HTTP clients on exit; stopped the resume
  watchdog on shutdown; applied privacy checks before quiz capture.
* Added a source launcher, environment diagnostics, Linux instructions and
  focused regression coverage. No UI redesign or AccessPath work.
* Full application startup and shutdown passed through
  `main.py --smoke-test 3 --show-panel` on the live desktop.
* Local Ollama `llama3.2:3b` correctly answered the text test. `qwen2.5vl:3b`
  correctly identified a synthetic red circle. CPU vision took about 101 s;
  after installing Arch's CUDA backend the same check took about 9 s, including
  loading the model. These are single-run measurements, not benchmark promises.
* Edge TTS produced speech; PyAV decoded it; local faster-whisper base returned
  “Clicky is ready. The red circle is on the screen.” Spoken playback completed.
  A brief real microphone check received 17,280 PCM bytes over 19 callbacks;
  captured microphone audio was discarded.
* The complete manager/UI flow passed with a generated spoken question and
  **live Wayland capture** of a temporary canvas: LISTENING → THINKING →
  SPEAKING → IDLE, answer “The circle on your screen is red.” Total about 11 s.
  The reproducible opt-in check is `tests/manual_end_to_end.py`.
* Real FFmpeg recording tests produce decodable H.264 MP4s and transcripts;
  odd dimensions and capture failures are covered. Regression tests also cover
  cancellation during transcription, privacy before quiz capture, recorder
  cleanup, Windows/Linux bootstrap flags, shortcut conflicts and model tags.
* Lifecycle tests must run outside a sandbox denying Unix sockets: asyncio's
  cross-thread wakeup otherwise times out. The suite passes on the real host.

Final checks: **23 automated tests passed**, all **63 application modules
imported**, Python sources/tests/tools compiled, error-focused Ruff passed,
`pip check` reported no broken requirements, the Bash launcher passed syntax
validation, and the live environment diagnostic reported no errors. There was
no static type-check configuration in the original project; no full-project
static type-check claim is made.

### Host changes and remaining limits

Created the project's `.venv`, installed Ollama plus `ollama-cuda` and its Arch
CUDA dependencies, downloaded both LLMs and the base Whisper model, and saved
`CLICKY_ACTIVE_LLM=ollama` in `~/.config/clicky/.env`. The setup-complete marker
lives in the XDG data directory. Temporary user services `clicky-ollama` and
`clicky` run the server and application; no persistent autostart or Hyprland
configuration files were changed. `clicky-models` finished its downloads.

Wayland workflow input recording is explicitly disabled because the existing
pynput backend cannot reliably observe native clients. Collaboration/replay
remain pre-existing stubs. Edge TTS/search need the network. Actual Windows
runtime, physical multi-monitor arrangements, other Wayland compositors,
optional paid cloud providers and real suspend/resume were not tested on this
host. Windows compatibility has guarded paths and mocked regression coverage,
not an unsupported claim of a Windows smoke test.

Additional dependency reference:
[PyAV 19 API removals](https://pyav.basswood.io/docs/stable/development/changelog.html).

## Cross-desktop support update

The Linux adapters now also target X11 and common Wayland sessions. X11 uses
`mss`, `xprop`, and an unprivileged `pynput` listener. Sway adds compositor IPC
for focused-window metadata and uses `grim` for per-output capture. GNOME, KDE,
and other Wayland sessions use the XDG Screenshot and Global Shortcuts portals
when their selected portal backends provide those interfaces. Unknown window
titles remain blocked by the privacy guard unless an interactive screenshot
portal is used. Portal screenshots are one-shot; continuous lesson recording
and workflow input recording remain unavailable on generic Wayland sessions.
The Escape stop shortcut stays with the focused app on portal-only sessions;
use the tray's Stop action to cancel a response.

The added desktop adapters have not yet received live validation on X11, Sway,
GNOME, or KDE Plasma. Only the Hyprland/Omarchy path has the live validation
recorded above.
