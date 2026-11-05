"""MT-138 probe: a warning the tee ignores, a critical it reports, one failure."""

from PySide6 import QtCore


def test_warning_passes(qtbot: object) -> None:
    QtCore.qWarning("PROBE-WARNING")


def test_critical_then_fail(qtbot: object) -> None:
    QtCore.qCritical("PROBE-CRITICAL reported")
    raise AssertionError("PROBE-FAILURE")
