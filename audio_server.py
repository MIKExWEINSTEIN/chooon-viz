"""
audio_server.py - Runs the AudioAnalyzer and broadcasts data via WebSocket.
Also serves an HTTP API on port 8080 for photo settings persistence.

Endpoints (port 8080):
  GET  /photo_settings.json  — return saved vignette settings
  POST /save_settings        — write updated settings JSON to disk
"""
import asyncio
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websockets
from audio import AudioAnalyzer

# ── Settings file path ───────────────────────────────────────────────────────
SETTINGS_PATH = pathlib.Path(__file__).parent / 'photo_settings.json'

# ── HTTP server (port 8080) ──────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for settings GET and POST."""

    def log_message(self, fmt, *args):  # silence default request logging
        pass

    def _send_cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        if self.path == '/photo_settings.json':
            if SETTINGS_PATH.exists():
                data = SETTINGS_PATH.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._send_cors()
                self.end_headers()
                self.wfile.write(data)
                print(f'[HTTP] GET /photo_settings.json — {len(data)} bytes')
            else:
                self.send_response(404)
                self._send_cors()
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/save_settings':
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            try:
                json.loads(body)  # validate before writing
                SETTINGS_PATH.write_bytes(body)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._send_cors()
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
                print(f'[HTTP] POST /save_settings — {len(body)} bytes saved')
            except (json.JSONDecodeError, OSError) as exc:
                self.send_response(400)
                self._send_cors()
                self.end_headers()
                print(f'[HTTP] POST /save_settings error: {exc}')
        else:
            self.send_response(404)
            self.end_headers()


def _run_http_server():
    server = ThreadingHTTPServer(('localhost', 8080), _Handler)
    print('HTTP server running on http://localhost:8080')
    server.serve_forever()

# ── WebSocket broadcast (port 8765) ─────────────────────────────────────────
connected_clients = set()

async def ws_handler(websocket):
    connected_clients.add(websocket)
    print(f"[WS] Client connected. Total: {len(connected_clients)}")
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)
        print(f"[WS] Client disconnected. Total: {len(connected_clients)}")

async def broadcast_loop(analyzer):
    while True:
        if connected_clients:
            data = analyzer.get()
            msg = json.dumps({
                "beat":          data.beat,
                "beat_strength": round(float(data.beat_strength), 4),
                "volume":        round(float(data.volume), 4),
                "band_energy":   [round(float(x), 4) for x in data.band_energy],
                "dominant_freq": round(float(data.dominant_freq), 2),
            })
            dead = set()
            for ws in connected_clients:
                try:
                    await ws.send(msg)
                except Exception:
                    dead.add(ws)
            connected_clients -= dead
        await asyncio.sleep(0.016)  # ~60fps

# ── Entry point ──────────────────────────────────────────────────────────────
async def main():
    # HTTP server in a background daemon thread
    http_thread = threading.Thread(target=_run_http_server, daemon=True)
    http_thread.start()

    analyzer = AudioAnalyzer()
    analyzer.start()
    print("Audio WebSocket server running on ws://localhost:8765")
    print("Press Ctrl+C to stop.")
    async with websockets.serve(ws_handler, "localhost", 8765):
        await broadcast_loop(analyzer)

if __name__ == "__main__":
    asyncio.run(main())
