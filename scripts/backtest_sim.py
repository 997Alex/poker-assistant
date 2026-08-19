"""Simulazioni e fuzzing dell'assistente poker.

Copre:
  1. invarianti della strategia su input casuali (migliaia di casi)
  2. decisione postflop riprodotta esattamente dalla regola dichiarata
  3. equity multiway: conservazione del piatto, decremento con piu' avversari
  4. convergenza Monte Carlo (50k vs 200k iterazioni)
  5. correttezza combinazioni range (_combos_for)
  6. simulazione street-by-street: flush draw -> colore -> river

Uso: .venv/bin/python scripts/backtest_sim.py
"""
from __future__ import annotations

import os
import random
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from src.equity import EquityCalculator, _combos_for  # noqa: E402
from src.hand_analyzer import best_hand, outs_and_draws  # noqa: E402
from src.strategy import Strategy  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


STRAT_CFG = {"raise_equity_threshold": 0.62, "fold_margin": 0.03,
             "raise_threshold": 0.60, "bet_pct": 0.66,
             "open_tiers": {"early": 7, "middle": 6, "late": 5, "blind": 6}}


def reference_postflop(s: Strategy, pot, to_call, equity, street, opps, board_len):
    """Riproduce ESATTAMENTE la regola in _postflop per confrontarla col motore."""
    if to_call <= 0:
        if equity >= s.raise_equity_threshold:
            return ("raise", round(max(pot * s.bet_pct, 2.0)))
        return ("check", 0)
    pot_odds = to_call / (pot + to_call)
    agg = 1.0 if not opps else sum(float(o.get("aggression", 1.0)) for o in opps) / len(opps)
    raise_need = s.raise_threshold + 0.06 * (agg - 1.0)
    call_need = pot_odds + s.fold_margin
    if equity >= raise_need:
        return ("raise", round(max(pot * s.bet_pct, to_call * 2.0)))
    if equity >= call_need:
        if equity >= pot_odds + 0.12 and street == "river":
            return ("raise", round(max(pot * s.bet_pct, to_call * 2.0)))
        return ("call", to_call)
    return ("fold", 0)


def test_strategy_fuzz() -> None:
    print("\n[1] Fuzzing strategia: invarianti + coincidenza con la regola dichiarata")
    s = Strategy(STRAT_CFG)
    rng = random.Random(7)
    bad = 0
    for _ in range(3000):
        pot = rng.randint(10, 10000)
        to_call = rng.randint(0, pot)
        equity = rng.random()
        street = rng.choice(["flop", "turn", "river"])
        board_len = 3 if street == "flop" else 4 if street == "turn" else 5
        ranks = "AKQJT98765432"
        suits = "CHSD"
        board = [ranks[rng.randrange(13)] + suits[rng.randrange(4)]
                 for _ in range(board_len)]
        agg = round(rng.uniform(0.5, 1.5), 2)
        opps = [{"aggression": agg, "range": "random"}]
        ctx = {"hero_cards": ["AC", "KD"], "board_cards": board, "pot": pot,
               "to_call": to_call, "street": street, "hero_equity": equity,
               "position": "middle", "opponents": opps}
        rec = s.recommend(ctx)
        exp_act, exp_amt = reference_postflop(s, pot, to_call, equity, street, opps, board_len)
        if rec["action"] != exp_act or (exp_act == "raise" and rec["amount"] != exp_amt) \
                or (exp_act == "call" and rec["amount"] != to_call) \
                or (exp_act in ("fold", "check") and rec["amount"] != 0):
            bad += 1
            if bad <= 3:
                check(f"fuzz pot={pot} tc={to_call} eq={equity:.2f} street={street} agg={agg}",
                      False, f"got {rec['action']}/{rec['amount']} exp {exp_act}/{exp_amt}")
    check("3000 casi coincidono con la regola postflop", bad == 0, f"{bad} scostamenti")

    # invarianti di base
    ok = True
    for _ in range(2000):
        pot = rng.randint(1, 10000)
        to_call = rng.randint(0, pot)
        equity = rng.random()
        street = rng.choice(["preflop", "flop", "turn", "river"])
        hero = rng.sample(["AC", "KD", "2H", "QD", "TS", "9C"], 2)
        n_board = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[street]
        board = ["2C", "7H", "JD", "4S", "9D"][:n_board]
        ctx = {"hero_cards": hero, "board_cards": board,
               "pot": pot, "to_call": to_call, "street": street, "hero_equity": equity,
               "position": rng.choice(["early", "middle", "late", "blind"]),
               "opponents": [{"aggression": 1.0}]}
        rec = s.recommend(ctx)
        if rec["action"] not in ("fold", "check", "call", "raise") or rec["amount"] < 0:
            ok = False
            break
        if rec["action"] == "call" and street != "preflop" and to_call > 0 and rec["amount"] != to_call:
            ok = False
            break
        if rec["action"] == "raise" and street != "preflop" and to_call > 0 and rec["amount"] < to_call:
            ok = False
            break
    check("2000 input casuali: azioni valide, importi coerenti", ok)

    # monotonia in equity: al crescere dell'equity l'azione non si indebolisce
    mono_ok = True
    pot, to_call = 100, 40
    board = ["2C", "7H", "JD"]
    order = {"fold": 0, "check": 1, "call": 2, "raise": 3}
    prev = -1
    for eq in [e / 100 for e in range(2, 99, 2)]:
        r = s.recommend({"hero_cards": ["AC", "KD"], "board_cards": board, "pot": pot,
                         "to_call": to_call, "street": "flop", "hero_equity": eq,
                         "position": "middle", "opponents": [{"aggression": 1.0}]})
        if order[r["action"]] < prev:
            mono_ok = False
            break
        prev = order[r["action"]]
    check("monotonia equity -> azione", mono_ok)

    # pot odds crescenti: per equity fissa l'azione non deve rafforzarsi
    mono2_ok = True
    prev = 99
    for tc in range(5, 95, 5):
        r = s.recommend({"hero_cards": ["AC", "KD"], "board_cards": board, "pot": 100,
                         "to_call": tc, "street": "turn", "hero_equity": 0.40,
                         "position": "middle", "opponents": [{"aggression": 1.0}]})
        if order[r["action"]] > prev:
            mono2_ok = False
            break
        prev = order[r["action"]]
    check("pot odds crescenti -> azione non piu' forte", mono2_ok)

    # mai raise di importo inferiore al minimo dichiarato
    min_ok = True
    for _ in range(500):
        pot = rng.randint(10, 5000)
        to_call = rng.randint(1, pot)
        r = s.recommend({"hero_cards": ["AC", "KD"], "board_cards": ["2C", "7H", "JD"],
                         "pot": pot, "to_call": to_call, "street": "river",
                         "hero_equity": 0.9, "position": "middle",
                         "opponents": [{"aggression": 1.0}]})
        if r["action"] == "raise" and r["amount"] < to_call * 2:
            min_ok = False
            break
    check("raise postflop >= 2x la puntata da chiamare", min_ok)


def test_multiway() -> None:
    print("\n[2] Equity multiway: conservazione del piatto + decremento con piu' avversari")
    calc = EquityCalculator(iterations=12000, seed=11)
    hero = ["AC", "KD"]
    board = ["2C", "7H", "JD"]
    prev_avg = 100.0
    ok_conserv = True
    ok_decr = True
    for n in range(1, 6):
        opps = [{"cards": None, "range": "random", "aggression": 1.0} for _ in range(n)]
        r = calc.run(hero, opps, board)
        h = r["hero"]
        if abs(h["win"] + h["tie"] + h["lose"] - 100.0) > 0.4:
            ok_conserv = False
        total = sum(o["win"] + o["tie"] / 2.0 for o in r["opponents"])
        if abs((h["win"] + h["tie"] / 2.0) + total - 100.0) > 1.5:
            ok_conserv = False
        avg_eq = h["win"] + h["tie"] / 2.0
        print(f"    vs {n} avversari random: hero equity {avg_eq:.1f}%")
        if n > 1 and avg_eq > prev_avg + 2.5:
            ok_decr = False
        prev_avg = avg_eq
    check("win+tie+lose = 100 e piatto conservato", ok_conserv)
    check("equity hero decresce (in media) con piu' avversari", ok_decr)


def test_convergence() -> None:
    print("\n[3] Convergenza Monte Carlo: 50k vs 200k iterazioni")
    r50 = EquityCalculator(iterations=50000, seed=3).run(
        ["AC", "AD"], [{"cards": ["KC", "KD"], "range": None}], [])
    r200 = EquityCalculator(iterations=200000, seed=3).run(
        ["AC", "AD"], [{"cards": ["KC", "KD"], "range": None}], [])
    w50, w200 = r50["hero"]["win"], r200["hero"]["win"]
    check("AA vs KK stabile tra 50k e 200k", abs(w50 - w200) <= 1.0,
          f"win50k={w50}% win200k={w200}%")
    check("AA vs KK ~81.9% (200k iterazioni)", abs(w200 - 81.9) <= 0.6, f"{w200}%")


def test_combos() -> None:
    print("\n[4] Combinazioni per classe di mano (_combos_for)")
    check("coppia: 6 combo", len(_combos_for("AA")) == 6, f"{len(_combos_for('AA'))}")
    check("suited: 4 combo", len(_combos_for("AKs")) == 4, f"{len(_combos_for('AKs'))}")
    check("offsuit: 12 combo", len(_combos_for("AKo")) == 12, f"{len(_combos_for('AKo'))}")
    # tutte le combo distinte per ogni classe usata nei range
    seen_ok = True
    for cls in ["AKs", "AKo", "KQs", "KQo", "77", "T8s", "54s"]:
        cs = _combos_for(cls)
        if len(cs) != len(set(cs)):
            seen_ok = False
            break
    check("nessuna combo duplicata nei range", seen_ok)


def test_hand_simulation() -> None:
    print("\n[5] Simulazione street-by-street: flush draw -> colore -> river")
    calc = EquityCalculator(iterations=15000, seed=5)
    s = Strategy(STRAT_CFG)
    hero = ["AH", "KH"]
    opp = [{"cards": None, "range": "tight10", "aggression": 1.0}]
    pot, to_call = 100, 40

    # FLOP: Ah Kh su 2h 7h Jd -> flush draw ~50% vs range tight (2 overcard + flush)
    flop = ["2H", "7H", "JD"]
    r = calc.run(hero, opp, flop)
    eq = r["hero"]["win"] + r["hero"]["tie"] / 2.0
    rec = s.recommend({"hero_cards": hero, "board_cards": flop, "pot": pot, "to_call": to_call,
                       "street": "flop", "hero_equity": eq / 100.0, "position": "middle",
                       "opponents": opp})
    check(f"flop flush draw: equity {eq:.0f}% -> non fold", rec["action"] in ("call", "raise"),
          f"{rec['action']}")
    od = outs_and_draws(hero, flop)
    check("flop: flush draw rilevato", any("Colore" in d for d in od["draws"]),
          f"{od['draws']}")

    # TURN: arriva il colore (3h) -> equity altissima
    turn = ["2H", "7H", "JD", "3H"]
    r = calc.run(hero, opp, turn)
    eq = r["hero"]["win"] + r["hero"]["tie"] / 2.0
    rec = s.recommend({"hero_cards": hero, "board_cards": turn, "pot": pot, "to_call": to_call,
                       "street": "turn", "hero_equity": eq / 100.0, "position": "middle",
                       "opponents": opp})
    check(f"turn colore: equity {eq:.0f}% -> raise", rec["action"] == "raise", f"{rec['action']}")

    # RIVER: hero con carte basse (2-3) su board coordinato -> fold
    river = ["KH", "QD", "9S", "5D", "JC"]
    r = calc.run(["2C", "3D"], [{"cards": None, "range": "tight10", "aggression": 1.0}], river)
    eq = r["hero"]["win"] + r["hero"]["tie"] / 2.0
    rec = s.recommend({"hero_cards": ["2C", "3D"], "board_cards": river, "pot": pot, "to_call": to_call,
                       "street": "river", "hero_equity": eq / 100.0, "position": "middle",
                       "opponents": [{"cards": None, "range": "tight10", "aggression": 1.0}]})
    check(f"river carte basse: equity {eq:.0f}% -> fold", rec["action"] == "fold", f"{rec['action']}")


def test_equity_consistency() -> None:
    print("\n[6] Coerenza equity <-> mano fatta sul river")
    calc = EquityCalculator(iterations=10000, seed=9)
    cases = [
        ("poker", ["AH", "AD"], ["AS", "AC", "3D", "7S", "9C"], 90.0),
        ("scala di colore", ["9H", "8H"], ["TH", "JH", "QH", "2S", "3C"], 90.0),
        ("colore nut", ["AH", "KH"], ["2H", "7H", "JH", "4C", "9D"], 80.0),
        ("full house", ["AC", "AD"], ["AS", "KS", "KD", "2H", "3C"], 85.0),
    ]
    for name, hero, board, min_eq in cases:
        r = calc.run(hero, [{"cards": None, "range": "random", "aggression": 1.0}], board)
        eq = r["hero"]["win"] + r["hero"]["tie"] / 2.0
        bh = best_hand(hero, board)
        check(f"river {name} ({bh['category']}): equity {eq:.0f}% >= {min_eq}%", eq >= min_eq)


def reference_preflop(s: Strategy, cards, pot, to_call, position, limpers):
    from src.strategy import _hand_tier
    tier = _hand_tier(cards)
    if tier < 0:
        return ("check", 0)
    exploit = 1 if limpers > 0 else 0
    needed = s.open_tiers.get(position, 6) + exploit
    if tier >= needed:
        base = max(pot * 3.0, 3.0) if pot else 3.0
        if limpers:
            base = max(base, pot * (3.5 + limpers))
        return ("raise", max(3.0, round(base)))
    if tier >= needed - 2 and to_call > 0 and to_call <= pot * 0.5 + 1:
        return ("call", to_call)
    if tier >= needed - 3 and to_call == 0:
        return ("check", 0)
    return ("fold", 0)


def test_preflop_fuzz() -> None:
    print("\n[7] Fuzzing preflop: coincidenza con la regola dichiarata (tier, posizioni, limper)")
    s = Strategy(STRAT_CFG)
    rng = random.Random(21)
    ranks = "AKQJT98765432"
    suits = "CHSD"
    bad = 0
    for _ in range(4000):
        cards = [ranks[rng.randrange(13)] + suits[rng.randrange(4)]
                 for _ in range(2)]
        pot = rng.randint(3, 300)
        to_call = rng.randint(0, pot)
        position = rng.choice(["early", "middle", "late", "blind"])
        limpers = rng.randint(0, 4)
        ctx = {"hero_cards": cards, "board_cards": [], "pot": pot, "to_call": to_call,
               "street": "preflop", "position": position, "limpers": limpers,
               "opponents": []}
        rec = s.recommend(ctx)
        exp_act, exp_amt = reference_preflop(s, cards, pot, to_call, position, limpers)
        if rec["action"] != exp_act or rec["amount"] != exp_amt:
            bad += 1
            if bad <= 3:
                check(f"preflop {cards} pos={position} lim={limpers} pot={pot} tc={to_call}",
                      False, f"got {rec['action']}/{rec['amount']} exp {exp_act}/{exp_amt}")
    check("4000 casi preflop coincidono con la regola", bad == 0, f"{bad} scostamenti")


def main() -> int:
    test_strategy_fuzz()
    test_multiway()
    test_convergence()
    test_combos()
    test_hand_simulation()
    test_equity_consistency()
    test_preflop_fuzz()
    print(f"\n=== SIMULAZIONI: {PASS} passate, {FAIL} fallite ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())