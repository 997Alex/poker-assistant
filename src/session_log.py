"""Log della sessione in JSONL: ogni evento di mano viene salvato per lo studio post-gioco."""
from __future__ import annotations

import json
import os
import time


class SessionLog:
    def __init__(self, logs_dir: str) -> None:
        os.makedirs(logs_dir, exist_ok=True)
        self.path = os.path.join(logs_dir, f"session_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
        self._fh = open(self.path, "a", encoding="utf-8")

    def log(self, event: str, **data) -> None:
        row = {"ts": time.time(), "event": event, **data}
        self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._fh.flush()

    def hand_start(self, hand_number: int, hero_cards, opponent_cards, board_cards) -> None:
        self.log("hand_start", hand_number=hand_number, hero_cards=hero_cards,
                 opponent_cards={str(k): v for k, v in opponent_cards.items()},
                 board_cards=board_cards)

    def analysis(self, hand_number: int, equity, recommendation, outs, hand_label,
                 pot: int, to_call: int, position: str, limpers: int) -> None:
        self.log("analysis", hand_number=hand_number, equity=equity,
                 recommendation=recommendation, outs=outs, hand_label=hand_label,
                 pot=pot, to_call=to_call, position=position, limpers=limpers)

    def hand_end(self, hand_number: int) -> None:
        self.log("hand_end", hand_number=hand_number)

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def summarize(path: str) -> None:
    """Stampa un riepilogo leggibile di una sessione JSONL."""
    import collections

    hands: dict[int, list] = collections.defaultdict(list)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row["event"] == "hand_start":
                hands.setdefault(row["hand_number"], []).append(row)
            elif row["event"] == "analysis":
                hands.setdefault(row["hand_number"], []).append(row)

    print(f"Sessione: {path}")
    print(f"Mani tracciate: {len(hands)}")
    for hn in sorted(hands):
        events = hands[hn]
        start = next((e for e in events if e["event"] == "hand_start"), None)
        an = next((e for e in events if e["event"] == "analysis"), None)
        if start and an:
            rec = an["recommendation"] or {}
            action = rec.get("action", "?")
            eq = an.get("equity") or {}
            print(f"  Mano {hn:>3}: {', '.join(start['hero_cards'] or ['—'])} | "
                  f"board {', '.join(start['board_cards'] or ['—'])} | "
                  f"win {eq.get('win', 0)}% | consiglio {action.upper()} | "
                  f"pot {an.get('pot')} call {an.get('to_call')}")