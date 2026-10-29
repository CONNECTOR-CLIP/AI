"""Optional JSONL timings for CoT4/CoT5, enabled by COT_TIMING_LOG."""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path


_lock = threading.Lock()


def emit(stage: str, idea_title: str, step: str, seconds: float, status: str = "ok", **extra) -> None:
    path = os.getenv("COT_TIMING_LOG")
    if not path:
        return
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "idea_title": idea_title,
        "step": step,
        "seconds": round(seconds, 4),
        "status": status,
        **extra,
    }
    with _lock:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


@contextmanager
def measure(stage: str, idea_title: str, step: str, **extra):
    started = time.perf_counter()
    status = "ok"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        emit(stage, idea_title, step, time.perf_counter() - started, status, **extra)


def timed_sync(stage: str, step: str):
    def decorate(fn):
        @wraps(fn)
        def wrapped(self, idea, *args, **kwargs):
            with measure(stage, idea.title, step):
                return fn(self, idea, *args, **kwargs)
        return wrapped
    return decorate


def timed_async(stage: str, step: str):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(idea, *args, **kwargs):
            with measure(stage, idea.title, step):
                return await fn(idea, *args, **kwargs)
        return wrapped
    return decorate
