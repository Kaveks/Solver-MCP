"""
observability — cross-cutting instrumentation for all layers (logging, tracing, metrics).

The one shared utility every layer may import. It carries no business logic — only logging,
tracing, and (from Phase 4) metrics — so importing it does not cross a layer boundary.

    from observability import get_logger, set_correlation_id

Metrics (observability/metrics.py) are added in docs/phase-4.3.
"""

from observability.logging import (
    configure_logging,
    get_correlation_id,
    get_logger,
    set_correlation_id,
)
from observability.tracing import init_tracing

__all__ = [
    "configure_logging",
    "get_logger",
    "get_correlation_id",
    "set_correlation_id",
    "init_tracing",
]
