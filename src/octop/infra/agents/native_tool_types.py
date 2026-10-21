"""Signature of the authenticated, audited native operation decorator."""

from collections.abc import Awaitable, Callable
from typing import Any

NativeOperation = Callable[
    ...,
    Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[str]]],
]
