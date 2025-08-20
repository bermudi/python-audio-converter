"""Simple worker pool for running encoding jobs (standard library).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Callable, Iterable, List, Optional, Tuple, Any


class WorkerPool:
    def __init__(self, max_workers: int) -> None:
        self._exe = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pac-worker")

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        return self._exe.submit(fn, *args, **kwargs)

    def map(self, fn: Callable[..., Any], items: Iterable[Any]) -> Iterable[Any]:
        return self._exe.map(fn, items)

    def shutdown(self, wait: bool = True) -> None:
        self._exe.shutdown(wait=wait)
