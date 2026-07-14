import json
import logging
import queue
import threading
from datetime import datetime, timezone

_log = logging.getLogger("friday.event_bus")


class EventBus:
    def __init__(self):
        # Queue-based subscribers (used by SSE / dashboard streams)
        self._subscribers = []
        # Callback-based subscribers: {event_type: [callable, ...]}
        self._callbacks: dict[str, list] = {}
        self._lock = threading.Lock()

    # ── queue-based subscribe (SSE / dashboard) ────────────────────────────────

    def subscribe(self):
        """Return a Queue that receives every published event."""
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subscribers = [item for item in self._subscribers if item is not q]

    # ── callback-based subscribe (internal subsystems) ─────────────────────────

    def on(self, event_type: str, callback) -> None:
        """Subscribe *callback* to a named event type.

        The callback is invoked synchronously inside publish() on the calling
        thread.  It must not block.  Exceptions in callbacks are caught and
        logged so they never propagate to the publisher.
        """
        with self._lock:
            self._callbacks.setdefault(event_type, []).append(callback)

    def off(self, event_type: str, callback) -> None:
        """Unsubscribe a previously registered callback."""
        with self._lock:
            bucket = self._callbacks.get(event_type, [])
            self._callbacks[event_type] = [c for c in bucket if c is not callback]

    # ── publish ────────────────────────────────────────────────────────────────

    def publish(self, event_type, payload=None):
        event = {
            "type": event_type,
            "payload": payload or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Deliver to queue-based subscribers (non-blocking; drops if full)
        with self._lock:
            queue_subs = list(self._subscribers)
            cb_subs = list(self._callbacks.get(event_type, []))

        for q in queue_subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass

        # Deliver to callback-based subscribers; isolate each callback
        for cb in cb_subs:
            try:
                cb(event)
            except Exception as exc:
                _log.error("EventBus callback error [%s]: %s", event_type, exc)

        return event

    @staticmethod
    def encode_sse(event):
        data = json.dumps(event, ensure_ascii=False)
        return f"event: {event['type']}\ndata: {data}\n\n".encode("utf-8")


# ── module-level singleton ─────────────────────────────────────────────────────
# All subsystems import this instance so they share the same bus without
# needing to thread it through every constructor.
_global_bus: EventBus | None = None
_global_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the process-wide EventBus singleton, creating it on first call."""
    global _global_bus
    if _global_bus is None:
        with _global_bus_lock:
            if _global_bus is None:
                _global_bus = EventBus()
    return _global_bus
