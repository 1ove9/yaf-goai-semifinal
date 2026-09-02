"""Locked paired-state openEMS entry point for the current execution cycle."""

from __future__ import annotations

from typing import NoReturn


class CrossCheckNotAuthorizedError(RuntimeError):
    """Raised because neither cross-solver release can occur in this cycle."""


def run_paired_cross_check(*_args: object, **_kwargs: object) -> NoReturn:
    raise CrossCheckNotAuthorizedError(
        "paired openEMS cross-check is not authorized in this preregistration cycle"
    )
