"""
visuals.py - Fullscreen animated visual renderer for chooon-viz.

Draws several layered effects driven by AudioData:
  • Plasma background
  • Radial waveform ring
  • Particle field (beat-spawned)
  • FFT bar spectrum
  • Loaded image overlay with:
      - Any-resolution smart scaling
      - 6 symmetry / kaleidoscope modes
      - Sobel edge detection with palette-coloured glow outline

All rendering happens on the pygame surface passed in; the caller owns the
display.
"""

from __future__ import annotations
import math
import random
import colorsys
from typing import Optional

import numpy as np
import pygame
from pygame import Surface
from PIL import Image, ImageFilter
from scipy.ndimage import sobel

from audio import AudioData, BANDS


# ── helpers ───────────────────────────────────────────────────────────────────

def _lerp(a, b, t):
    return a + (b - a) * t


# ── colour palettes ───────────────────────────────────────────────────────────

PALETTES = {
    "Rainbow": lambda h: (h,              1.0,               1.0),
    "Inferno": lambda h: (0.05 + h * 0.1, 1.0,               min(1.0, h * 2.0)),
    "Ocean":   lambda h: (0.55 + h * 0.1, 0.8 + h * 0.2,    0.5 + h * 0.5),
    "Neon":    lambda h: (0.75 + h * 0.5, 1.0,               1.0),
    "Forest":  lambda h: (0.30 + h * 0.15,0.7,               0.3 + h * 0.7),
    "Sunset":  lambda h: (0.02 + h * 0.12,0.9,               0.9),
}
PALETTE_NAMES = list(PALETTES.keys())

# ── symmetry modes ────────────────────────────────────────────────────────────

SYMMETRY_MODES = [
    "None",           # original image
    "Mirror H",       # left half reflected right  (vertical axis)
    "Mirror V",       # top half reflected down    (horizontal axis)
    "4-Way",          # top-left quadrant × 4
    "Kaleidoscope 4", # 4-segment polar kaleidoscope
    "Kaleidoscope 8", # 8-segment polar kaleidoscope (classic)
]

# Max pixel budget for internal processing (keeps numpy fast on any input res)
_MAX_PROCESS_PX = 1024


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

    Shared ``params`` dict keys
    ---------------------------
    speed            float  0.1–4.0   animation speed multiplier
    intensity        float  0.0–3.0   beat response strength
    palette          str              key in PALETTES
    show_plasma      bool
    show_waveform    bool
    show_particles   bool
    show_spectrum    bool
    symmetry_mode    str              key in SYMMETRY_MODES
    outline_enabled  bool
    outline_strength float  0.0–3.0
    outline_glow     bool
    """

    MAX_PARTICLES = 800

    def __init__(self, surface: Surface, params: dict):
        self.surface  = surface
        self.params   = params
        self.W, self.H = surface.get_size()
        self.cx, self.cy = self.W // 2, self.H // 2

        self._t          = 0.0
        self._hue        = 0.0
        self._beat_flash = 0.0
        self._beat_scale = 1.0
        self._particles: list[Particle] = []

        # Plasma low-res buffer
        self._plasma_w    = 160
        self._plasma_h    = 90
        self._plasma_surf = pygame.Surface((self._plasma_w, self._plasma_h))

        # Smoothed FFT for waveform ring
        self._smooth_fft = np.zeros(256, dtype=np.float32)

        # Beat-flash overlay
        self._flash_surf = pygame.Surface((self.W, self.H), pygame.SRCALPHA)

        # Image overlay state
        self._pil_original  : Optional[Image.Image] = None  # loaded, res-capped
        self._pil_symmetric : Optional[Image.Image] = None  # after symmetry
        self._edge_arr      : Optional[np.ndarray]  = None  # uint8 (h, w)
        self._overlay       : Optional[Surface]     = None  # pygame surface
        self._overlay_path  : Optional[str]         = None

    # ── public API ────────────────────────────────────────────────────────────

    def load_image(self, path: str):
        """Load an image of any resolution, cap it, store, and rebuild overlay."""
        try:
            pil = Image.open(path).convert("RGBA")

            # Smart resolution cap: keep quality up to _MAX_PROCESS_PX on
            # each axis without distorting the aspect ratio.
            w, h   = pil.size
            factor = min(1.0, _MAX_PROCESS_PX / max(w, h, 1))
            if factor < 1.0:
                pil = pil.resize(
                    (max(1, int(w * factor)), max(1, int(h * factor))),
                    Image.LANCZOS,
                )
            self._pil_original = pil
            self._overlay_path = path
            self._rebuild_overlay()
        except Exception as exc:
            print(f"[Visualizer] Could not load image '{path}': {exc}")
            self._clear_image_state()

    def clear_image(self):
        self._clear_image_state()

    def rebuild_overlay(self):
        """Re-apply symmetry + edge detection when transform params change."""
        if self._pil_original is not None:
            self._rebuild_overlay()

    def update(self, audio: AudioData, dt: float):
        """Advance simulation by dt seconds."""
        speed     = float(self.params.get("speed",     1.0))
        intensity = float(self.params.get("intensity", 1.0))

        self._t   += dt * speed
        self._hue += dt * speed * 0.08

        if audio.beat:
            s = audio.beat_strength * intensity
            self._beat_flash = min(1.0, self._beat_flash + s * 0.8)
            self._beat_scale = 1.0 + s * 0.25
            self._spawn_particles(audio, intensity)

        self._beat_flash = max(0.0, self._beat_flash - dt * 3.0)
        self._beat_scale = _lerp(self._beat_scale, 1.0, dt * 8.0)

        fft_slice = audio.raw_fft[:256]
        if len(fft_slice) < 256:
            fft_slice = np.pad(fft_slice, (0, 256 - len(fft_slice)))
        self._smooth_fft = 0.6 * self._smooth_fft + 0.4 * fft_slice

        for p in self._particles:
            p.update(dt * speed, gravity=60.0 * intensity)
        self._particles = [p for p in self._particles if p.alive]

    def draw(self, audio: AudioData):
        """Render all layers onto self.surface."""
        self.surface.fill((0, 0, 0))

        if self.params.get("show_plasma",    True):
            self._draw_plasma(audio)
        if self.params.get("show_waveform",  True):
            self._draw_waveform_ring(audio)
        if self.params.get("show_particles", True):
            self._draw_particles()
        if self.params.get("show_spectrum",  True):
            self._draw_spectrum(audio)

        self._draw_beat_flash()

        if self._overlay is not None:
            self._draw_overlay(audio)

    # ── palette ───────────────────────────────────────────────────────────────

    def _palette_color(self, h: float, s: float = 1.0, v: float = 1.0, alpha: int = 255):
        name = self.params.get("palette", "Rainbow")
        fn   = PALETTES.get(name, PALETTES["Rainbow"])
        ph, ps, pv = fn(h)
        r, g, b    = colorsys.hsv_to_rgb(ph % 1.0, ps * s, pv * v)
        return (int(r * 255), int(g * 255), int(b * 255), alpha)

    # ── plasma ────────────────────────────────────────────────────────────────

    def _draw_plasma(self, audio: AudioData):
        pw, ph    = self._plasma_w, self._plasma_h
        intensity = float(self.params.get("intensity", 1.0))

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
        v = (v - v.min()) / (v.max() - v.min() + 1e-9)

        hue_offset = self._hue
        px = np.zeros((ph, pw, 3), dtype=np.uint8)
        for i in range(ph):
            for j in range(pw):
                c = self._palette_color((v[i, j] + hue_offset) % 1.0,
                                        v=0.5 + v[i, j] * 0.5)
                px[i, j] = c[:3]

        pygame.surfarray.blit_array(self._plasma_surf, np.transpose(px, (1, 0, 2)))
        scaled = pygame.transform.smoothscale(self._plasma_surf, (self.W, self.H))
        self.surface.blit(scaled, (0, 0))

    # ── waveform ring ─────────────────────────────────────────────────────────

    def _draw_waveform_ring(self, audio: AudioData):
        intensity = float(self.params.get("intensity", 1.0))
        n         = 256
        base_r    = min(self.W, self.H) * 0.22
        beat_r    = base_r * self._beat_scale
        fft       = self._smooth_fft

        pts_outer, pts_inner = [], []
        for i in range(n):
            angle = (2 * math.pi * i / n) - math.pi / 2
            mag   = float(fft[i]) * intensity * base_r * 0.6
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            pts_outer.append((self.cx + cos_a * (beat_r + mag),
                               self.cy + sin_a * (beat_r + mag)))
            pts_inner.append((self.cx + cos_a * beat_r * 0.85,
                               self.cy + sin_a * beat_r * 0.85))

        combined = pts_outer + list(reversed(pts_inner))
        if len(combined) >= 3:
            hue = (self._hue + audio.volume * 0.3) % 1.0
            col = self._palette_color(hue, alpha=200)
            s   = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            pygame.draw.polygon(s, col, combined)
            self.surface.blit(s, (0, 0))

        if len(pts_outer) >= 2:
            col2 = self._palette_color((self._hue + 0.5) % 1.0, alpha=220)
            pygame.draw.lines(self.surface, col2[:3], True,
                              [(int(x), int(y)) for x, y in pts_outer], 2)

    # ── particles ─────────────────────────────────────────────────────────────

    def _spawn_particles(self, audio: AudioData, intensity: float):
        count = min(int(10 + 30 * audio.beat_strength * intensity),
                    self.MAX_PARTICLES - len(self._particles))
        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(80, 300) * (0.5 + intensity * 0.5)
            self._particles.append(Particle(
                x    = self.cx + random.uniform(-20, 20),
                y    = self.cy + random.uniform(-20, 20),
                vx   = math.cos(angle) * speed,
                vy   = math.sin(angle) * speed - 60,
                life = random.uniform(0.5, 2.0),
                size = random.uniform(2, 6 + audio.beat_strength * 8),
                hue  = (self._hue + random.uniform(-0.1, 0.1)) % 1.0,
            ))

    def _draw_particles(self):
        for p in self._particles:
            col = self._palette_color(p.hue, alpha=p.alpha)
            sz  = max(1, int(p.size))
            dim = sz * 2 + 2
            s   = pygame.Surface((dim, dim), pygame.SRCALPHA)
            pygame.draw.circle(s, col, (sz + 1, sz + 1), sz)
            self.surface.blit(s, (int(p.x - p.size), int(p.y - p.size)))

    # ── spectrum ──────────────────────────────────────────────────────────────

    def _draw_spectrum(self, audio: AudioData):
        n          = len(BANDS)
        intensity  = float(self.params.get("intensity", 1.0))
        total_w    = self.W * 0.8
        bar_w      = total_w / n * 0.98
        gap        = total_w / n * 0.02
        x_start    = (self.W - total_w) / 2
        max_h      = self.H * 0.25

        for i, energy in enumerate(audio.band_energy):
            bar_h = max(4, int(energy * max_h * intensity))
            x     = int(x_start + i * (bar_w + gap))
            y     = self.H - bar_h - 4
            hue   = (self._hue + i / n * 0.4) % 1.0
            col   = self._palette_color(hue, v=0.7 + energy * 0.3)

            pygame.draw.rect(self.surface, col[:3],
                             pygame.Rect(x, y, int(bar_w), bar_h), border_radius=4)

            glow_h = max(2, bar_h // 6)
            glow   = pygame.Surface((int(bar_w), glow_h), pygame.SRCALPHA)
            glow.fill((*col[:3], 180))
            self.surface.blit(glow, (x, y))

    # ── beat flash ────────────────────────────────────────────────────────────

    def _draw_beat_flash(self):
        if self._beat_flash < 0.01:
            return
        col = self._palette_color((self._hue + 0.5) % 1.0,
                                   alpha=int(self._beat_flash * 60))
        self._flash_surf.fill(col)
        self.surface.blit(self._flash_surf, (0, 0))

    # ── image overlay ─────────────────────────────────────────────────────────

    def _draw_overlay(self, audio: AudioData):
        intensity = float(self.params.get("intensity", 1.0))

        # Beat-reactive scale
        pulse = audio.volume * 0.12 * intensity + (self._beat_scale - 1.0) * 0.5
        scale = 1.0 + pulse

        ow = max(1, int(self._overlay.get_width()  * scale))
        oh = max(1, int(self._overlay.get_height() * scale))

        img_scaled = pygame.transform.smoothscale(self._overlay, (ow, oh))

        # Alpha modulated by volume
        alpha = int(np.clip(155 + audio.volume * 100 * intensity, 80, 255))
        img_scaled.set_alpha(alpha)

        # Palette tint
        tint = pygame.Surface((ow, oh), pygame.SRCALPHA)
        hue  = (self._hue + float(audio.band_energy[1]) * 0.3) % 1.0
        tint.fill(self._palette_color(hue, s=0.4, v=1.0, alpha=55))
        img_blended = img_scaled.copy()
        img_blended.blit(tint, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

        x = (self.W - ow) // 2
        y = (self.H - oh) // 2
        self.surface.blit(img_blended, (x, y))

        # Outline layer
        if self.params.get("outline_enabled", False) and self._edge_arr is not None:
            self._draw_outline(audio, x, y, ow, oh)

    def _draw_outline(self, audio: AudioData, ox: int, oy: int, ow: int, oh: int):
        """Draw a palette-coloured, glow-blurred Sobel edge outline."""
        strength = float(self.params.get("outline_strength", 1.0))
        glow     = bool(self.params.get("outline_glow", True))

        # Dynamic colour: pulses on beat, shifts with mid-band energy
        hue        = (self._hue + 0.5 + float(audio.band_energy[2]) * 0.25) % 1.0
        beat_boost = 1.0 + audio.beat_strength * 1.2
        col        = self._palette_color(hue)

        # Resize edge map to current display size
        h_src, w_src = self._edge_arr.shape
        edge_pil     = Image.fromarray(self._edge_arr, "L")
        edge_pil     = edge_pil.resize((ow, oh), Image.BILINEAR)
        edge_np      = np.array(edge_pil, dtype=np.float32)

        # Build RGBA: uniform colour, edge-driven alpha
        alpha_np = np.clip(edge_np * strength * beat_boost, 0, 255).astype(np.uint8)

        rgba = np.zeros((oh, ow, 4), dtype=np.uint8)
        rgba[:, :, 0] = col[0]
        rgba[:, :, 1] = col[1]
        rgba[:, :, 2] = col[2]
        rgba[:, :, 3] = alpha_np

        edge_pil_rgba = Image.fromarray(rgba, "RGBA")

        if glow:
            # Two passes: wider faint glow + crisp inner edge
            glow_wide = edge_pil_rgba.filter(ImageFilter.GaussianBlur(radius=4))
            glow_fine = edge_pil_rgba.filter(ImageFilter.GaussianBlur(radius=1))
            # Composite: wide glow under fine glow
            glow_combined = Image.alpha_composite(glow_wide, glow_fine)
            edge_pil_rgba = glow_combined

        raw       = edge_pil_rgba.tobytes()
        edge_surf = pygame.image.fromstring(raw, (ow, oh), "RGBA").convert_alpha()
        self.surface.blit(edge_surf, (ox, oy))

    # ── image pipeline: internal rebuild ─────────────────────────────────────

    def _clear_image_state(self):
        self._pil_original  = None
        self._pil_symmetric = None
        self._edge_arr      = None
        self._overlay       = None
        self._overlay_path  = None

    def _rebuild_overlay(self):
        """Re-run the full image → symmetry → edge → surface pipeline."""
        if self._pil_original is None:
            return

        # 1. Apply symmetry transform
        mode = self.params.get("symmetry_mode", "None")
        try:
            self._pil_symmetric = _apply_symmetry(self._pil_original, mode)
        except Exception as exc:
            print(f"[Visualizer] Symmetry error: {exc}")
            self._pil_symmetric = self._pil_original.copy()

        # 2. Scale to fit inside display (90 % of the screen dimension)
        img = self._pil_symmetric
        sw  = int(self.W * 0.9)
        sh  = int(self.H * 0.9)
        iw, ih = img.size
        scale   = min(sw / iw, sh / ih, 1.0)
        nw, nh  = max(1, int(iw * scale)), max(1, int(ih * scale))
        img_fit = img.resize((nw, nh), Image.LANCZOS)

        # 3. Compute edge map on the fit image
        self._edge_arr = _compute_edges(img_fit)

        # 4. Build pygame surface
        raw           = img_fit.tobytes()
        self._overlay = pygame.image.fromstring(raw, (nw, nh), "RGBA").convert_alpha()


# ── symmetry helpers (module-level, pure PIL/numpy) ───────────────────────────

def _apply_symmetry(img: Image.Image, mode: str) -> Image.Image:
    if mode == "None":
        return img.copy()
    elif mode == "Mirror H":
        return _sym_mirror_h(img)
    elif mode == "Mirror V":
        return _sym_mirror_v(img)
    elif mode == "4-Way":
        return _sym_4way(img)
    elif mode == "Kaleidoscope 4":
        return _sym_kaleidoscope(img, n=4)
    elif mode == "Kaleidoscope 8":
        return _sym_kaleidoscope(img, n=8)
    return img.copy()


def _sym_mirror_h(img: Image.Image) -> Image.Image:
    """Left half reflected to fill right — symmetric about the vertical axis."""
    w, h  = img.size
    left  = img.crop((0, 0, w // 2, h))
    right = left.transpose(Image.FLIP_LEFT_RIGHT)
    out   = Image.new("RGBA", (w, h))
    out.paste(left,  (0,      0))
    out.paste(right, (w // 2, 0))
    return out


def _sym_mirror_v(img: Image.Image) -> Image.Image:
    """Top half reflected downward — symmetric about the horizontal axis."""
    w, h   = img.size
    top    = img.crop((0, 0, w, h // 2))
    bottom = top.transpose(Image.FLIP_TOP_BOTTOM)
    out    = Image.new("RGBA", (w, h))
    out.paste(top,    (0, 0))
    out.paste(bottom, (0, h // 2))
    return out


def _sym_4way(img: Image.Image) -> Image.Image:
    """Top-left quadrant mirrored into all four quadrants (mandala-style)."""
    w, h  = img.size
    qw, qh = w // 2, h // 2

    q      = img.crop((0, 0, qw, qh))
    q_r    = q.transpose(Image.FLIP_LEFT_RIGHT)
    q_b    = q.transpose(Image.FLIP_TOP_BOTTOM)
    q_br   = q_r.transpose(Image.FLIP_TOP_BOTTOM)

    out = Image.new("RGBA", (w, h))
    out.paste(q,    (0,  0))
    out.paste(q_r,  (qw, 0))
    out.paste(q_b,  (0,  qh))
    out.paste(q_br, (qw, qh))
    return out


def _sym_kaleidoscope(img: Image.Image, n: int = 8) -> Image.Image:
    """
    Polar kaleidoscope with *n* segments.

    Each 2π/n arc of the image is reflected within itself so the pattern
    tiles perfectly around the centre.  Produces the classic stained-glass /
    mandala effect.
    """
    # Centre-crop to square for a perfect circle
    w, h    = img.size
    size    = min(w, h)
    left_c  = (w - size) // 2
    top_c   = (h - size) // 2
    img_sq  = img.crop((left_c, top_c, left_c + size, top_c + size))

    arr = np.array(img_sq.convert("RGBA"), dtype=np.uint8)  # (size, size, 4)
    cx = cy = size // 2

    # Build index grids
    yi, xi  = np.mgrid[0:size, 0:size]
    dx      = (xi - cx).astype(np.float32)
    dy      = (yi - cy).astype(np.float32)
    r       = np.sqrt(dx ** 2 + dy ** 2)
    theta   = np.arctan2(dy, dx)          # −π … π

    seg     = 2.0 * math.pi / n
    half    = seg / 2.0

    # Fold all angles into [0, half] within one segment
    theta_mod = theta % seg               # [0, seg)
    mirror    = theta_mod > half
    theta_mod[mirror] = seg - theta_mod[mirror]

    # Map folded angles back to Cartesian source coordinates
    src_x = np.clip((cx + r * np.cos(theta_mod)).astype(np.int32), 0, size - 1)
    src_y = np.clip((cy + r * np.sin(theta_mod)).astype(np.int32), 0, size - 1)

    result = arr[src_y, src_x]           # (size, size, 4)
    return Image.fromarray(result, "RGBA")


# ── edge detection ────────────────────────────────────────────────────────────

def _compute_edges(img: Image.Image) -> np.ndarray:
    """
    Return a uint8 (h, w) Sobel-magnitude edge map of *img*.

    Uses scipy.ndimage.sobel on the luminance channel.  Result is
    contrast-stretched so the brightest edge = 255.
    """
    gray = np.array(img.convert("L"), dtype=np.float32)
    sx   = sobel(gray, axis=1)
    sy   = sobel(gray, axis=0)
    mag  = np.hypot(sx, sy)

    peak = mag.max()
    if peak > 1e-6:
        mag = mag / peak * 255.0
    return np.clip(mag, 0, 255).astype(np.uint8)
