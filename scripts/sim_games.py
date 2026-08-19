"""1000 partite simulate con mani e betting realistici, usando i componenti reali.

Ogni partita:
  - mani reali: hero random, avversari con range misti (random/tight/loose)
  - betting realistico: bui, rilanci preflop, puntate postflop 1/3..full pot,
    check, all-in occasionali, limper, posizioni casuali
  - la strada della decisione (preflop..river) e' casuale e coperta di board
  - il programma decide con equity vs RANGE (come a runtime); l'azione "perfetta"
    usa l'equity vs le MANI REALI degli avversari (informazione completa)
  - si verifica se l'azione del programma e' +EV rispetto alla realta'

Metriche: accordo programma vs perfetto, EV delle decisioni, tasso di vittoria
allo showdown, errore medio equity-range vs equity-reale.

Uso: .venv/bin/python scripts/sim_games.py [--hands 1000] [--iter 1500]
"""
from __future__ import annotations

import argparse
import functools
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from src.equity import EquityCalculator, RANGES, _combos_for  # noqa: E402
from src.strategy import Strategy  # noqa: E402

STRAT_CFG = {"raise_equity_threshold": 0.62, "fold_margin": 0.03,
             "raise_threshold": 0.60, "bet_pct": 0.66,
             "open_tiers": {"early": 7, "middle": 6, "late": 5, "blind": 6}}
RANKS = "AKQJT98765432"
SUITS = "CHSD"


def _card(rng: random.Random) -> str:
    return RANKS[rng.randrange(13)] + SUITS[rng.randrange(4)]


def _unique_cards(rng: random.Random, n: int, used: set) -> list[str]:
    out = []
    while len(out) < n:
        c = _card(rng)
        if c not in used:
            used.add(c)
            out.append(c)
    return out


def play_hand(seed: int, iterations: int) -> dict:
    rng = random.Random(seed)
    from treys import Card, Evaluator
    calc = EquityCalculator(iterations=iterations, seed=seed)
    strat = Strategy(STRAT_CFG)

    n_opp = rng.randint(1, 4)
    opp_ranges = [rng.choice(["random", "tight10", "loose25"]) for _ in range(n_opp)]
    used = set()
    hero = _unique_cards(rng, 2, used)
    opp_hands = []
    for rn in opp_ranges:
        # disegna una mano reale compatibile col range usando i nomi treys
        pool = RANGES.get(rn) or []
        found = None
        if pool:
            for _ in range(3000):
                cls = rng.choice(pool)
                c1, c2 = rng.choice(_combos_for(cls))
                n1, n2 = Card.int_to_str(c1).upper(), Card.int_to_str(c2).upper()
                if n1 not in used and n2 not in used and n1 != n2:
                    found = [n1, n2]
                    break
        if found is None:
            found = _unique_cards(rng, 2, used)
        used.update(found)
        opp_hands.append(found)
    opp_fixed = [{"cards": h, "range": None} for h in opp_hands]

    # strada della decisione e posizione
    street = rng.choice(["preflop", "flop", "turn", "river"])
    position = rng.choice(["early", "middle", "late", "blind"])
    limpers = rng.randint(0, min(2, n_opp))

    # pot preflop: bui + rilancio piu' chiamate
    raise_sz = rng.choice([3, 3, 4, 4, 5, 6, 10, 15, 25])
    to_call = raise_sz
    pot = 3 + raise_sz + raise_sz * rng.randint(0, min(2, n_opp))
    pot += limpers * raise_sz

    # board per la strada
    board = []
    n_board = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[street]
    board = _unique_cards(rng, n_board, used)

    if street != "preflop":
        # crescita postflop: puntate da 1/3 a pot, o check
        for _ in range({"flop": 1, "turn": 2, "river": 3}[street]):
            if rng.random() < 0.30:
                continue  # check
            bet = rng.choice([0.33, 0.5, 0.5, 0.66, 0.66, 1.0, 1.5, 3.0])
            amt = max(2, int(pot * bet))
            to_call = amt if rng.random() < 0.85 else 0  # a volte hero di fronte a 0 (check)
            pot += amt * rng.randint(1, min(2, n_opp))
    else:
        # preflop: a volte hero di fronte a 0 (buio gia' messo)
        if rng.random() < 0.25:
            to_call = 0

    hero_opps_range = [{"cards": None, "range": rn} for rn in opp_ranges]

    eq_range = calc.run(hero, hero_opps_range, board)["hero"]
    eq_perf = calc.run(hero, opp_fixed, board)["hero"]
    er = (eq_range["win"] + eq_range["tie"] / 2.0) / 100.0
    ep = (eq_perf["win"] + eq_perf["tie"] / 2.0) / 100.0

    ctx_base = {"hero_cards": hero, "board_cards": board, "pot": pot,
                "to_call": to_call, "street": street, "position": position,
                "limpers": limpers,
                "opponents": [{"aggression": 1.0, "range": rn} for rn in opp_ranges]}
    prog = strat.recommend({**ctx_base, "hero_equity": er})
    perf = strat.recommend({**ctx_base, "hero_equity": ep})

    pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0
    # verifica EV vs realta' (informazione completa)
    ev_ok = True
    ev_value = 0.0
    if prog["action"] == "fold":
        ev_value = 0.0
        ev_ok = ep < pot_odds + STRAT_CFG["fold_margin"]
    elif prog["action"] in ("call", "raise"):
        ev_value = ep * (pot + to_call) - to_call
        ev_ok = ev_value > -0.001

    # risoluzione allo showdown
    full = board + _unique_cards(rng, 5 - n_board, set(used) | set(board))
    ev = Evaluator()
    scores = [ev.evaluate([Card.new(c[0] + c[1].lower()) for c in hero],
                          [Card.new(c[0] + c[1].lower()) for c in full])]
    for h in opp_hands:
        scores.append(ev.evaluate([Card.new(c[0] + c[1].lower()) for c in h],
                                  [Card.new(c[0] + c[1].lower()) for c in full]))
    best = min(scores)
    hero_win = scores[0] == best and scores.count(best) == 1
    hero_tie = scores[0] == best and scores.count(best) > 1

    return {
        "street": street, "n_opp": n_opp, "pot": pot, "to_call": to_call,
        "pot_odds": pot_odds, "eq_range": er, "eq_perf": ep,
        "prog": prog["action"], "perf": perf["action"],
        "agree": prog["action"] == perf["action"],
        "ev_ok": ev_ok, "ev_value": ev_value,
        "hero_win": hero_win, "hero_tie": hero_tie,
    }


def worker(seed: int, iterations: int) -> dict:
    try:
        return play_hand(seed, iterations)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--iter", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    args = ap.parse_args()

    t0 = time.time()
    seeds = list(range(args.hands))
    run = functools.partial(worker, iterations=args.iter)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, seeds))

    stats = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    n = len(stats)
    actions = {}
    for r in stats:
        actions[r["prog"]] = actions.get(r["prog"], 0) + 1
    agree = sum(1 for r in stats if r["agree"]) / n
    ev_ok = sum(1 for r in stats if r["ev_ok"]) / n
    fold_eq = [r["eq_perf"] for r in stats if r["prog"] == "fold"]
    callraise = [r for r in stats if r["prog"] in ("call", "raise")]
    cr_eq = [r["eq_perf"] for r in callraise]
    cr_odds = [r["pot_odds"] for r in callraise]
    maes = [abs(r["eq_range"] - r["eq_perf"]) for r in stats]
    wins_all = sum(1 for r in stats if r["hero_win"]) / n
    wins_play = sum(1 for r in callraise if r["hero_win"]) / max(1, len(callraise))
    wins_fold = sum(1 for r in stats if r["prog"] == "fold" and r["hero_win"]) / max(1, len(fold_eq))

    print(f"\n=== SIMULAZIONE: {n} partite (iterazioni MC: {args.iter}, worker: {args.workers}) ===")
    print(f"Tempo: {time.time() - t0:.0f}s   Errori worker: {len(errors)}")
    print(f"\nDistribuzione strade: " +
          ", ".join(f"{s}={sum(1 for r in stats if r['street']==s)}"
                    for s in ["preflop", "flop", "turn", "river"]))
    print(f"Distribuzione azioni: " +
          ", ".join(f"{k}={v} ({v/n:.0%})" for k, v in sorted(actions.items())))
    print(f"\nAccordo programma vs azione 'perfetta' (equity reale): {agree:.1%}")
    print(f"Decisioni +EV rispetto alle mani reali: {ev_ok:.1%}")
    print(f"Fold: equity reale media {sum(fold_eq)/max(1,len(fold_eq)):.1%}  (n={len(fold_eq)})")
    print(f"Call/Raise: equity reale media {sum(cr_eq)/max(1,len(cr_eq)):.1%}  "
          f"vs pot odds media {sum(cr_odds)/max(1,len(cr_odds)):.1%}  (n={len(callraise)})")
    print(f"Errore medio equity-range vs equity-reale: {sum(maes)/n:.1%}  (mediana: {sorted(maes)[n//2]:.1%})")
    print(f"\nVittoria allo showdown: totale {wins_all:.1%} | "
          f"quando il programma diceva gioca {wins_play:.1%} | fold {wins_fold:.1%}")
    return 0 if ev_ok > 0.7 else 1


if __name__ == "__main__":
    sys.exit(main())