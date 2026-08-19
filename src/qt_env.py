"""Fissa il percorso dei plugin Qt: cv2 lo sovrascrive con i propri plugin (incompatibili)."""
from __future__ import annotations

import os


def fix_qt_plugins() -> None:
    try:
        import PyQt5  # noqa: PLC0415
        plugins = os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
        if os.path.isdir(plugins):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugins
    except ImportError:
        pass