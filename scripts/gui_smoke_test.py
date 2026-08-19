"""Smoke test GUI: apre SeatConfigWindow e HUD, li chiude dopo 2s."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from src.qt_env import fix_qt_plugins
fix_qt_plugins()

app = QApplication(sys.argv)

from src.seat_config import SeatConfigWindow
from src.hud import Hud

win = SeatConfigWindow(monitor=1)
win.resize(1400, 900)
win.show()
print("SeatConfigWindow aperta:", win.isVisible())

hud = Hud(callbacks={"toggle": lambda: None, "reset": lambda: None})
hud.show()
print("HUD aperta:", hud.isVisible())

hud.set_hand(["As", "Kd"], ["2c", "7h", "Jd"], {1: ["Qs", "Qc"]})
hud.set_equity({"hero": {"win": 55.0, "tie": 2.5, "lose": 42.5}, "iterations": 30000}, 900)
hud.set_action({"action": "raise", "amount": 26, "reason": "equity 68% — value"})
print("HUD aggiornata")

QTimer.singleShot(2000, app.quit)
sys.exit(app.exec_())