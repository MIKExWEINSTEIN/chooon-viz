#!/usr/bin/env python3
"""
main.py - chooon-viz entry point.

Launches:
  • PyAudio capture thread  (audio.py)
  • Tkinter control panel   (controls.py)
  • Pygame fullscreen render loop (visuals.py)

Usage
-----
    python main.py [--windowed] [--width W] [--height H] [--device N]

Flags
-----
  --windowed        Run in a window instead of fullscreen.
  --width  W        Window width  (default 1280, only used with --windowed).
  --height H        Window height (default 720,  only used with --windowed).
  --device N        PyAudio device index to use (default: system default).
  --no-controls     Don't open the control panel.
"""

import argparse
import queue
import sys
import time

import pygame

from audio    import AudioAnalyzer
from controls import (ControlPanel, EVT_QUIT, EVT_LOAD_IMAGE,
                       EVT_CLEAR_IMAGE, EVT_REBUILD_OVERLAY)
from visuals  import Visualizer, PALETTE_NAMES


# ── defaults ─────────────────────────────────────────────────────────────────

DEFAULT_PARAMS = {
    # animation
    "speed":            1.0,
    "intensity":        1.0,
    "palette":          PALETTE_NAMES[0],
    # layers
    "show_plasma":      True,
    "show_waveform":    True,
    "show_particles":   True,
    "show_spectrum":    True,
    # image transforms
    "symmetry_mode":    "None",
    "outline_enabled":  False,
    "outline_strength": 1.0,
    "outline_glow":     True,
}

TARGET_FPS = 60


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="chooon-viz – audio reactive visuals")
    p.add_argument("--windowed",     action="store_true",
                   help="Run in a window instead of fullscreen")
    p.add_argument("--width",  type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--device", type=int, default=None,
                   help="PyAudio input device index")
    p.add_argument("--no-controls", action="store_true",
                   help="Disable the control panel")
    return p.parse_args()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    args   = parse_args()
    params = dict(DEFAULT_PARAMS)
    events : queue.Queue = queue.Queue()

    # ── pygame display ────────────────────────────────────────────────────────
    pygame.init()
    pygame.display.set_caption("chooon-viz")

    if args.windowed:
        flags  = pygame.RESIZABLE
        screen = pygame.display.set_mode((args.width, args.height), flags)
    else:
        flags  = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
        screen = pygame.display.set_mode((0, 0), flags)

    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()

    # ── audio ─────────────────────────────────────────────────────────────────
    analyzer = AudioAnalyzer(device_index=args.device)
    analyzer.start()

    # ── control panel ─────────────────────────────────────────────────────────
    panel: ControlPanel | None = None
    if not args.no_controls:
        panel = ControlPanel(params, events)
        panel.start()

        # Populate device list once the panel is up
        import threading
        def _populate():
            time.sleep(0.4)   # give tkinter a moment to initialise
            try:
                devices = analyzer.list_input_devices()
                if panel:
                    panel.set_devices(devices)
            except Exception:
                pass
        threading.Thread(target=_populate, daemon=True).start()

    # ── visualiser ────────────────────────────────────────────────────────────
    vis = Visualizer(screen, params)

    running  = True
    prev_t   = time.perf_counter()
    font     = pygame.font.SysFont("monospace", 14)

    while running:
        now = time.perf_counter()
        dt  = min(now - prev_t, 0.05)   # cap at 50 ms to avoid spiral
        prev_t = now

        # ── pygame events ────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_f:
                    pygame.display.toggle_fullscreen()
                elif event.key == pygame.K_1:
                    params["show_plasma"]    = not params["show_plasma"]
                elif event.key == pygame.K_2:
                    params["show_waveform"]  = not params["show_waveform"]
                elif event.key == pygame.K_3:
                    params["show_particles"] = not params["show_particles"]
                elif event.key == pygame.K_4:
                    params["show_spectrum"]  = not params["show_spectrum"]
                elif event.key == pygame.K_UP:
                    params["intensity"] = min(3.0, params["intensity"] + 0.1)
                elif event.key == pygame.K_DOWN:
                    params["intensity"] = max(0.0, params["intensity"] - 0.1)
                elif event.key == pygame.K_RIGHT:
                    params["speed"] = min(4.0, params["speed"] + 0.1)
                elif event.key == pygame.K_LEFT:
                    params["speed"] = max(0.1, params["speed"] - 0.1)
                elif event.key == pygame.K_p:
                    idx = PALETTE_NAMES.index(params["palette"])
                    params["palette"] = PALETTE_NAMES[(idx + 1) % len(PALETTE_NAMES)]
                elif event.key == pygame.K_h:
                    _toggle_help(params)
                elif event.key == pygame.K_o:
                    params["outline_enabled"] = not params.get("outline_enabled", False)
                elif event.key == pygame.K_s:
                    # cycle symmetry mode
                    from visuals import SYMMETRY_MODES
                    idx = SYMMETRY_MODES.index(params.get("symmetry_mode", "None"))
                    params["symmetry_mode"] = SYMMETRY_MODES[(idx + 1) % len(SYMMETRY_MODES)]
                    vis.rebuild_overlay()
            elif event.type == pygame.VIDEORESIZE:
                # Update visualiser surface reference on resize
                screen = pygame.display.get_surface()
                vis.surface = screen
                vis.W, vis.H = screen.get_size()
                vis.cx, vis.cy = vis.W // 2, vis.H // 2

        # ── control panel events ──────────────────────────────────────────────
        try:
            while True:
                ev = events.get_nowait()
                if ev["type"] == EVT_QUIT:
                    running = False
                elif ev["type"] == EVT_LOAD_IMAGE:
                    vis.load_image(ev["path"])
                elif ev["type"] == EVT_CLEAR_IMAGE:
                    vis.clear_image()
                elif ev["type"] == EVT_REBUILD_OVERLAY:
                    vis.rebuild_overlay()
                elif ev["type"] == "set_device":
                    idx = ev.get("index")
                    analyzer.stop()
                    analyzer = AudioAnalyzer(device_index=idx)
                    analyzer.start()
        except queue.Empty:
            pass

        # ── render ────────────────────────────────────────────────────────────
        audio = analyzer.get()
        vis.update(audio, dt)
        vis.draw(audio)

        # ── HUD overlay ───────────────────────────────────────────────────────
        if params.get("show_hud", False):
            _draw_hud(screen, font, params, audio, clock)

        pygame.display.flip()
        clock.tick(TARGET_FPS)

    # ── cleanup ───────────────────────────────────────────────────────────────
    analyzer.stop()
    if panel:
        panel.stop()
    pygame.quit()
    sys.exit(0)


# ── HUD helpers ───────────────────────────────────────────────────────────────

def _toggle_help(params: dict):
    params["show_hud"] = not params.get("show_hud", False)


def _draw_hud(surface, font, params, audio, clock):
    lines = [
        f"FPS:       {clock.get_fps():.0f}",
        f"Palette:   {params['palette']}",
        f"Speed:     {params['speed']:.1f}",
        f"Intensity: {params['intensity']:.1f}",
        f"Volume:    {audio.volume:.2f}",
        f"Beat:      {'●' if audio.beat else '○'}  ({audio.beat_strength:.2f})",
        f"Dom freq:  {audio.dominant_freq:.0f} Hz",
        f"Symmetry:  {params.get('symmetry_mode','None')}",
        f"Outline:   {'on' if params.get('outline_enabled') else 'off'}",
        "",
        "ESC quit  F fullscreen  H toggle HUD",
        "1-4 layers  P palette  O outline  S symmetry",
        "↑↓ intensity  ←→ speed",
    ]
    x, y = 12, 12
    for line in lines:
        shadow = font.render(line, True, (0, 0, 0))
        text   = font.render(line, True, (220, 220, 220))
        surface.blit(shadow, (x + 1, y + 1))
        surface.blit(text,   (x,     y))
        y += 18


if __name__ == "__main__":
    main()
