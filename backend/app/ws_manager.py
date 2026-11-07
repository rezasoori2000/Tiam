"""Broadcast-style WebSocket connection manager. Each camera gets its own
ConnectionManager instance (see camera_manager.get_stream_manager), fanning
that camera's frames out to every client watching it; alerts use one shared
global instance below since every alert payload is already tagged with its
camera_id.

Each camera has exactly one producer coroutine (camera_manager._pump_camera_frames)
pulling frames off that camera's frame_queue and calling broadcast_bytes(). If
broadcasting meant awaiting a network write to every client in sequence, one
slow/high-latency client (e.g. a remote viewer on a slower link than the
server's own LAN) would pace -- or with an unbounded await, completely stall
-- delivery to every other client of that camera, including the server's own
local view. So each connection gets its own bounded, drop-oldest queue and
writer task: broadcast_bytes/json only ever does a non-blocking enqueue, and
each client's actual send happens independently at whatever rate that
client's link supports."""
import asyncio
import logging
from typing import Dict, List, Union

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Matches camera_manager.FRAME_QUEUE_MAXSIZE -- fine to drop stale frames for
# a slow viewer, they'll catch up to "live" as soon as their link keeps up.
DEFAULT_QUEUE_MAXSIZE = 2


class ConnectionManager:
    def __init__(self, queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE) -> None:
        self.active: List[WebSocket] = []
        self._queue_maxsize = queue_maxsize
        self._queues: Dict[WebSocket, "asyncio.Queue"] = {}
        self._writers: Dict[WebSocket, "asyncio.Task"] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._queues[websocket] = queue
        self._writers[websocket] = asyncio.create_task(self._writer(websocket, queue))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)
        self._queues.pop(websocket, None)
        writer = self._writers.pop(websocket, None)
        if writer is not None:
            writer.cancel()

    async def _writer(self, websocket: WebSocket, queue: "asyncio.Queue") -> None:
        """One task per connection: drains that client's own queue and does
        the actual (potentially slow) network send, fully isolated from every
        other client and from the shared frame-pump coroutine."""
        try:
            while True:
                data = await queue.get()
                if isinstance(data, (bytes, bytearray)):
                    await websocket.send_bytes(data)
                else:
                    await websocket.send_json(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.disconnect(websocket)

    def _enqueue(self, websocket: WebSocket, data: Union[bytes, dict]) -> None:
        queue = self._queues.get(websocket)
        if queue is None:
            return
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(data)

    async def broadcast_bytes(self, data: bytes) -> None:
        for ws in list(self.active):
            self._enqueue(ws, data)

    async def broadcast_json(self, data: dict) -> None:
        for ws in list(self.active):
            self._enqueue(ws, data)


# Alerts are low-frequency and shouldn't be casually dropped the way stale
# video frames are -- give them a much larger buffer than the video default.
alerts_manager = ConnectionManager(queue_maxsize=64)
