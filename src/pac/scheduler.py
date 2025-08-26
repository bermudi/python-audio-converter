"""Simple worker pool for running encoding jobs (standard library).

Adds a bounded, unordered iterator that maintains backpressure so that
only O(workers) tasks are in-flight, suitable for very large catalogs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
from typing import Callable, Iterable, Optional, Tuple, Any, Dict, Set, Iterator
import threading

from loguru import logger


class WorkerPool:
    def __init__(self, max_workers: int) -> None:
        self._exe = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pac-worker")
        self._max_workers = max_workers

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        return self._exe.submit(fn, *args, **kwargs)

    def map(self, fn: Callable[..., Any], items: Iterable[Any]) -> Iterable[Any]:
        return self._exe.map(fn, items)

    def imap_unordered_bounded(
        self,
        fn: Callable[[Any], Any],
        iterable: Iterable[Any],
        max_pending: int,
        *,
        stop_event: Optional[threading.Event] = None,
    ) -> Iterator[Tuple[Any, Any]]:
        """Yield (item, result) as they complete while keeping <= max_pending futures in flight.

        - fn: function called as fn(item) -> result
        - iterable: items to process
        - max_pending: max futures in flight (should be a small multiple of workers)
        - stop_event: if set, stops submitting new tasks; drains in-flight tasks
        """
        if max_pending < 1:
            raise ValueError("max_pending must be >= 1")

        # One-time debug for observability in field reports
        try:
            factor = max_pending / max(1, self._max_workers)
            logger.debug(
                f"bounded window: bound={max_pending} (≈{factor:.1f}×workers, workers={self._max_workers})"
            )
        except Exception:
            logger.debug(f"bounded window: bound={max_pending} (workers={self._max_workers})")

        it = iter(iterable)
        pending: Dict[Future, Any] = {}
        active: Set[Future] = set()

        def try_submit() -> bool:
            if stop_event is not None and stop_event.is_set():
                return False
            try:
                item = next(it)
            except StopIteration:
                return False
            fut = self._exe.submit(fn, item)
            pending[fut] = item
            active.add(fut)
            return True

        # Prime the window
        while len(active) < max_pending and try_submit():
            pass

        while active:
            done_set, _ = wait(active, return_when=FIRST_COMPLETED)
            for fut in done_set:
                active.remove(fut)
                item = pending.pop(fut)
                result = fut.result()
                yield item, result
                # Replenish after a completion
                if len(active) < max_pending:
                    try_submit()

    def shutdown(self, wait: bool = True) -> None:
        self._exe.shutdown(wait=wait)
