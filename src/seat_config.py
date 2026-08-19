"""UI di configurazione: seleziona le regioni dei seggiolini e del board.

Usa uno screenshot del monitor: trascina rettangoli, assegna il ruolo
(Hero / Avversario / Board) e salva in config/config.json.
"""
from __future__ import annotations

import json
import os
import sys

from PyQt5.QtCore import Qt, QRect, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap, QImage
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
    QPushButton, QVBoxLayout, QWidget,
)

ROLE_COLORS = {"hero": QColor(0, 200, 0), "opp": QColor(255, 160, 0),
               "board": QColor(0, 150, 255), "pot": QColor(255, 80, 200)}
ROLE_LABELS = {"hero": "Seat Hero (tu)", "opp": "Seggiolino avversario",
               "board": "Board (carte comuni)", "pot": "Pot (area cifre, opzionale)"}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from src.paths import model_path

MODEL_PATH = model_path()


def to_qimage(bgr) -> QImage:
    import numpy as np
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class SelectionCanvas(QWidget):
    def __init__(self, screenshot, scale: float, parent=None) -> None:
        super().__init__(parent)
        self.screenshot = screenshot
        self.scale = scale
        self.role = "hero"
        self.rects: list[dict] = []
        self._drag_start = None
        self._drag_cur = None
        self.setMouseTracking(True)
        img = to_qimage(screenshot)
        self._pix = QPixmap.fromImage(img)
        self.setFixedSize(int(img.width() * scale), int(img.height() * scale))

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return int(x / self.scale), int(y / self.scale)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pix.scaled(self.width(), self.height(), Qt.KeepAspectRatio))
        for r in self.rects:
            color = ROLE_COLORS[r["role"]]
            pen = QPen(color, 3)
            p.setPen(pen)
            rect = QRect(
                int(r["x"] * self.scale), int(r["y"] * self.scale),
                int(r["w"] * self.scale), int(r["h"] * self.scale),
            )
            p.drawRect(rect)
            p.setPen(QPen(Qt.white, 1))
            p.drawText(rect.adjusted(5, 5, -5, -5), r["label"])
        if self._drag_cur:
            p.setPen(QPen(ROLE_COLORS[self.role], 2, Qt.DashLine))
            x1, y1 = self._drag_start
            x2, y2 = self._drag_cur
            p.drawRect(QRect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)))

    def mousePressEvent(self, e) -> None:
        self._drag_start = (e.pos().x(), e.pos().y())
        self._drag_cur = (e.pos().x(), e.pos().y())

    def mouseMoveEvent(self, e) -> None:
        if self._drag_start:
            self._drag_cur = (e.pos().x(), e.pos().y())
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if not self._drag_start:
            return
        x1, y1 = self._drag_start
        x2, y2 = (e.pos().x(), e.pos().y())
        self._drag_start = None
        self._drag_cur = None
        sx1, sy1 = self.to_screen(min(x1, x2), min(y1, y2))
        sx2, sy2 = self.to_screen(max(x1, x2), max(y1, y2))
        if sx2 - sx1 < 5 or sy2 - sy1 < 5:
            self.update()
            return
        n = len([r for r in self.rects if r["role"] == self.role])
        label = ROLE_LABELS[self.role].split("(")[0].strip() + f" #{n + 1}"
        self.rects.append({"role": self.role, "x": sx1, "y": sy1, "w": sx2 - sx1, "h": sy2 - sy1, "label": label})
        self.update()


class LearnWorker(QThread):
    """Rilevamento tavolo/carte in un thread separato per non bloccare la UI.

    (Su Windows una UI bloccata 20+ secondi viene mostrata come
    "Non risponde" e sembra un crash.)
    """

    progress = pyqtSignal(int, int)
    done = pyqtSignal(list, object)
    error = pyqtSignal(str)

    def __init__(self, monitor: int, model_path: str, total: int = 12) -> None:
        super().__init__()
        self.monitor = monitor
        self.model_path = model_path
        self.total = total
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from src.capture import ScreenCapture
        from src.detector import CardDetector
        dets_all: list = []
        img = None
        try:
            cap = ScreenCapture(self.monitor)
            # imgsz piu' alto per le carte piccole a schermo intero
            detector = CardDetector(self.model_path, conf=0.35, imgsz=1280)
            for i in range(self.total):
                if self._stop:
                    break
                img = cap.grab_full()
                dets_all.append(detector.detect(img))
                self.progress.emit(i + 1, self.total)
            cap.close()
            self.done.emit(dets_all, img)
        except Exception as e:  # noqa: BLE001
            self.error.emit(f"{type(e).__name__}: {e}")


class SeatConfigWindow(QMainWindow):
    def __init__(self, monitor: int = 1) -> None:
        super().__init__()
        self.setWindowTitle("Configura seggiolini — Poker Assistant")
        self.monitor = monitor
        self._worker = None

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from src.capture import ScreenCapture

        self.screenshot = None
        self.screen_w, self.screen_h = 1920, 1080
        self._capture_error = None
        cap = ScreenCapture(monitor)
        try:
            self.screenshot = cap.grab_full()
            self.screen_w, self.screen_h = cap.size
        except Exception as e:  # noqa: BLE001
            self._capture_error = f"{type(e).__name__}: {e}"
        finally:
            cap.close()
        if self.screenshot is None:
            import numpy as np
            self.screenshot = np.zeros((self.screen_h, self.screen_w, 3), dtype=np.uint8)

        scale = min(1.0, 1280.0 / self.screen_w, 800.0 / self.screen_h)
        self.canvas = SelectionCanvas(self.screenshot, scale)

        self.role_combo = QComboBox()
        for key, label in ROLE_LABELS.items():
            self.role_combo.addItem(label, key)
        self.role_combo.currentIndexChanged.connect(self._role_changed)

        self.btn_auto = QPushButton("Scopri tavolo automaticamente")
        self.btn_auto.setStyleSheet("background:#00695c;color:white;font-weight:bold;")
        self.btn_auto.clicked.connect(self._start_auto)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet("color:#ffd54f;padding:4px;")

        self.btn_undo = QPushButton("Annulla ultimo")
        self.btn_undo.clicked.connect(lambda: (self.canvas.rects.pop(), self.canvas.update()) if self.canvas.rects else None)
        self.btn_clear = QPushButton("Pulisci tutto")
        self.btn_clear.clicked.connect(self._clear)
        self.btn_save = QPushButton("Salva configurazione")
        self.btn_save.setStyleSheet("background:#2e7d32;color:white;font-weight:bold;")
        self.btn_save.clicked.connect(self._save)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Ruolo:"))
        bar.addWidget(self.role_combo)
        bar.addWidget(self.btn_undo)
        bar.addWidget(self.btn_clear)
        bar.addWidget(self.btn_auto)
        bar.addStretch()
        bar.addWidget(self.btn_save)

        root = QVBoxLayout()
        root.addWidget(self.canvas)
        root.addWidget(self.lbl_progress)
        root.addLayout(bar)
        wrap = QWidget()
        wrap.setLayout(root)
        self.setCentralWidget(wrap)

        info = QLabel("Trascina col mouse un rettangolo per ogni seggiolino e per le carte comuni. "
                      "Il primo Hero = tu. Oppure usa 'Scopri tavolo automaticamente'.")
        info.setStyleSheet("padding:6px;")
        if self._capture_error:
            info.setText(info.text() + f"  [Errore cattura: {self._capture_error}]")
        root.insertWidget(0, info)

        QTimer.singleShot(400, self._start_auto)

    def _start_auto(self) -> None:
        if getattr(self, "_auto_running", False) or (self._worker and self._worker.isRunning()):
            return
        if self._capture_error:
            self.lbl_progress.setText(f"Cattura schermo non disponibile: {self._capture_error}")
            return
        self._auto_running = True
        self._auto_layout = None
        self._auto_dets: list = []
        self.btn_auto.setEnabled(False)
        self.btn_auto.setText("Apprendimento in corso...")
        self.lbl_progress.setText("Apprendimento del tavolo... (tieni il tavolo visibile)")
        self._worker = LearnWorker(self.monitor, MODEL_PATH)
        self._worker.progress.connect(self._auto_progress)
        self._worker.done.connect(self._auto_done)
        self._worker.error.connect(self._auto_error)
        self._worker.start()

    def _auto_progress(self, n: int, total: int) -> None:
        self.lbl_progress.setText(f"Apprendimento del tavolo... {n}/{total}")

    def _auto_done(self, dets: list, img) -> None:
        self._auto_running = False
        self._auto_dets = dets
        self.btn_auto.setEnabled(True)
        self.btn_auto.setText("Scopri tavolo automaticamente")
        self._apply_layout(img)

    def _auto_error(self, msg: str) -> None:
        self._auto_running = False
        self.btn_auto.setEnabled(True)
        self.btn_auto.setText("Scopri tavolo automaticamente")
        self.lbl_progress.setText(f"Errore apprendimento: {msg}")

    def _apply_layout(self, img) -> None:
        from src.table_detector import build_layout
        layout = build_layout(self._auto_dets, img)
        if layout is None:
            self.lbl_progress.setText("Tavolo non riconosciuto: disegna i rettangoli a mano oppure riprova.")
            return
        self._auto_layout = layout
        self.canvas.rects.clear()
        counts = {"hero": 0, "opp": 0, "board": 0, "pot": 0}
        for s in layout.seats:
            role = "hero" if s["is_hero"] else "opp"
            counts[role] += 1
            r = s["rect"]
            self.canvas.rects.append({"role": role, "x": r[0], "y": r[1], "w": r[2], "h": r[3],
                                      "label": ROLE_LABELS[role].split("(")[0].strip() + f" #{counts[role]}"})
        bx, by, bw, bh = layout.board_rect
        self.canvas.rects.append({"role": "board", "x": bx, "y": by, "w": bw, "h": bh,
                                  "label": "Board (carte comuni) #1"})
        if layout.pot_rect:
            px, py, pw, ph = layout.pot_rect
            self.canvas.rects.append({"role": "pot", "x": px, "y": py, "w": pw, "h": ph,
                                      "label": "Pot (area cifre) #1"})
        self.canvas.update()
        self.lbl_progress.setText(
            f"Layout proposto: {len(layout.seats)} seggiolini · confidenza {layout.confidence:.0%}. "
            "Sistema i rettangoli se serve, poi Salva.")
        self.statusBar().showMessage("Verifica i rettangoli verdi/arancioni/blu e premi 'Salva configurazione'.", 8000)

    def _role_changed(self, idx: int) -> None:
        self.canvas.role = self.role_combo.itemData(idx)

    def _clear(self) -> None:
        self.canvas.rects.clear()
        self.canvas.update()

    def _save(self) -> None:
        rects = self.canvas.rects
        heroes = [r for r in rects if r["role"] == "hero"]
        opps = [r for r in rects if r["role"] == "opp"]
        boards = [r for r in rects if r["role"] == "board"]
        pots = [r for r in rects if r["role"] == "pot"]
        if not heroes or not boards:
            self.statusBar().showMessage("Serve almeno un seggiolino Hero e una zona Board!", 5000)
            return
        hero = heroes[0]
        seats = [{"label": "Hero (tu)", "is_hero": True, "rect": [hero["x"], hero["y"], hero["w"], hero["h"]],
                  "range": "random", "aggression": 1.0}]
        for o in opps:
            seats.append({"label": o["label"], "is_hero": False, "rect": [o["x"], o["y"], o["w"], o["h"]],
                          "range": "random", "aggression": 1.0})
        board = boards[0]
        cfg = {
            "monitor": self.monitor,
            "screen_size": [self.screen_w, self.screen_h],
            "seats": seats,
            "board_rect": [board["x"], board["y"], board["w"], board["h"]],
        }
        if pots:
            p = pots[0]
            cfg["pot_rect"] = [p["x"], p["y"], p["w"], p["h"]]
        cfg["settings"] = {
                "fps": 5,
                "conf_threshold": 0.6,
                "mc_iterations": 30000,
                "imgsz": 640,
                "use_ocr": False,
                "position": "middle",
                "open_tiers": {"early": 7, "middle": 6, "late": 5, "blind": 6},
                "raise_equity_threshold": 0.62,
                "fold_margin": 0.03,
                "raise_threshold": 0.60,
                "bet_pct": 0.66,
                "opponent_ranges": {"tight": "tight10", "loose": "loose25", "aggressive": "loose50"},
            }
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.makedirs(os.path.join(base, "config"), exist_ok=True)
        name, ok = QInputDialog.getText(
            self, "Nome piattaforma",
            "Come si chiama questa piattaforma/tavolo?\n(es. 888, sisal, playmoney — verrà usata per l'auto-selezione)",
            text="",
        )
        if ok and name.strip():
            from src import profiles
            trect = None
            if getattr(self, "_auto_layout", None):
                trect = self._auto_layout.table_rect
            path = profiles.complete_profile(name.strip(), cfg, trect)
            self.statusBar().showMessage(f"Profilo '{name.strip()}' salvato in {path} — {len(seats)} seggiolini + board.", 8000)
        else:
            path = os.path.join(base, "config", "config.json")
            with open(path, "w") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            self.statusBar().showMessage(f"Salvato in {path} — {len(seats)} seggiolini + board.", 5000)
        self.close()

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        event.accept()


def run(monitor: int = 1) -> int:
    from src.qt_env import fix_qt_plugins
    fix_qt_plugins()
    app = QApplication.instance() or QApplication(sys.argv)
    win = SeatConfigWindow(monitor)
    win.resize(1400, 900)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(run())