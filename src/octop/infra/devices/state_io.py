"""Bound transient Windows file locks without weakening atomic state writes."""

from __future__ import annotations

import os
import time
from collections.abc import Callable


def retry_file_lock[T](operation: Callable[[], T]) -> T:
    deadline = time.monotonic() + 1
    while True:
        try:
            return operation()
        except PermissionError as exc:
            if (
                os.name != "nt"
                or getattr(exc, "winerror", None) not in {5, 32, 33}
                or time.monotonic() >= deadline
            ):
                raise
            # MoveFileEx/read can overlap a short-lived reader or replacement.
            # Keep the original destination intact and surface persistent denial.
            time.sleep(0.01)
