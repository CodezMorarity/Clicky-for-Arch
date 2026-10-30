# Clicky on Arch Linux

This is the original PyQt6 application with Linux desktop adapters. It supports
X11 and common Wayland sessions: Hyprland, Sway, GNOME, and KDE Plasma. Some
Wayland features depend on the desktop's XDG portal backend. The original
Hyprland path is the only Wayland setup with end-to-end live validation so far.
No AccessPath functionality is included.

## Install

Install the base packages from your regular desktop terminal:

```bash
sudo pacman -S --needed python python-pip portaudio libsndfile xorg-xwayland \
  libxcb xcb-util-cursor libxkbcommon-x11 grim tesseract tesseract-data-eng \
  ffmpeg ollama xorg-xprop xdg-desktop-portal
```

For NVIDIA systems, also install the Arch Ollama CUDA backend:

```bash
sudo pacman -S --needed ollama-cuda
```

Install the portal backend for the desktop session you use. Install only the
matching backend; the desktop may already provide it:

```bash
# GNOME
sudo pacman -S --needed xdg-desktop-portal-gnome
# KDE Plasma
sudo pacman -S --needed xdg-desktop-portal-kde
# Sway / wlroots
sudo pacman -S --needed xdg-desktop-portal-wlr
# Hyprland
sudo pacman -S --needed xdg-desktop-portal-hyprland
```

Then create the environment and install Clicky's Python requirements:

```bash
cd /path/to/clicky-omarchy
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
ollama serve
```

Leave the server terminal running while downloading in another terminal:

```bash
ollama pull llama3.2:3b
ollama pull qwen2.5vl:3b
./run-linux.sh --show-panel
```

On Omarchy, use `omarchy pkg add` instead of `sudo pacman -S`. Clicky can start
a local `ollama serve` process when needed if it is installed on PATH. An
existing server is reused. A remote `OLLAMA_HOST` never starts a local server.
CUDA is optional for installation, but strongly improves local vision latency.
The NVIDIA driver must already be working; check `nvidia-smi` and `ollama ps`.

For the exact Linux environment used in validation, install
`requirements-linux.lock.txt` instead of `requirements.txt`. The lock includes
pytest and Ruff; it is Linux-specific. The normal requirements retain Windows
markers. PyAV is capped below 19 because released faster-whisper 1.2.1 still
uses a decoder argument removed in PyAV 19.

## Use

* Hold **Ctrl+Alt+Space**, speak, then release Space to send. A quick tap keeps
  listening until speech ends. The panel's **Hold to talk** button also works.
* **Escape** cancels on Windows, X11, and Hyprland. On portal-only Wayland,
  use Tray → **Stop**; Escape continues to reach the focused application.
* Open the panel and settings from the system tray. The panel opens
  automatically if global shortcut registration fails or no tray is available.
* Microphone access defaults to push-to-talk. Enable the existing wake-word
  option in the tray if you want continuous listening; that downloads the tiny
  Whisper model on first use. Normal transcription uses the base Whisper model.

On X11, shortcuts use `pynput` and do not require root or raw `/dev/input`
access. Hyprland shortcuts are registered only for Clicky's lifetime; existing
shortcut conflicts are reported rather than overwritten. Other Wayland
desktops use the XDG Global Shortcuts portal if their backend implements it.
Portal registration may ask you to approve or choose a key. If a shortcut is
unavailable, Clicky opens the panel so its talk button remains usable. Linux
shortcuts need a terminal key, such as `ctrl+alt+space`.

## Storage and configuration

Linux settings saved by the UI live in `~/.config/clicky/.env`. Data, logs,
SQLite journal and provider caches live in `~/.local/share/clicky/`. Recordings
are under that data directory's `recordings/` folder. XDG environment overrides
are honored. An existing legacy `~/Clicky` data directory remains in use.

The source checkout's `.env` and `.env.local` remain readable for compatibility;
Linux user settings take priority. `CLICKY_CONFIG_FILE=/absolute/path` selects
a single settings file, and `CLICKY_DATA_DIR=/absolute/path` isolates data.
The Windows locations remain unchanged.

Minimal optional settings:

```dotenv
CLICKY_ACTIVE_LLM=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_TEXT_MODEL=llama3.2:3b
OLLAMA_VISION_MODEL=qwen2.5vl:3b
HOTKEY=ctrl+alt+space
CLICKY_MIC_MODE=hotkey
WHISPER_MODEL=base
```

No API keys are needed for this setup. LLM inference and speech recognition
run locally after model downloads. **Edge speech synthesis and enabled web
search still require internet access.** This configuration is not fully offline.

## Desktop behavior and limits

X11 uses `mss` for capture and X11 window metadata for the privacy guard. Sway
and Hyprland use `grim` plus compositor IPC for capture, scale, and active-window
titles. GNOME, KDE Plasma, and other Wayland sessions use the XDG Screenshot
portal when available. The portal asks you to approve each screen capture; if
you cancel or its backend is missing, Clicky continues without a screenshot.
The desktop may expose the returned image through its document portal while
Clicky reads it; Clicky does not create a separate persistent screenshot copy.
When the active window cannot be identified, the existing privacy guard only
allows capture through this interactive portal path.

Qt uses XWayland when available so it can position the panel and overlay. On
native Wayland sessions without XWayland positioning, or on multi-monitor
sessions where portal coordinates are ambiguous, Clicky hides the pointer
overlay and keeps the panel and voice controls. Portal screenshots are
one-shot, so continuous lesson recording is unavailable on those sessions.
XDG Global Shortcuts are used where the desktop portal backend supports them;
otherwise the panel's talk button is the fallback. Workflow input recording
remains disabled on Wayland because `pynput` cannot observe native clients.

The Hyprland live check used a 1920×1080 display at 125% scale. Sway, GNOME,
KDE Plasma, and general X11 support now have adapters but need live validation
on those desktop sessions. Keep `DISPLAY` and `WAYLAND_DISPLAY` available when
the desktop provides XWayland. `CLICKY_QT_PLATFORM` remains an override for
troubleshooting.

Windows UI Automation stays on Windows. Linux uses Tesseract text localization
on the captured screenshot and the existing vision fallback. Model-based
pointing remains approximate. OCR quality depends on text size and installed
Tesseract languages.

Workflow replay and collaboration remain unfinished upstream. On supported
continuous-capture backends, lesson recording saves MP4 video plus a Markdown
transcript; it does not add an audio track. Privacy protection is an
active-window-title heuristic, not redaction of every visible window. Unknown
window titles fail closed except when the screenshot portal presents the user
with an explicit capture interaction.

## Verify or troubleshoot

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python -m pip check
.venv/bin/python scripts/check_environment.py --live
./run-linux.sh --smoke-test 3 --show-panel
```

`--live` captures images only in memory and reports metadata, device names and
local model availability. The startup smoke check exercises the actual UI,
shortcuts and cleanup, then exits. Run desktop checks outside containers or
sandboxes that deny Wayland, D-Bus, audio or local Unix sockets. Such restrictions
also prevent asyncio's cross-thread wakeup and cause false lifecycle timeouts.

An opt-in complete pipeline check opens a temporary test canvas, generates a
spoken question, uses real STT/capture/Ollama/TTS, and exits:

```bash
.venv/bin/python tests/manual_end_to_end.py
```

This test sends only the generated question to Edge TTS and captures your
visible desktop for the **local** model. Keep the test canvas visible. Microphone
hardware should also be checked by speaking with the real talk shortcut/button.

Logs: `~/.local/share/clicky/clicky.log` (or the legacy/overridden data directory).
For microphone trouble, select the device under Tray → Setup & Diagnostics.
For slow local inference, confirm `ollama ps` reports GPU use. For shortcut
conflicts, choose a free chord in the settings file and restart Clicky.
Exit through Tray → Quit so shortcuts, model clients and recordings are cleaned up.
