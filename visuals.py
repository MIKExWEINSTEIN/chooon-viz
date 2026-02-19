"""
visuals.py - Fullscreen animated visual renderer for chooon-viz.

Draws several layered effects driven by AudioData:
  • Radial waveform ring
  • Particle field (beat-spawned)
  • FFT bar spectrum
  • Plasma background
  • Loaded image overlay (alpha-reacts to volume/beat)

All rendering happens on the pygame surface passed in; the caller owns the
display.
"""

from __future__ import annotations
import math
import random
import colorsys
import numpy as np
import pygame
from pygame import Surface, Color
from PIL import Image
from typing import Optional

from audio import AudioData, BANDS


# ── helpers ──────────────────────────────────────────────────────────────────

def _hsv_surf(h: float, s: float, v: float, alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (int(r * 255), int(g * 255), int(b * 255), alpha)


def _lerp(a, b, t):
    return a + (b - a) * t


# ── colour palettes ───────────────────────────────────────────────────────────

PALETTES = {
    "Rainbow":   lambda h: (h, 1.0, 1.0),          # hue cycles continuously
    "Inferno":   lambda h: (0.05 + h * 0.1, 1.0, min(1.0, h * 2.0)),
    "Ocean":     lambda h: (0.55 + h * 0.1, 0.8 + h * 0.2, 0.5 + h * 0.5),
    "Neon":      lambda h: (0.75 + h * 0.5, 1.0, 1.0),
    "Forest":    lambda h: (0.3 + h * 0.15, 0.7, 0.3 + h * 0.7),
    "Sunset":    lambda h: (0.02 + h * 0.12, 0.9, 0.9),
}
PALETTE_NAMES = list(PALETTES.keys())


# ── particle system ───────────────────────────────────────────────────────────

class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size", "hue", "alpha")

    def __init__(self, x, y, vx, vy, life, size, hue):
        self.x        = x
        self.y        = y
        self.vx       = vx
        self.vy       = vy
        self.life     = life
        self.max_life = life
        self.size     = size
        self.hue      = hue
        self.alpha    = 255

    def update(self, dt: float, gravity: float = 0.0):
        self.x    += self.vx * dt
        self.y    += self.vy * dt
        self.vy   += gravity * dt
        self.life -= dt
        frac       = max(self.life / self.max_life, 0.0)
        self.alpha = int(frac * 255)

    @property
    def alive(self):
        return self.life > 0


# ── main renderer ─────────────────────────────────────────────────────────────

class Visualizer:
    """
    Renders audio-reactive visuals onto a pygame Surface each frame.

    Parameters
    ----------
    surface : pygame.Surface
        The display surface (typically the fullscreen display).
    params  : dict
        Shared dict updated by the control panel; keys:
          speed, intensity, palette, show_waveform, show_particles,
          show_spectrum, show_plasma
    """

    MAX_PARTICLES = 800

    def __init__(self, surface: Surface, params: dict):
        self.surface  = surface
        self.params   = params
        self.W, self.H = surface.get_size()
        self.cx, self.cy = self.W // 2, self.H // 2

        self._t         = 0.0          # master time accumulator
        self._hue       = 0.0          # colour hue offset
        self._beat_flash= 0.0          # beat-flash intensity (decays)
        self._beat_scale= 1.0          # beat pulse scale
        self._particles : list[Particle] = []
        self._overlay   : Optional[Surface] = None
        self._overlay_path : Optional[str] = None

        # Pre-allocate plasma buffer (low-res, then scale up)
        self._plasma_w = 160
        self._plasma_h = 90
        self._plasma_surf = pygame.Surface((self._plasma_w, self._plasma_h))

        # Off-screen for glow blur
        self._glow_surf = pygame.Surface((self.W, self.H), pygame.SRCALPHA)

        # Smoothed FFT for waveform ring
        self._smooth_fft = np.zeros(256, dtype=np.float32)

        # Beat flash overlay surface
        self._flash_surf = pygame.Surface((self.W, self.H), pygame.SRCALPHA)

    # ── public ───────────────────────────────────────────────────────────────

    def load_image(self, path: str):
        """Load an image file to use as an overlay."""
        try:
            pil_img = Image.open(path).convert("RGBA")
            # Scale to fit inside display while preserving aspect ratio
            img_w, img_h = pil_img.size
            scale = min(self.W / img_w, self.H / img_h) * 0.9
            new_w = max(1, int(img_w * scale))
            new_h = max(1, int(img_h * scale))
            pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
            raw = pil_img.tobytes()
            self._overlay = pygame.image.fromstring(raw, (new_w, new_h), "RGBA").convert_alpha()
            self._overlay_path = path
        except Exception as exc:
            print(f"[Visualizer] Could not load image '{path}': {exc}")
            self._overlay = None

    def clear_image(self):
        self._overlay = None
        self._overlay_path = None

    def update(self, audio: AudioData, dt: float):
        """Advance the simulation by dt seconds using audio data."""
        speed     = float(self.params.get("speed",     1.0))
        intensity = float(self.params.get("intensity", 1.0))

        self._t   += dt * speed
        self._hue += dt * speed * 0.08

        # Beat reactions
        if audio.beat:
            strength = audio.beat_strength * intensity
            self._beat_flash = min(1.0, self._beat_flash + strength * 0.8)
            self._beat_scale = 1.0 + strength * 0.25
            self._spawn_particles(audio, intensity)

        # Decay beat effects
        self._beat_flash = max(0.0, self._beat_flash - dt * 3.0)
        self._beat_scale = _lerp(self._beat_scale, 1.0, dt * 8.0)

        # Smooth FFT (use first 256 bins)
        fft_slice = audio.raw_fft[:256]
        if len(fft_slice) < 256:
            fft_slice = np.pad(fft_slice, (0, 256 - len(fft_slice)))
        self._smooth_fft = 0.6 * self._smooth_fft + 0.4 * fft_slice

        # Age particles
        for p in self._particles:
            p.update(dt * speed, gravity=60.0 * intensity)
        self._particles = [p for p in self._particles if p.alive]

    def draw(self, audio: AudioData):
        """Render everything onto self.surface."""
        # ── background ──────────────────────────────────────────────────────
        self.surface.fill((0, 0, 0))

        show_plasma    = self.params.get("show_plasma",    True)
        show_waveform  = self.params.get("show_waveform",  True)
        show_particles = self.params.get("show_particles", True)
        show_spectrum  = self.params.get("show_spectrum",  True)

        if show_plasma:
            self._draw_plasma(audio)
        if show_waveform:
            self._draw_waveform_ring(audio)
        if show_particles:
            self._draw_particles()
        if show_spectrum:
            self._draw_spectrum(audio)
        self._draw_beat_flash()
        if self._overlay is not None:
            self._draw_overlay(audio)

    # ── private drawing routines ─────────────────────────────────────────────

    def _palette_color(self, h: float, s: float = 1.0, v: float = 1.0, alpha: int = 255):
        name = self.params.get("palette", "Rainbow")
        fn   = PALETTES.get(name, PALETTES["Rainbow"])
        ph, ps, pv = fn(h)
        # Allow caller to modulate saturation / value
        r, g, b = colorsys.hsv_to_rgb(ph % 1.0, ps * s, pv * v)
        return (int(r * 255), int(g * 255), int(b * 255), alpha)

    # ── plasma ───────────────────────────────────────────────────────────────

    def _draw_plasma(self, audio: AudioData):
        pw, ph = self._plasma_w, self._plasma_h
        intensity = float(self.params.get("intensity", 1.0))

        # Sub-sample grid
        xs = np.linspace(0, 2 * math.pi, pw)
        ys = np.linspace(0, 2 * math.pi, ph)
        xg, yg = np.meshgrid(xs, ys)

        t    = self._t * 0.5
        bass = float(audio.band_energy[1]) * intensity
        mid  = float(audio.band_energy[3]) * intensity

        v = (np.sin(xg + t)
             + np.sin(yg + t * 0.7)
             + np.sin((xg + yg) * 0.5 + t * 1.3)
             + np.sin(np.sqrt(xg ** 2 + yg ** 2 + 0.5) * (1.0 + bass) + t)
             + mid * np.sin(xg * 3 + t * 2))

        v = (v - v.min()) / (v.max() - v.min() + 1e-9)  # normalise 0..1

        hue_offset = self._hue
        pixel_array = np.zeros((ph, pw, 3), dtype=np.uint8)
        for i in range(ph):
            for j in range(pw):
                h = (v[i, j] + hue_offset) % 1.0
                col = self._palette_color(h, v=0.5 + v[i, j] * 0.5)
                pixel_array[i, j] = col[:3]

        pygame.surfarray.blit_array(
            self._plasma_surf,
            np.transpose(pixel_array, (1, 0, 2))
        )
        scaled = pygame.transform.smoothscale(self._plasma_surf, (self.W, self.H))
        self.surface.blit(scaled, (0, 0))

    # ── waveform ring ─────────────────────────────────────────────────────────

    def _draw_waveform_ring(self, audio: AudioData):
        intensity  = float(self.params.get("intensity", 1.0))
        n          = 256
        base_r     = min(self.W, self.H) * 0.22
        fft        = self._smooth_fft
        beat_r     = base_r * self._beat_scale

        points_outer = []
        points_inner = []

        for i in range(n):
            angle  = (2 * math.pi * i / n) - math.pi / 2
            mag    = float(fft[i]) * intensity * base_r * 0.6
            r_out  = beat_r + mag
            r_in   = beat_r * 0.85

            ox = self.cx + math.cos(angle) * r_out
            oy = self.cy + math.sin(angle) * r_out
            ix = self.cx + math.cos(angle) * r_in
            iy = self.cy + math.sin(angle) * r_in

            points_outer.append((ox, oy))
            points_inner.append((ix, iy))

        # Draw filled polygon between inner and outer rings
        combined = points_outer + list(reversed(points_inner))
        if len(combined) >= 3:
            hue = (self._hue + audio.volume * 0.3) % 1.0
            col = self._palette_color(hue, alpha=200)
            s = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            pygame.draw.polygon(s, col, combined)
            self.surface.blit(s, (0, 0))

        # Bright outer ring line
        if len(points_outer) >= 2:
            col2 = self._palette_color((self._hue + 0.5) % 1.0, alpha=220)
            pygame.draw.lines(self.surface, col2[:3], True, [(int(x), int(y)) for x, y in points_outer], 2)

    # ── particles ────────────────────────────────────────────────────────────

    def _spawn_particles(self, audio: AudioData, intensity: float):
        count = int(10 + 30 * audio.beat_strength * intensity)
        count = min(count, self.MAX_PARTICLES - len(self._particles))
        hue   = self._hue

        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(80, 300) * (0.5 + intensity * 0.5)
            life  = random.uniform(0.5, 2.0)
            size  = random.uniform(2, 6 + audio.beat_strength * 8)
            self._particles.append(Particle(
                x    = self.cx + random.uniform(-20, 20),
                y    = self.cy + random.uniform(-20, 20),
                vx   = math.cos(angle) * speed,
                vy   = math.sin(angle) * speed - 60,
                life = life,
                size = size,
                hue  = (hue + random.uniform(-0.1, 0.1)) % 1.0,
            ))

    def _draw_particles(self):
        for p in self._particles:
            col = self._palette_color(p.hue, alpha=p.alpha)
            s   = pygame.Surface((int(p.size * 2 + 2), int(p.size * 2 + 2)), pygame.SRCALPHA)
            pygame.draw.circle(s, col, (int(p.size + 1), int(p.size + 1)), max(1, int(p.size)))
            self.surface.blit(s, (int(p.x - p.size), int(p.y - p.size)))

    # ── spectrum bars ─────────────────────────────────────────────────────────

    def _draw_spectrum(self, audio: AudioData):
        n          = len(BANDS)
        intensity  = float(self.params.get("intensity", 1.0))
        bar_margin = 0.02
        total_w    = self.W * 0.8
        bar_w      = total_w / n * (1 - bar_margin)
        gap        = total_w / n * bar_margin
        x_start    = (self.W - total_w) / 2
        max_h      = self.H * 0.25

        for i, energy in enumerate(audio.band_energy):
            bar_h = max(4, int(energy * max_h * intensity))
            x     = int(x_start + i * (bar_w + gap))
            y     = self.H - bar_h - 4

            hue = (self._hue + i / n * 0.4) % 1.0
            col = self._palette_color(hue, v=0.7 + energy * 0.3)

            # Main bar
            rect = pygame.Rect(x, y, int(bar_w), bar_h)
            pygame.draw.rect(self.surface, col[:3], rect, border_radius=4)

            # Glow highlight (lighter top strip)
            glow_h = max(2, bar_h // 6)
            glow   = pygame.Surface((int(bar_w), glow_h), pygame.SRCALPHA)
            glow.fill((*col[:3], 180))
            self.surface.blit(glow, (x, y))

    # ── beat flash ───────────────────────────────────────────────────────────

    def _draw_beat_flash(self):
        if self._beat_flash < 0.01:
            return
        alpha = int(self._beat_flash * 60)
        hue   = (self._hue + 0.5) % 1.0
        col   = self._palette_color(hue, alpha=alpha)
        self._flash_surf.fill(col)
        self.surface.blit(self._flash_surf, (0, 0))

    # ── image overlay ─────────────────────────────────────────────────────────

    def _draw_overlay(self, audio: AudioData):
        intensity = float(self.params.get("intensity", 1.0))

        # Scale pulsing with beat/volume
        base_scale = 1.0
        pulse      = audio.volume * 0.15 * intensity + self._beat_scale * 0.05
        scale      = base_scale + pulse

        ow = int(self._overlay.get_width()  * scale)
        oh = int(self._overlay.get_height() * scale)
        ow = max(1, ow)
        oh = max(1, oh)

        scaled_img = pygame.transform.smoothscale(self._overlay, (ow, oh))

        # Alpha modulated by volume
        alpha = int(np.clip(160 + audio.volume * 95 * intensity, 80, 255))
        scaled_img.set_alpha(alpha)

        # Apply a colour tint from current palette
        tint_surf = pygame.Surface((ow, oh), pygame.SRCALPHA)
        hue = (self._hue + audio.band_energy[1] * 0.3) % 1.0
        tint_col = self._palette_color(hue, s=0.4, v=1.0, alpha=60)
        tint_surf.fill(tint_col)

        blended = scaled_img.copy()
        blended.blit(tint_surf, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

        x = (self.W - ow) // 2
        y = (self.H - oh) // 2
        self.surface.blit(blended, (x, y))
