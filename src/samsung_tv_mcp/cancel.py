"""Let a newer command stop a long TV routine that's still running.

The family remote runs each routine (Netflix, a YouTube cast, opening an app...) inside a
`scope` with its own event. Starting something new sets the old event; the old routine then
stops at its next wait or key press by raising `Cancelled`. Outside a scope these are just a
plain sleep and a no-op, so the CLI and Claude behave as before.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class Cancelled(Exception):
    """A newer command replaced this one."""


_local = threading.local()


def _event() -> threading.Event | None:
    return getattr(_local, "event", None)


@contextmanager
def scope(event: threading.Event):
    previous = _event()
    _local.event = event
    try:
        yield
    finally:
        _local.event = previous


def check() -> None:
    event = _event()
    if event is not None and event.is_set():
        raise Cancelled()


def sleep(seconds: float) -> None:
    event = _event()
    if event is None:
        time.sleep(seconds)
    elif event.wait(max(0.0, seconds)):
        raise Cancelled()


def stopper():
    """A callable that says whether the current routine has been replaced (for other threads)."""
    event = _event()
    return (lambda: event.is_set()) if event is not None else (lambda: False)
