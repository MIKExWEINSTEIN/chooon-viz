"""
audio.py - Real-time audio capture and analysis for chooon-viz.

Captures audio from the default input device, computes FFT, detects beats,
and exposes a thread-safe AudioData snapshot for the renderer to consume.
Also runs a WebSocket server on ws://localhost:8765 that broadcasts every
analysed frame as JSON to all connected clients.
"""

import asyncio
import json
import threading
import numpy as np
import pyaudio
import websockets

# ── constants ────────────────────────────────────────────────────────────────
SAMPLE_RATE   = 44100
CHUNK         = 1024          # frames per read
FFT_SIZE      = CHUNK * 2     # zero-pad for better freq resolution
CHANNELS      = 1

# Frequency bands (Hz): sub-bass, bass, low-mid, mid, high
BANDS = [
    (20,   60),    # sub-bass
    (60,   250),   # bass
    (250,  500),   # low-mid
    (500,  2000),  # mid
    (2000, 8000),  # high
    (8000, 20000), # air
]

# Beat detection – energy history window (# chunks)
BEAT_HISTORY  = 43   # ~1 s worth at 44100/1024

# ── module-level WebSocket state ──────────────────────────────────────────────
_ws_clients: set = set()
_ws_loop: asyncio.AbstractEventLoop | None = None


async def _ws_handler(ws):
    """Accept a new connection and keep it alive until the client disconnects."""
    _ws_clients.add(ws)
    try:
        await ws.wait_closed()
    finally:
        _ws_clients.discard(ws)


async def _broadcast(msg: str):
    """Send *msg* to every connected client; silently drop dead connections."""
    dead = set()
    for ws in list(_ws_clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead


def start_ws_server(port: int = 8765):
    """
    Start the WebSocket server in a background daemon thread.
    The thread owns its own asyncio event loop so it never interferes
    with the audio capture thread or any caller event loop.
    """
    global _ws_loop

    def _run():
        global _ws_loop
        _ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_ws_loop)

        async def _serve():
            async with websockets.serve(_ws_handler, "localhost", port):
                await asyncio.Future()   # run until loop.stop()

        _ws_loop.run_until_complete(_serve())

    t = threading.Thread(target=_run, daemon=True, name="ws-server")
    t.start()


class AudioData:
    """Immutable snapshot of a single audio analysis frame."""
    __slots__ = (
        "raw_fft",      # full magnitude spectrum (FFT_SIZE//2,)
        "band_energy",  # per-band normalised energy  [0..1]  len==len(BANDS)
        "beat",         # True if a beat was detected this frame
        "beat_strength",# 0..1 – how strong the beat was
        "volume",       # overall RMS volume  0..1
        "dominant_freq",# Hz of the loudest component
    )

    def __init__(self, raw_fft, band_energy, beat, beat_strength, volume, dominant_freq):
        self.raw_fft       = raw_fft
        self.band_energy   = band_energy
        self.beat          = beat
        self.beat_strength = beat_strength
        self.volume        = volume
        self.dominant_freq = dominant_freq


_SILENT = AudioData(
    raw_fft        = np.zeros(FFT_SIZE // 2, dtype=np.float32),
    band_energy    = np.zeros(len(BANDS),    dtype=np.float32),
    beat           = False,
    beat_strength  = 0.0,
    volume         = 0.0,
    dominant_freq  = 0.0,
)


class AudioAnalyzer:
    """
    Opens a PyAudio stream and continuously analyses the incoming audio.

    Thread-safe: call ``get()`` from the render thread at any time.
    """

    def __init__(self, device_index=None):
        self._pa             = pyaudio.PyAudio()
        self._device_index   = device_index   # None → default input
        self._lock           = threading.Lock()
        self._current        = _SILENT
        self._running        = False
        self._thread         = None

        # Beat-detection history buffers
        self._energy_history = np.zeros(BEAT_HISTORY, dtype=np.float64)
        self._history_ptr    = 0

        # Running max for normalisation (decay slowly)
        self._band_max       = np.ones(len(BANDS), dtype=np.float64) * 1e-6
        self._fft_max        = 1e-6
        self._vol_max        = 1e-6

        # Smoothed band energies (prevent flickering)
        self._smooth_energy  = np.zeros(len(BANDS), dtype=np.float64)

    # ── public API ──────────────────────────────────────────────────────────

    def start(self):
        """Start the background capture thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background capture thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def get(self) -> AudioData:
        """Return the latest AudioData snapshot (never blocks)."""
        with self._lock:
            return self._current

    def list_input_devices(self):
        """Return list of (index, name) for all input devices."""
        devices = []
        for i in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices.append((i, info["name"]))
        return devices

    # ── internals ───────────────────────────────────────────────────────────

    def _capture_loop(self):
        kwargs = dict(
            format            = pyaudio.paFloat32,
            channels          = CHANNELS,
            rate              = SAMPLE_RATE,
            input             = True,
            frames_per_buffer = CHUNK,
        )
        if self._device_index is not None:
            kwargs["input_device_index"] = self._device_index

        try:
            stream = self._pa.open(**kwargs)
        except OSError as exc:
            print(f"[AudioAnalyzer] Could not open input stream: {exc}")
            self._running = False
            return

        buf = np.zeros(FFT_SIZE, dtype=np.float32)

        while self._running:
            try:
                raw = stream.read(CHUNK, exception_on_overflow=False)
            except OSError:
                continue

            chunk = np.frombuffer(raw, dtype=np.float32)
            # Rolling buffer: shift left, append new
            buf[:-CHUNK] = buf[CHUNK:]
            buf[-CHUNK:]  = chunk

            data = self._analyse(buf)
            with self._lock:
                self._current = data

        stream.stop_stream()
        stream.close()

    def _analyse(self, buf: np.ndarray) -> AudioData:
        # Windowed FFT
        window   = np.hanning(FFT_SIZE)
        windowed = buf * window
        spectrum = np.abs(np.fft.rfft(windowed, n=FFT_SIZE))[:FFT_SIZE // 2]

        freqs    = np.fft.rfftfreq(FFT_SIZE, d=1.0 / SAMPLE_RATE)[:FFT_SIZE // 2]

        # ── volume (RMS) ────────────────────────────────────────────────────
        rms = float(np.sqrt(np.mean(buf ** 2)))
        self._vol_max = max(self._vol_max * 0.9995, rms, 1e-6)
        volume = min(rms / self._vol_max, 1.0)

        # ── FFT normalisation ────────────────────────────────────────────────
        self._fft_max = max(self._fft_max * 0.9995, spectrum.max(), 1e-6)
        norm_fft = (spectrum / self._fft_max).astype(np.float32)

        # ── per-band energy ──────────────────────────────────────────────────
        raw_energy = np.zeros(len(BANDS), dtype=np.float64)
        for i, (lo, hi) in enumerate(BANDS):
            mask = (freqs >= lo) & (freqs < hi)
            if mask.any():
                raw_energy[i] = float(spectrum[mask].mean())

        self._band_max = np.maximum(self._band_max * 0.9995, raw_energy)
        self._band_max = np.maximum(self._band_max, 1e-6)
        norm_energy = raw_energy / self._band_max

        # Smooth (exponential moving average, α=0.3)
        self._smooth_energy = 0.7 * self._smooth_energy + 0.3 * norm_energy
        band_energy = self._smooth_energy.astype(np.float32)

        # ── beat detection (spectral flux on bass band) ───────────────────────
        bass_energy = float(raw_energy[1])   # bass band
        avg_hist    = self._energy_history.mean()
        threshold   = avg_hist * 1.35 + 1e-9

        beat = bass_energy > threshold and volume > 0.02
        beat_strength = float(np.clip((bass_energy - avg_hist) / (avg_hist + 1e-9), 0, 3) / 3.0)

        self._energy_history[self._history_ptr] = bass_energy
        self._history_ptr = (self._history_ptr + 1) % BEAT_HISTORY

        # ── dominant frequency ───────────────────────────────────────────────
        dom_idx      = int(np.argmax(spectrum))
        dominant_freq = float(freqs[dom_idx]) if dom_idx < len(freqs) else 0.0

        result = AudioData(
            raw_fft        = norm_fft,
            band_energy    = band_energy,
            beat           = beat,
            beat_strength  = beat_strength,
            volume         = float(volume),
            dominant_freq  = dominant_freq,
        )

        # ── WebSocket broadcast ──────────────────────────────────────────────
        if _ws_loop is not None and _ws_clients:
            msg = json.dumps({
                "beat":          bool(result.beat),
                "beat_strength": round(float(result.beat_strength), 3),
                "volume":        round(float(result.volume), 3),
                "band_energy":   [round(float(v), 3) for v in result.band_energy],
                "dominant_freq": round(float(result.dominant_freq), 1),
            })
            asyncio.run_coroutine_threadsafe(_broadcast(msg), _ws_loop)

        return result


# ── standalone entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    import time

    analyzer = AudioAnalyzer()
    start_ws_server()
    analyzer.start()
    print("Audio WebSocket server running on ws://localhost:8765")

    while True:
        time.sleep(1)
