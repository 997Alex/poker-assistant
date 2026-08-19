"""Backtest dell'assistente: equity vs valori noti, outs/draw esatti, decisioni.

Uso: .venv/bin/python scripts/backtest.py
"""
from __future__ import annotations

import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from src.equity import EquityCalculator  # noqa: E402
from src.hand_analyzer import best_hand, outs_and_draws  # noqa: E402
from src.state_tracker import GameState  # noqa: E402
from src.strategy import Strategy, _hand_tier  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def _cards(pair: str, suited: bool = True) -> list[str]:
    s1, s2 = ("C", "C") if suited else ("C", "D")
    return [pair[0] + s1, pair[1] + s2]


def test_tier() -> None:
    print("\n[1] Tier preflop (incluse le carte 10x del modello, es. '10C')")
    cases = [
        (_cards("AA"), 9), (_cards("KK"), 9), (_cards("QQ"), 8), (_cards("JJ"), 8),
        (_cards("TT"), 7), (_cards("AK", True), 8), (_cards("AK", False), 7),
        (_cards("AQ", True), 7), (_cards("KQ", True), 6), (_cards("AJ", True), 7),
        (_cards("QJ", True), 5), (_cards("JT", True), 5), (_cards("A2", True), 4),
        (_cards("72", False), 0), (["10C", "10D"], 7), (["AC", "KD"], 7),
    ]
    for cards, exp in cases:
        try:
            got = _hand_tier(cards)
        except Exception as e:  # noqa: BLE001
            check(f"tier {cards}", False, f"CRASH {type(e).__name__}: {e}")
            continue
        check(f"tier {cards} == {exp}", got == exp, f"got {got}")


def test_equity_known() -> None:
    print("\n[2] Equity Monte Carlo vs valori noti (heads-up all-in preflop)")
    calc = EquityCalculator(iterations=40000)
    known = [
        (["AC", "AD"], [{"cards": None, "range": "random"}], [], 85.2, 1.0),   # AA vs random
        (["AC", "AD"], [{"cards": ["KC", "KD"], "range": None}], [], 81.9, 1.0),  # AA vs KK
        (["KC", "KD"], [{"cards": ["AC", "AH"], "range": None}], [], 18.1, 1.0),  # KK vs AA
        (["AC", "KD"], [{"cards": ["KC", "AD"], "range": None}], [], 50.0, 1.5),  # AK vs AK (quasi sempre patta)
        (["QC", "QD"], [{"cards": ["AC", "KS"], "range": None}], [], 57.0, 1.5),  # QQ vs AKo
    ]
    for hero, opps, board, exp, tol in known:
        t0 = time.time()
        r = calc.run(hero, opps, board)
        win = r["hero"]["win"] + r["hero"]["tie"] / 2.0
        check(f"equity {hero} -> atteso {exp}%", abs(win - exp) <= tol,
              f"got {win:.1f}% ({int((time.time()-t0)*1000)}ms)")


def test_outs_known() -> None:
    print("\n[3] Outs e disegni su esempi noti (flop)")
    # 2 carte di cuori in mano + 2 a cuori sul board = flush draw 9 outs
    od = outs_and_draws(["AH", "KH"], ["2H", "7H", "JD"])
    check("flush draw: 9 outs", od["count"] >= 9 and "Colore" in " ".join(od["draws"]),
          f"count={od['count']} draws={od['draws']}")
    # OESD: 8 outs (es. 8-9 su 6-7-2)
    od = outs_and_draws(["8C", "9D"], ["6H", "7S", "2C"])
    check("OESD: 8 outs", od["count"] >= 8 and "open-ended" in " ".join(od["draws"]),
          f"count={od['count']} draws={od['draws']}")
    # gutshot: 4 outs (es. 9-8 su 7-5-2)
    od = outs_and_draws(["9C", "8D"], ["7H", "5S", "2C"])
    check("gutshot: 4 outs", od["count"] >= 4 and "gutshot" in " ".join(od["draws"]),
          f"count={od['count']} draws={od['draws']}")
    # flush + OESD: 15 outs (es. 9h-8h su 7h-6h-2c)
    od = outs_and_draws(["9H", "8H"], ["7H", "6H", "2C"])
    check("combo flush+OESD: 15 outs", od["count"] >= 15,
          f"count={od['count']} draws={od['draws']}")
    # tris -> full/poker: 7 outs (3 del valore + 1 carta per full) piu' pair board
    od = outs_and_draws(["AH", "AD"], ["AS", "7C", "3D"])
    check("set: outs sensati", od["count"] >= 6, f"count={od['count']}")
    # edge case: 4-6-7 (buco al 5) e' un gutshot, NON un OESD
    od = outs_and_draws(["6H", "7S"], ["4C", "8D", "2H"])
    is_oesd = "open-ended" in " ".join(od["draws"])
    check("4-6-7-8 = gutshot non OESD", not is_oesd, f"draws={od['draws']}")


def test_best_hand() -> None:
    print("\n[4] Classificazione mano")
    check("doppia coppia", best_hand(["AH", "KD"], ["AC", "KS", "2D"])["category"] == "Two Pair")
    check("scala", best_hand(["9H", "8D"], ["TC", "JD", "QD"])["category"] == "Straight")
    check("colore", best_hand(["AH", "KH"], ["2H", "7H", "JH"])["category"] == "Flush")
    check("full house", best_hand(["AC", "AD"], ["AS", "KS", "KD"])["category"] == "Full House")
    check("coppia con 10x", best_hand(["10H", "10D"], ["2C", "7H", "JD"])["category"] == "Pair")


def test_strategy_sanity() -> None:
    print("\n[5] Decisioni: monotonia in equity, soglie pot odds, preflop")
    s = Strategy({"raise_equity_threshold": 0.62, "fold_margin": 0.03,
                  "raise_threshold": 0.60, "bet_pct": 0.66,
                  "open_tiers": {"early": 7, "middle": 6, "late": 5, "blind": 6}})
    base = {
        "hero_cards": ["AC", "KD"], "board_cards": ["2C", "7H", "JD"],
        "pot": 100, "to_call": 40, "street": "flop",
        "position": "middle", "opponents": [{"aggression": 1.0}],
    }
    # pot odds = 40/140 = 28.6%; call_need = 31.6%; raise_need = 60%
    for eq, exp in [(0.20, "fold"), (0.40, "call"), (0.70, "raise")]:
        r = s.recommend({**base, "hero_equity": eq})
        check(f"equity {eq:.0%} -> {exp}", r["action"] == exp, f"got {r['action']} ({r['reason'][:40]})")

    # monotonia: mai una azione piu' debole con equity maggiore
    prev = -1
    ok = True
    for i in range(5, 85, 5):
        r = s.recommend({**base, "hero_equity": i / 100.0})
        order = {"fold": 0, "check": 1, "call": 2, "raise": 3}[r["action"]]
        if order < prev:
            ok = False
            break
        prev = order
    check("monotonia equity->azione", ok)

    # to_call=0: con equity alta si punta, altrimenti check
    r = s.recommend({**base, "to_call": 0, "hero_equity": 0.70})
    check("nessuna puntata + equity alta -> raise", r["action"] == "raise", f"got {r['action']}")
    r = s.recommend({**base, "to_call": 0, "hero_equity": 0.30})
    check("nessuna puntata + equity bassa -> check", r["action"] == "check", f"got {r['action']}")

    # preflop: tier forte apre, tier debole folda, tier medio senza puntate -> check
    for cards, exp in [(["AC", "AD"], "raise"), (["7C", "2D"], "fold"), (["10C", "9D"], "check")]:
        r = s.recommend({"hero_cards": cards, "board_cards": [], "pot": 6, "to_call": 0,
                         "street": "preflop", "position": "late",
                         "opponents": [], "limpers": 0})
        check(f"preflop {cards} -> {exp}", r["action"] == exp, f"got {r['action']} ({r.get('reason','')[:40]})")


def test_state() -> None:
    print("\n[6] State tracker: debounce, unlock, reset automatico")
    st = GameState(["Hero", "A1"])
    for _ in range(2):
        st.update_seat(0, [("AC", 0.9)])
    check("carte bloccate dopo 2 frame", st.hero_cards(0) == ["AC"])
    for _ in range(6):
        st.update_seat(0, [])
    check("carte rimosse dopo 5 frame assenti", st.hero_cards(0) == [])
    # board visto poi svuotato -> reset (nuova mano)
    st.update_board([("2C", 0.9)] * 3)
    hn = st.hand_number
    for _ in range(4):
        st.update_board([])
        st.tick()
    check("reset mano quando il board si svuota", st.hand_number == hn + 1)
    # niente carte per molto tempo -> reset
    st.reset()
    hn = st.hand_number
    for _ in range(65):
        st.tick()
    check("reset dopo idle 60 frame", st.hand_number == hn + 1)


def test_mc_stability() -> None:
    print("\n[7] Riproducibilità: con seed fisso lo stesso input dà lo stesso risultato")
    calc = EquityCalculator(iterations=20000, seed=42)
    r1 = calc.run(["AC", "KD"], [{"cards": None, "range": "random"}], ["2C", "7H", "JD"])
    calc = EquityCalculator(iterations=20000, seed=42)
    r2 = calc.run(["AC", "KD"], [{"cards": None, "range": "random"}], ["2C", "7H", "JD"])
    check("equity identica con seed fisso", r1["hero"]["win"] == r2["hero"]["win"],
          f"win1={r1['hero']['win']}% win2={r2['hero']['win']}%")


def test_equity_dedup() -> None:
    print("\n[8] Equity: carte avversarie in conflitto ignorate (niente crash / risultati impossibili)")
    calc = EquityCalculator(iterations=5000)
    # avversario con la stessa carta del hero
    r = calc.run(["AC", "KD"], [{"cards": ["AC", "QD"], "range": "random"}], [])
    check("opp con carta del hero -> nessun errore", r.get("hero") is not None, str(r.get("error")))
    check("equity sensata (0..100)", 0 <= r["hero"]["win"] <= 100, f"win={r['hero']['win']}%")
    # hero e board con carte duplicate -> errore esplicito
    r = calc.run(["AC", "AD"], [], ["AC", "7H", "3D"])
    check("hero+board duplicati -> errore esplicito", r.get("error") is not None,
          f"error={r.get('error')}")


def main() -> int:
    test_tier()
    test_equity_known()
    test_outs_known()
    test_best_hand()
    test_strategy_sanity()
    test_state()
    test_mc_stability()
    test_equity_dedup()
    print(f"\n=== RISULTATO: {PASS} passati, {FAIL} falliti ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())