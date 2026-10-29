"""Markers owned by `tests/integration/` (MT-123 Contract block 5).

`gpu` and `network` are registered in `pyproject.toml`; `pages` is registered
here, because RED may write a test path and not `pyproject.toml`'s pytest
table. GREEN may move the line into `[tool.pytest.ini_options] markers` if it
prefers one registry - either is acceptable, both is not.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "pages: reads non-redistributable scans under spikes/; needs no GPU; never runs on CI",
    )
