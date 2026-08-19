"""Cattura schermo multi-monitor via mss."""
from __future__ import annotations

import mss
import numpy as np


class ScreenCapture:
    """Cattura regioni dello schermo come array BGR (formato OpenCV)."""

    def __init__(self, monitor: int = 1) -> None:
        self.sct = mss.mss()
        self.monitor = monitor
        self._m = self.sct.monitors[monitor]

    @property
    def size(self) -> tuple[int, int]:
        return self._m["width"], self._m["height"]

    @property
    def offset(self) -> tuple[int, int]:
        return self._m["left"], self._m["top"]

    @staticmethod
    def monitor_count() -> int:
        with mss.mss() as sct:
            return len(sct.monitors) - 1

    def grab_region(self, left: int, top: int, width: int, height: int) -> np.ndarray:
        region = {"left": left, "top": top, "width": width, "height": height}
        shot = self.sct.grab(region)
        img = np.asarray(shot)[:, :, :3]
        return np.ascontiguousarray(img)

    def grab_full(self) -> np.ndarray:
        return self.grab_region(0, 0, self._m["width"], self._m["height"])

    def close(self) -> None:
        self.sct.close()