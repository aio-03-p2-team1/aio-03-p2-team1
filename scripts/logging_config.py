"""Consistent stdout logging for operational scripts."""
from __future__ import annotations

import logging
import sys


def configure_logging() -> None:
    # httpx INFO logs include full request URLs, which can contain serviceKey.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )
