"""Scelta del monitor all'avvio: elenca i display con anteprima e ricorda l'ultima scelta."""
from __future__ import annotations

import json
import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from src import paths
from src.capture import ScreenCapture


def _settings_path() -> str:
    cfg_dir = os.path.join(paths.user_dir(), "config")
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, "monitor.json")


def get_last_monitor() -> int:
    try:
        with open(_settings_path()) as f:
            return int(json.load(f).get("monitor", 1))
    except Exception:  # noqa: BLE001
        return 1


def set_last_monitor(monitor: int) -> None:
    try:
        with open(_settings_path(), "w") as f:
            json.dump({"monitor": monitor}, f)
    except Exception:  # noqa: BLE001
        pass


def list_monitors() -> list[dict]:
    """Elenca i monitor (indice mss 1..n, geometria in pixel)."""
    import mss
    with mss.mss() as sct:
        return [
            {"index": i, "left": m["left"], "top": m["top"],
             "width": m["width"], "height": m["height"]}
            for i, m in enumerate(sct.monitors[1:], start=1)
        ]


def _to_qpixmap(bgr, max_w: int = 320) -> QPixmap:
    import numpy as np
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    pix = QPixmap.fromImage(img)
    return pix.scaledToWidth(max_w, Qt.SmoothTransformation)


class MonitorPickerDialog(QDialog):
    def __init__(self, monitors: list[dict], default: int = 1, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scegli il monitor con il tavolo — Poker Assistant")
        self.monitors = monitors
        self.selected = default
        self._preview = None

        self.combo = QComboBox()
        for m in monitors:
            self.combo.addItem(
                f"Monitor {m['index']} — {m['width']}x{m['height']} px",
                m["index"],
            )
        idx = self.combo.findData(default)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self.combo.currentIndexChanged.connect(self._on_change)

        self.lbl_preview = QLabel("Anteprima...")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumSize(360, 220)
        self.lbl_preview.setStyleSheet("background:#222;color:#888;border:1px solid #444;")

        self.chk_remember = QCheckBox("Ricorda la scelta per la prossima volta")
        self.chk_remember.setChecked(True)

        btn_ok = QPushButton("OK")
        btn_ok.setStyleSheet("background:#2e7d32;color:white;font-weight:bold;")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("Annulla")
        btn_cancel.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        row.addStretch()

        lay = QVBoxLayout()
        lay.addWidget(QLabel("Su quale schermo è il tavolo da seguire?"))
        lay.addWidget(self.combo)
        lay.addWidget(self.lbl_preview, 1)
        lay.addWidget(self.chk_remember)
        lay.addLayout(row)
        self.setLayout(lay)
        self.resize(460, 380)

        self._on_change(self.combo.currentIndex())

    def _on_change(self, idx: int) -> None:
        m = self.monitors[idx]
        self.selected = m["index"]
        try:
            cap = ScreenCapture(m["index"])
            img = cap.grab_full()
            cap.close()
            self._preview = img
            self.lbl_preview.setPixmap(_to_qpixmap(img))
        except Exception as e:  # noqa: BLE001
            self.lbl_preview.setText(f"Anteprima non disponibile:\n{type(e).__name__}: {e}")

    def _accept(self) -> None:
        if self.chk_remember.isChecked():
            set_last_monitor(self.selected)
        self.accept()


def ask_monitor(parent=None) -> int | None:
    """Mostra il selettore (salta se c'è un solo monitor). Ritorna indice mss o None."""
    monitors = list_monitors()
    if len(monitors) <= 1:
        if monitors:
            set_last_monitor(monitors[0]["index"])
            return monitors[0]["index"]
        return None
    dialog = MonitorPickerDialog(monitors, default=get_last_monitor(), parent=parent)
    if dialog.exec_() == QDialog.Accepted:
        return dialog.selected
    return None