"""MT-138 probe: the C runtime's abort(), MT-112 PO-5's signature on demand."""

import os


def test_abort(qtbot: object) -> None:
    os.abort()
