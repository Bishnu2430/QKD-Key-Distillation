"""Parallel sweep driver.

Every (mask, QBER) point is independent, so sweeps are embarrassingly
parallel. This module spreads them over processes, which is the difference
between an overnight run and an afternoon one at the sample sizes REQ-VER-02
asks for.

Worker processes each JIT-compile the Numba kernels once (the on-disk cache
makes that cheap after the first run), then stream results back as they finish.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .code import RateMask
from .pipeline import measure


@dataclass
class Point:
    """One sweep point: a mask, a QBER and the knobs for that measurement."""

    mask: RateMask
    qber: float
    frames: int
    seed: int
    label: str = ""
    kwargs: dict[str, Any] = field(default_factory=dict)


def _run_point(point: Point) -> dict:
    stats = measure(point.mask, point.qber, point.frames, seed=point.seed, **point.kwargs)
    stats["label"] = point.label
    return stats


def default_workers() -> int:
    """Leave one core for the rest of the machine."""
    return max(1, (os.cpu_count() or 2) - 1)


def run_points(
    points: Iterable[Point],
    workers: int | None = None,
    on_result: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Measure every point, in parallel, and return the results.

    ``workers=1`` runs in-process, which keeps tracebacks readable while
    debugging. ``on_result`` is called as each point lands, for progress output.
    """
    points = list(points)
    workers = default_workers() if workers is None else workers

    if workers <= 1:
        out = []
        for p in points:
            r = _run_point(p)
            if on_result:
                on_result(r)
            out.append(r)
        return out

    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_point, p): p for p in points}
        for fut in as_completed(futures):
            r = fut.result()
            if on_result:
                on_result(r)
            results.append(r)

    # keep the caller's ordering rather than completion order
    order = {(id(p.mask), p.qber, p.label): i for i, p in enumerate(points)}
    results.sort(key=lambda r: order.get((id(r.get("_mask")), r["qber"], r.get("label", "")), 0))
    results.sort(key=lambda r: (r.get("label", ""), r["qber"]))
    return results
