"""
audio_server.py - Runs the AudioAnalyzer and broadcasts data via WebSocket.
"""
import asyncio
import json
import time
import threading
import websockets
from audio import AudioAnalyzer

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

async def main():
    analyzer = AudioAnalyzer()
    analyzer.start()
    print("Audio WebSocket server running on ws://localhost:8765")
    print("Press Ctrl+C to stop.")
    async with websockets.serve(ws_handler, "localhost", 8765):
        await broadcast_loop(analyzer)

if __name__ == "__main__":
    asyncio.run(main())
