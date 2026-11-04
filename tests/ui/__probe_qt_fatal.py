"""MT-138 probe: a Qt critical at import, then a test that goes fatal."""

from PySide6 import QtCore

QtCore.qCritical("PROBE-CRITICAL at import")


def test_qfatal(qtbot: object) -> None:
    QtCore.qCritical("PROBE-CRITICAL before the fatal")
    QtCore.QMessageLogger().fatal("PROBE-FATAL")
