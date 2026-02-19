# chooon-viz

Real-time audio-reactive visualiser for Python.
Analyses your microphone or line-in and drives animated visuals that **pulse,
morph, and change colour** to the beat.  Load any image as an overlay and
transform it into a mandala or kaleidoscope — with a palette-tinted glow
outline that reacts to the music.

---

## Table of contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Quick start](#quick-start)
4. [Command-line flags](#command-line-flags)
5. [Keyboard shortcuts](#keyboard-shortcuts)
6. [Control panel](#control-panel)
   - [Animation](#animation-section)
   - [Color Palette](#color-palette-section)
   - [Layers](#layers-section)
   - [Image Overlay](#image-overlay-section)
   - [Image Transforms](#image-transforms-section)
   - [Audio Input](#audio-input-section)
7. [Visual layers in detail](#visual-layers-in-detail)
8. [Image overlay in detail](#image-overlay-in-detail)
   - [Supported formats & resolutions](#supported-formats--resolutions)
   - [Symmetry modes](#symmetry-modes)
   - [Outline / edge detection](#outline--edge-detection)
9. [Audio analysis explained](#audio-analysis-explained)
10. [Setting up your audio source](#setting-up-your-audio-source)
11. [Performance tips](#performance-tips)
12. [Troubleshooting](#troubleshooting)
13. [Technical reference](#technical-reference)

---

## Requirements

| Component     | Version          |
|---------------|------------------|
| Python        | 3.10 – 3.13 ⚠️   |
| pygame        | ≥ 2.5            |
| pyaudio       | ≥ 0.2.14         |
| numpy         | ≥ 1.24           |
| Pillow        | ≥ 10.0           |
| scipy         | ≥ 1.11           |

> ⚠️ **Python 3.14 is not yet supported.**  pygame 2.6.x does not ship
> pre-built wheels for Python 3.14, and building from source requires SDL2
> headers that are not included with Xcode.  Use Python **3.12 or 3.13**
> (both have ready-made pygame wheels for macOS Apple Silicon and Intel).

**System libraries** (install these *before* running `pip install`):

```bash
# macOS (Homebrew) — installs portaudio for pyaudio
brew install portaudio

# Debian / Ubuntu
sudo apt install portaudio19-dev

# Windows – pre-built wheels cover everything; no extra step needed
```

---

## Installation

### macOS (Apple Silicon or Intel)

macOS does not ship Python 3 as `python` — you must use `python3`.
Also check your Python version first: **3.14+ will fail** (see Requirements).

```bash
# Check your version — must be 3.10–3.13
python3 --version

# If you see 3.14 or higher, install 3.13 via Homebrew:
brew install python@3.13

# Homebrew Python 3.13 does NOT include Tcl/Tk (needed for the control panel)
# Install it explicitly — this step is required:
brew install python-tk@3.13

# Install system dependency for audio
brew install portaudio

# Clone the repo — note the spelling: three o's in chooon
git clone https://github.com/MIKExWEINSTEIN/chooon-viz.git chooon-viz
cd chooon-viz                          # make sure you cd into chooon-viz

# Create a virtual environment with Python 3.13
python3.13 -m venv .venv
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt

# Run
python3 main.py --windowed
```

### Linux (Debian / Ubuntu)

```bash
sudo apt install portaudio19-dev
git clone https://github.com/MIKExWEINSTEIN/chooon-viz.git chooon-viz
cd chooon-viz
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

### Windows

```powershell
git clone https://github.com/MIKExWEINSTEIN/chooon-viz.git chooon-viz
cd chooon-viz
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py --windowed
```

---

## Quick start

> On **macOS / Linux** replace `python` with `python3` in all commands below.

```bash
# Fullscreen on the primary monitor
python3 main.py

# Resizable window (good for first launch / development)
python3 main.py --windowed

# Specific window size
python3 main.py --windowed --width 1920 --height 1080

# Without the control panel (pure visuals)
python3 main.py --no-controls

# Specific audio device (check the Audio Input dropdown in the control panel)
python3 main.py --device 2
```

Once running:
- The **fullscreen canvas** shows the animated visuals.
- The **control panel** pops up as a separate window (stays on top).
- Press **H** to show/hide the heads-up display with live stats.
- Press **ESC** to quit.

---

## Command-line flags

| Flag | Default | Description |
|------|---------|-------------|
| `--windowed` | off | Run in a resizable window instead of fullscreen |
| `--width W` | 1280 | Window width (windowed mode only) |
| `--height H` | 720 | Window height (windowed mode only) |
| `--device N` | system default | PyAudio input device index |
| `--no-controls` | off | Suppress the Tkinter control panel |

---

## Keyboard shortcuts

These work at any time while the visualiser window is focused.

| Key | Action |
|-----|--------|
| `ESC` | Quit |
| `F` | Toggle fullscreen / windowed |
| `H` | Toggle the HUD (heads-up display) |
| `1` | Toggle **plasma** background layer |
| `2` | Toggle **waveform ring** layer |
| `3` | Toggle **particle** layer |
| `4` | Toggle **spectrum bars** layer |
| `P` | Cycle to the next colour palette |
| `O` | Toggle image outline on / off |
| `S` | Cycle to the next symmetry mode (requires an image to be loaded) |
| `↑` / `↓` | Intensity +0.1 / −0.1 |
| `←` / `→` | Speed −0.1 / +0.1 |

---

## Control panel

The panel is a scrollable dark-themed Tkinter window.  All changes take
effect immediately — there is no "Apply" button.  You can scroll the panel
with the mouse wheel if your screen is short.

### Animation section

| Slider | Range | Effect |
|--------|-------|--------|
| **Speed** | 0.1 – 4.0 | Multiplies the master time step.  Higher = faster plasma, quicker particle movement. |
| **Intensity** | 0.0 – 3.0 | Scales all audio-reactive amplitudes: how much the visuals respond to the beat and volume. |

### Color Palette section

Choose one of six palettes.  The selected palette affects **all** visual
layers simultaneously, including the image tint and outline colour.

| Palette | Character |
|---------|-----------|
| **Rainbow** | Full-spectrum HSV cycle — always vibrant |
| **Inferno** | Dark reds → orange → bright yellow |
| **Ocean** | Deep blue-cyan-aqua gradients |
| **Neon** | Hot pink → purple → electric blue |
| **Forest** | Muted greens shifting to lime |
| **Sunset** | Warm orange-red-amber tones |

### Layers section

Four independent render layers can be toggled on or off independently:

- **Plasma background** — the animated sine-wave colour field
- **Waveform ring** — the radial FFT ring in the centre
- **Particles** — beat-spawned sparks that arc outward
- **Spectrum bars** — six frequency-band bars at the bottom

Disabling layers you don't need improves frame rate on slower hardware.

### Image Overlay section

**Load Image …** opens a file picker.  The image is processed immediately in
the background (symmetry + edge detection) and appears centred on screen
on the next frame.

**Clear** removes the overlay.

The supported format list and resolution note displayed in the panel are
informational — see [Supported formats & resolutions](#supported-formats--resolutions) below.

### Image Transforms section

This section controls the two image-processing pipelines that run whenever
you load an image or change these settings.

#### Symmetry

Dropdown with six modes.  A short description of the selected mode appears
below the dropdown automatically.  Changing the mode re-processes the image
immediately.

| Mode | What it does |
|------|-------------|
| **None** | Original image — no transformation |
| **Mirror H** | Left half is reflected to fill the right; result is symmetric about the vertical centre line |
| **Mirror V** | Top half is reflected downward; result is symmetric about the horizontal centre line |
| **4-Way** | Top-left quadrant is reflected into all four quadrants, creating a Rorschach / mandala pattern |
| **Kaleidoscope 4** | 4-segment polar kaleidoscope (90° wedge, mirrored and tiled around the centre) |
| **Kaleidoscope 8** | Classic 8-segment stained-glass / crystal kaleidoscope using polar coordinate folding |

See [Symmetry modes](#symmetry-modes) for a detailed explanation.

#### Outline

| Control | Description |
|---------|-------------|
| **Enable outline** | Turns on the Sobel edge-detection overlay |
| **Glow** | Applies a two-pass Gaussian blur for a soft glow halo around each edge |
| **Strength** (0 – 3) | Scales the edge alpha channel — higher = more visible, thicker-looking edges |

The outline colour automatically follows the active palette and is shifted
by mid-band frequency energy so it drifts in hue as the music changes.  On
every detected beat the outline briefly brightens by up to 2× for a flash
effect.

### Audio Input section

Shows a dropdown of all detected PyAudio input devices.  Select a device to
switch the capture stream without restarting the app.  The dropdown is
populated a moment after the control panel opens.

---

## Visual layers in detail

### Plasma background

A 160 × 90 pixel sine-wave plasma rendered in the active palette and
upscaled with smooth interpolation.  The wave frequencies are driven by bass
energy (warping the radial component) and mid energy (adding a secondary
horizontal wave).  The hue drifts continuously at a rate proportional to
Speed.

### Waveform ring

The first 256 FFT bins are mapped around a circle centred on screen.  Each
bin's magnitude pushes that point's radius outward from a base radius of 22 %
of the shorter screen dimension.  On a beat, the entire ring scales outward
(beat-scale pulse) and snaps back over ~125 ms.  The ring is drawn as a
filled band between an inner arc and the FFT-modulated outer arc, plus a
bright line along the outer edge.

### Particle system

Up to 800 simultaneous particles, spawned in bursts on every detected beat.
Each burst size scales with `beat_strength × intensity`.  Particles:
- Radiate outward from the screen centre at randomised angles and speeds
- Experience downward gravity (proportional to Intensity)
- Fade out over a randomised lifetime (0.5 – 2 s)
- Shrink proportionally as they fade

Particle hues are sampled from the current palette hue offset at spawn time,
with a small random jitter for variety.

### Spectrum bars

Six bars corresponding to the six frequency bands analysed by the audio
engine:

| Band | Frequency range |
|------|----------------|
| Sub-bass | 20 – 60 Hz |
| Bass | 60 – 250 Hz |
| Low-mid | 250 – 500 Hz |
| Mid | 500 – 2 000 Hz |
| High | 2 000 – 8 000 Hz |
| Air | 8 000 – 20 000 Hz |

Bar height = `band_energy × Intensity × 25 % of screen height`.  Each bar
has a lighter glow cap at its top for depth.

### Beat flash

On each detected beat a full-screen coloured overlay is briefly drawn with
alpha proportional to `beat_strength × 0.8`.  It decays in ~330 ms.  The
colour is the palette hue opposite (hue + 0.5) to the current drift hue,
creating a complementary flash.

---

## Image overlay in detail

### Supported formats & resolutions

Pillow (PIL) is used for all image loading, so any format Pillow can open
works: **PNG, JPEG, WEBP, GIF (first frame), BMP, TIFF, ICO, PPM, PGM** and
more.

Resolution is handled automatically:

1. The raw image is opened and **downscaled to at most 1024 px on the long
   edge** using LANCZOS resampling, preserving aspect ratio.  This is the
   working resolution used for symmetry transforms and edge detection.
   *Upsampling is never done here — tiny images stay small.*

2. After symmetry is applied, the result is **scaled to fit 90 % of the
   display** using LANCZOS, again preserving aspect ratio.

3. This fitted image is stored as a pygame Surface.  **Every frame** the
   surface is scaled by a small factor (`1.0 + beat_pulse`) to create the
   breathing effect.

There is no hard upper limit on the input resolution — a 20 MP photograph
will simply be downscaled cleanly before processing.  Kaleidoscope modes
centre-crop to square first, so very wide panoramas or tall portrait images
will lose the sides/top-bottom respectively.

### Symmetry modes

#### None
The image is displayed as-is (after aspect-ratio scaling).

#### Mirror H — horizontal mirror
```
Before:   After:
A | B     A | A'
C | D     C | C'
```
The left half of the working image is copied and flipped horizontally, then
pasted onto the right half.  The result is perfectly symmetric about the
vertical centre line.  Works best with images that have an interesting
left side.

#### Mirror V — vertical mirror
The top half is flipped downward.  Symmetric about the horizontal axis.
Good for landscapes or any image where the top half has character.

#### 4-Way — quadrant mirror (mandala)
```
TL | TR       Q | Q'
---+---  →   ---+---
BL | BR      Q↓ | Q'↓
```
The top-left quadrant `Q` is reflected into three copies:
- `Q'`  = Q flipped left-right  (top-right)
- `Q↓`  = Q flipped top-bottom  (bottom-left)
- `Q'↓` = Q flipped both axes   (bottom-right)

Creates a Rorschach / mandala / rug-tile pattern.  Works best with
photographs that have varied texture in the top-left area.

#### Kaleidoscope 4 — 4-segment polar kaleidoscope
The image is centre-cropped to a square.  A 90° pie-slice is extracted from
the source and reflected within itself so it tiles perfectly when rotated four
times around the centre.

Technical detail: every output pixel `(x, y)` is converted to polar
coordinates `(r, θ)`.  `θ` is folded into `[0°, 45°]` by mirroring within
each 90° segment.  The source pixel at the folded `(r, θ)` in Cartesian
space is sampled from the original image.

#### Kaleidoscope 8 — 8-segment polar kaleidoscope (classic)
Same polar-folding algorithm as above, but with 8 segments of 45° each,
folded into `[0°, 22.5°]`.  This is the archetypal stained-glass / crystal
kaleidoscope look.  For the best effect, use photographs with strong colour
contrast and interesting detail near the centre.

**Tip**: images of flowers, mandalas, circuit boards, fabric patterns, and
macro photography work beautifully.  Try different source images — the
kaleidoscope amplifies whatever textures and colours exist in the corner
nearest the crop centre.

### Outline / edge detection

When **Enable outline** is ticked, a Sobel-gradient edge map is computed from
the luminance channel of the (symmetry-applied, screen-fitted) image.

**Pipeline:**

1. Convert image to greyscale (L mode).
2. Compute horizontal and vertical Sobel derivatives using
   `scipy.ndimage.sobel`.
3. Calculate gradient magnitude: `√(Gx² + Gy²)`.
4. Contrast-stretch so the maximum edge = 255; store as `uint8`.

At render time each frame:

1. Resize the stored edge map to the current (beat-pulsed) display size.
2. Determine outline colour from the current palette at hue offset `+0.5 +
   mid_band_energy × 0.25`.
3. Build an RGBA image: uniform RGB = outline colour, alpha = edge magnitude
   × Strength × beat_boost.
4. If **Glow** is on, composite two Gaussian blurs (radii 4 and 1 px) for a
   soft halo under a crisp edge line.
5. Convert to a pygame surface and blit over the image.

Result: a glowing neon contour that traces every edge in the image, shifts
colour with the music, and flashes brighter on beats.

---

## Audio analysis explained

The audio engine (`audio.py`) opens a PyAudio stream at 44 100 Hz, 1 channel,
float32.  A rolling 2 048-sample window is maintained.

**FFT**: A Hanning-windowed FFT (zero-padded to 2 048 points) is computed
each chunk (~23 ms latency at 1 024-frame chunks).

**Band energy**: The mean FFT magnitude in each of the six frequency bands is
computed.  Per-band running maxima are tracked with slow exponential decay
(`max × 0.9995` per chunk) so the display adapts to quiet and loud sources
without clipping.  A further exponential moving average (α = 0.3) smooths the
display values to prevent flickering.

**Beat detection**: The instantaneous bass-band energy is compared to the mean
of the previous ~1 second of bass energy (43 chunks).  A beat is declared
when the instantaneous energy exceeds `mean × 1.35` and the overall RMS
volume is above 0.02 (to suppress false positives during silence).
`beat_strength` is `(instant − mean) / mean`, clamped to [0, 1].

**Volume**: RMS of the current 2 048-sample window, normalised by a running
maximum with the same slow-decay mechanism.

---

## Setting up your audio source

### Microphone (simplest)

Just run the app.  PyAudio will use the system-default input device, which is
usually your built-in microphone or the one selected in your OS sound
settings.

### Line-in / audio interface

Connect the source to your line-in or USB audio interface.  Open your OS
audio settings and set that device as the default input **before** starting
chooon-viz, or use the **Audio Input** dropdown in the control panel to switch
mid-session.

### Routing desktop audio (virtual cable)

To visualise music playing from Spotify, YouTube, etc.:

- **Linux**: Use a loopback ALSA device, PulseAudio monitor source, or
  PipeWire loopback.  In pavucontrol set the recording source to the monitor
  of your output.  The device will appear in the Audio Input dropdown.

- **macOS**: Install **BlackHole** (free) or **Soundflower**.  Route app
  audio through the virtual device and select it in chooon-viz.

- **Windows**: Use **VB-Cable** (free) or enable "Stereo Mix" in your sound
  card driver.  Set it as the recording device.

---

## Performance tips

| Symptom | Suggested fix |
|---------|--------------|
| Low FPS (< 30) with plasma | Reduce `--width / --height`, or toggle off the plasma layer (key `1`) |
| Outline causes lag | Lower Outline Strength, disable Glow, or use smaller images |
| Kaleidoscope 8 is slow to apply | It runs once on load — subsequent frames are fast.  Wait a moment after loading |
| Too many particles | Lower Intensity slider |
| Audio latency feels high | This is inherent to 44 100 / 1 024-chunk streaming; the visuals lag the audio by ~23 ms which is imperceptible |

The plasma layer is the most CPU-intensive because it evaluates sine functions
per pixel (even at 160 × 90).  On a modern CPU it costs ~3–6 ms per frame.
The kaleidoscope preprocessing is a one-time numpy operation at load time
(~50–300 ms depending on image size) — not per-frame.

---

## Troubleshooting

### "Could not open input stream"
- No microphone or input device detected.
- Check your OS audio settings and ensure an input device is selected and
  not muted.
- Try specifying a device index explicitly: `python main.py --device 0`.

### Nothing happens / visuals don't react to audio
- The audio source may be silent or very quiet.  Enable the HUD (`H`) and
  watch **Volume** — it should move when audio plays.
- Check that the correct input device is selected in the control panel.
- On Linux with PulseAudio: ensure the app is recording from the right source
  in `pavucontrol`.

### Image appears blank or not visible
- The image may have a transparent alpha channel.  Try a JPEG or a PNG
  without transparency.
- Check the terminal for a `[Visualizer]` error message with the file path.

### Control panel does not appear
- It opens in a separate thread a fraction of a second after the main window.
  If it still doesn't appear after 2–3 s, run with `--no-controls` to
  verify the visualiser itself works, then file a bug.
- On some Linux desktops the panel may open behind the fullscreen window.
  Run `--windowed` to avoid this.

### `ImportError: No module named 'pyaudio'`
- Install the portaudio system library first, then reinstall pyaudio.
  See [Installation](#installation).

### `ModuleNotFoundError: No module named '_tkinter'`

The control panel uses Tkinter, which Homebrew's `python@3.13` does not
include by default.  Fix — install the Tk package and restart the app:

```bash
brew install python-tk@3.13
python3 main.py --windowed
```

No need to recreate the venv; Homebrew drops the `_tkinter` extension directly
into the Python 3.13 installation that your venv links back to.

### `ModuleNotFoundError: No module named 'pygame'`
- Run `pip install -r requirements.txt` inside the correct virtual
  environment (confirm the venv is active — your prompt should start with
  `(.venv)`).
- If pygame failed to build during `pip install`, see the SDL.h entry below.

### `fatal error: 'SDL.h' file not found` / pygame build failure

This almost always means **Python 3.14** is being used.  pygame 2.6.x has no
pre-built wheel for Python 3.14 and the source build requires SDL2 headers
that aren't readily available.

Fix — switch to Python 3.13:

```bash
# Install Python 3.13 via Homebrew (macOS)
brew install python@3.13

# Remove the broken venv and recreate with 3.13
deactivate
rm -rf .venv
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py --windowed
```

Verify the right Python is active before installing:
```bash
python3 --version   # should print 3.13.x, not 3.14.x
```

### `-bash: cd: chooon-viz: No such file or directory`
- The repo name has **three o's**: `chooon-viz`.  Double-check the folder
  name with `ls` and use `cd chooon-viz` (three o's).

---

## Technical reference

### File overview

| File | Role |
|------|------|
| `main.py` | Entry point: pygame loop, event routing, CLI args, HUD |
| `audio.py` | PyAudio capture thread, FFT analysis, beat detection |
| `visuals.py` | Pygame renderer: all drawing code + image pipeline |
| `controls.py` | Tkinter control panel in a background thread |
| `requirements.txt` | Python dependency list |

### params dict — all keys

The `params` dict is the shared state between the control panel thread and the
render thread.  All values are written atomically by the GIL.

| Key | Type | Default | Set by |
|-----|------|---------|--------|
| `speed` | float | 1.0 | Slider |
| `intensity` | float | 1.0 | Slider |
| `palette` | str | `"Rainbow"` | Dropdown |
| `show_plasma` | bool | True | Checkbox |
| `show_waveform` | bool | True | Checkbox |
| `show_particles` | bool | True | Checkbox |
| `show_spectrum` | bool | True | Checkbox |
| `symmetry_mode` | str | `"None"` | Dropdown / `S` key |
| `outline_enabled` | bool | False | Checkbox / `O` key |
| `outline_strength` | float | 1.0 | Slider |
| `outline_glow` | bool | True | Checkbox |
| `show_hud` | bool | False | `H` key |

### events queue — all event types

| `type` | Payload | Effect |
|--------|---------|--------|
| `"load_image"` | `path: str` | `vis.load_image(path)` |
| `"clear_image"` | — | `vis.clear_image()` |
| `"rebuild_overlay"` | — | `vis.rebuild_overlay()` |
| `"set_device"` | `index: int\|None` | Restarts AudioAnalyzer on new device |
| `"quit"` | — | Exits the main loop |

### AudioData fields

| Field | Type | Description |
|-------|------|-------------|
| `raw_fft` | `np.ndarray[float32]` | Normalised FFT magnitudes, length = FFT_SIZE // 2 |
| `band_energy` | `np.ndarray[float32]` | Smoothed per-band energy, shape (6,), range [0, 1] |
| `beat` | `bool` | True if a beat was detected this chunk |
| `beat_strength` | `float` | [0, 1] relative beat intensity |
| `volume` | `float` | [0, 1] normalised RMS volume |
| `dominant_freq` | `float` | Hz of the loudest FFT bin |
