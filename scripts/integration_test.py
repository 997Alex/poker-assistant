"""Test di integrazione: simulazione della pipeline completa su immagini reali di tavolo."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detector import CardDetector
from src.state_tracker import GameState

IMG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/opencode/yolo11-poker/images/real_img_2.png"
MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "poker_best.pt")

import cv2
img = cv2.imread(IMG)
h, w = img.shape[:2]
print(f"Immagine {w}x{h}")

# regioni fittizie: 2 seggiolini (bande laterali) + board (metà centrale)
left = img[:, :w//4]
right = img[:, 3*w//4:]
board = img[:, w//4:3*w//4]

det = CardDetector(MODEL, conf=0.45, imgsz=640)
t0 = time.time()
for name, region in [("seat L", left), ("seat R", right), ("board", board)]:
    d = det.detect(region)
    print(f"{name}: {[(x['name'], round(x['conf'],2)) for x in d]}")
print(f"inferenza totale: {time.time()-t0:.2f}s")

# ora la pipeline intera: un'unica inferenza + assegnazione per zona
dets = det.detect(img)
state = GameState(["L", "R"])
board_rect = (w//4, 0, w//2, h)
seat_rects = [(0, 0, w//4, h), (3*w//4, 0, w//4, h)]
per_seat = {}
board_dets = []
for d in dets:
    x1, y1, x2, y2 = d["box"]
    cx, cy = (x1+x2)/2, (y1+y2)/2
    assigned = None
    for i, (sx, sy, sw, sh) in enumerate(seat_rects):
        if sx <= cx <= sx+sw and sy <= cy <= sy+sh:
            assigned = i
            break
    if assigned is None:
        bx, by, bw, bh = board_rect
        if bx <= cx <= bx+bw and by <= cy <= by+bh:
            board_dets.append((d["name"], d["conf"]))
        else:
            continue
    else:
        per_seat.setdefault(assigned, []).append((d["name"], d["conf"]))

for i, items in per_seat.items():
    state.update_seat(i, items)
state.update_board(board_dets)

# simula altri 2 frame identici (debounce) per il lock
for _ in range(2):
    for i, items in per_seat.items():
        state.update_seat(i, items)
    state.update_board(board_dets)

print("\n--- Stato finale (dopo 3 frame) ---")
for i, s in state.seats.items():
    print(f"Seat {i}: {s.locked_cards()}")
print(f"Board: {state.board_cards()}")
print(f"Hero: {state.hero_cards(0)}")
print(f"Opp: {state.opponent_cards(0)}")

# reset automatico: board svuotato per 3 frame -> nuova mano
print("\n--- Simulo nuova mano (board vuoto) ---")
for _ in range(3):
    state.update_board([])
    if state.tick():
        print("RESET AUTOMATICO scattato (mano n.", state.hand_number, ")")
print(f"Board dopo reset: {state.board_cards()}")