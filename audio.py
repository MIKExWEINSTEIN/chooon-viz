"""
audio.py - Real-time audio capture, analysis, and WebSocket broadcast.

Captures audio from the default input device, computes FFT, detects beats,
and exposes a thread-safe AudioData snapshot for the renderer to consume.

WebSocket server
----------------
A WebSocket server runs on ws://localhost:8765 in a private background thread
(its own asyncio event loop).  Every time a new frame is analysed the server
broadcasts a JSON message to all connected clients:

    {
        "beat":          bool,
        "beat_strength": float  (0..1),
        "volume":        float  (0..1),
        "band_energy":   [float, float, float, float, float, float],
        "dominant_freq": float  (Hz)
    }

Clients that disconnect are silently removed.  If no clients are connected
the broadcast is a no-op.

Run standalone
--------------
    python3 audio.py [--device N] [--port PORT]

Prints a live status line and serves the WebSocket until Ctrl-C.
"""

import asyncio
import json
import threading
import numpy as np
import pyaudio

try:
    import websockets
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False
    print("[AudioAnalyzer] 'websockets' not installed — WebSocket server disabled.")

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

    A WebSocket server on ``ws://localhost:<port>`` broadcasts each frame to
    connected clients as JSON.  The server runs in its own daemon thread with
    a private asyncio event loop so it never interferes with the capture loop
    or the caller's event loop.
    """

    def __init__(self, device_index=None, ws_port=8765):
        self._pa             = pyaudio.PyAudio()
        self._device_index   = device_index   # None → default input
        self._ws_port        = ws_port
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

        # WebSocket state — owned by _ws_thread / _ws_loop
        self._ws_loop        = None          # asyncio event loop (WS thread)
        self._ws_clients     = set()         # connected WebSocketServerProtocol
        self._ws_thread      = None

    # ── public API ──────────────────────────────────────────────────────────

    def start(self):
        """Start the audio capture thread and the WebSocket server thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        if _WS_AVAILABLE:
            self._ws_thread = threading.Thread(
                target=self._run_ws_server, daemon=True, name="WS-server"
            )
            self._ws_thread.start()

    def stop(self):
        """Stop the audio capture thread (WS thread is daemon — exits with process)."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        # Signal the WS event loop to stop so the thread can exit cleanly
        if self._ws_loop and self._ws_loop.is_running():
            self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)

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

    # ── WebSocket server ─────────────────────────────────────────────────────

    def _run_ws_server(self):
        """
        Runs in a dedicated daemon thread.
        Creates a private asyncio event loop and hosts the WebSocket server
        for the lifetime of the process.
        """
        self._ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._ws_loop)

        async def handler(ws):
            self._ws_clients.add(ws)
            try:
                await ws.wait_closed()
            finally:
                self._ws_clients.discard(ws)

        async def serve():
            try:
                async with websockets.serve(handler, "localhost", self._ws_port):
                    print(f"[AudioAnalyzer] WebSocket server on ws://localhost:{self._ws_port}")
                    await asyncio.Future()   # run until loop.stop() is called
            except OSError as exc:
                print(f"[AudioAnalyzer] WebSocket server could not start: {exc}")

        self._ws_loop.run_until_complete(serve())

    def _broadcast(self, data: AudioData):
        """
        Called from the capture thread after each analysis frame.
        Schedules a coroutine on the WS event loop to send to all clients.
        Thread-safe: uses run_coroutine_threadsafe so no shared-state races.
        """
        if not _WS_AVAILABLE or not self._ws_clients or self._ws_loop is None:
            return

        msg = json.dumps({
            "beat":          bool(data.beat),
            "beat_strength": round(float(data.beat_strength), 3),
            "volume":        round(float(data.volume), 3),
            "band_energy":   [round(float(v), 3) for v in data.band_energy],
            "dominant_freq": round(float(data.dominant_freq), 1),
        })

        async def _send_all():
            dead = set()
            for ws in list(self._ws_clients):
                try:
                    await ws.send(msg)
                except Exception:
                    dead.add(ws)
            self._ws_clients -= dead

        asyncio.run_coroutine_threadsafe(_send_all(), self._ws_loop)

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

            self._broadcast(data)   # non-blocking: schedules on WS loop

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

        return AudioData(
            raw_fft        = norm_fft,
            band_energy    = band_energy,
            beat           = beat,
            beat_strength  = beat_strength,
            volume         = float(volume),
            dominant_freq  = dominant_freq,
        )


# ── standalone entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import time

    p = argparse.ArgumentParser(description="chooon-viz audio analyser + WebSocket server")
    p.add_argument("--device", type=int, default=None, help="PyAudio input device index")
    p.add_argument("--port",   type=int, default=8765,  help="WebSocket port (default 8765)")
    args = p.parse_args()

    analyzer = AudioAnalyzer(device_index=args.device, ws_port=args.port)
    analyzer.start()

    print("Capturing audio.  Ctrl-C to stop.")
    print("Connect a WebSocket client to see live data.\n")

    band_labels = ["sub", "bas", "lmid", "mid", "hi", "air"]

    try:
        while True:
            time.sleep(0.1)
            a = analyzer.get()
            bars = "  ".join(
                f"{lbl}={v:.2f}" for lbl, v in zip(band_labels, a.band_energy)
            )
            beat_marker = "BEAT" if a.beat else "    "
            print(
                f"\r  {beat_marker}  vol={a.volume:.2f}  {bars}  "
                f"f={a.dominant_freq:6.0f}Hz    ",
                end="", flush=True,
            )
    except KeyboardInterrupt:
        print("\nStopping.")
        analyzer.stop()
