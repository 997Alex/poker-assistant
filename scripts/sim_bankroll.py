"""Simulazione di sessione cash game: 1000 partite, capitale 50€, regole 888poker.

Unita' = big blind. Stakes NL25 (SB 0.10€ / BB 0.25€) -> 50€ = 200BB.
Regole 888poker modellate:
  - bui SB 0.5 / BB 1
  - buy-in massimo 100BB, minimo 40BB; ricompra a 100BB quando si scende sotto 40BB
  - rake 5% del piatto (cap 4BB) SOLO se il flop e' stato distribuito (no-flop no-drop)
  - NL hold'em standard: check/call/raise, all-in, showdown

Ogni mano usa le stesse carte hero/avversari (stessi seed) della simulazione
scripts/sim_games.py; il betting e' street-by-street con le decisioni REALI del
bot (equity Monte Carlo vs range ad ogni strada) e avversari che callano/
foldano/rilanciano in base alla forza della loro mano.

Uso: .venv/bin/python scripts/sim_bankroll.py [--hands 1000] [--iter 1500] [--workers 8]
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from treys import Card, Evaluator  # noqa: E402

from src.equity import EquityCalculator, RANGES, _combos_for  # noqa: E402
from src.strategy import Strategy, _hand_tier  # noqa: E402

STRAT_CFG = {"raise_equity_threshold": 0.62, "fold_margin": 0.03,
             "raise_threshold": 0.60, "bet_pct": 0.66,
             "open_tiers": {"early": 7, "middle": 6, "late": 5, "blind": 6}}
RANKS = "AKQJT98765432"
SUITS = "CHSD"

SB, BB = 0.5, 1.0
BUYIN = 100.0
MIN_STACK = 40.0
START_BANKROLL = 200.0          # 50€ @ NL25 (BB 0.25€)
RAKE_PCT = 0.05
RAKE_CAP = 4.0

EVAL = Evaluator()


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


def deal_hands(rng: random.Random):
    """Stessa sequenza di carte di scripts/sim_games.py (stessi seed)."""
    n_opp = rng.randint(1, 4)
    opp_ranges = [rng.choice(["random", "tight10", "loose25"]) for _ in range(n_opp)]
    used = set()
    hero = _unique_cards(rng, 2, used)
    opp_hands = []
    for rn in opp_ranges:
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
    board5 = _unique_cards(rng, 5, used)
    return n_opp, opp_ranges, hero, opp_hands, board5


def _tc(c: str) -> int:
    return Card.new(c[0] + c[1].lower())


def _strength(cards: list[str], board: list[str]) -> int:
    """Classe treys 0..8 (0 high, 1 pair, 2 two pair, 3 trips, 4 straight,
    5 flush, 6 full, 7 quads, 8 straight flush)."""
    if not board:
        return _hand_tier(cards)
    score = EVAL.evaluate([_tc(c) for c in cards], [_tc(c) for c in board])
    return EVAL.get_rank_class(score)


def _pay(player: dict, amount: float) -> bool:
    """Mette chips nel piatto (cappato allo stack). True se va all-in."""
    if amount <= 0:
        return player["allin"]
    pay = min(amount, player["stack"])
    player["comm"] += pay
    player["stack"] -= pay
    if player["stack"] <= 0.0001:
        player["allin"] = True
    return player["allin"]


def _pot(opps, hero_st) -> float:
    return sum(o["comm"] for o in opps) + hero_st["comm"]


def play_hand(seed: int, iterations: int, stack0: float, debug: bool = False) -> dict:
    rng = random.Random(seed)
    n_opp, opp_ranges, hero, opp_hands, board5 = deal_hands(rng)
    calc = EquityCalculator(iterations=iterations, seed=seed)
    strat = Strategy(STRAT_CFG)

    position = rng.choice(["early", "middle", "late", "blind"])
    limpers = rng.randint(0, min(2, n_opp))
    blind_pay = rng.choice([0.0, 0.5, 1.0])
    raise_sz = rng.choice([2.5, 3, 3, 3.5, 4, 4, 5, 6])

    hero_st = {"comm": 0.0, "stack": stack0, "allin": False}
    opps = [{"comm": 0.0, "stack": BUYIN, "allin": False, "cards": h, "range": rn,
             "in": True}
            for h, rn in zip(opp_hands, opp_ranges)]

    # bui
    hero_st["comm"] = blind_pay
    hero_st["stack"] -= blind_pay
    if n_opp == 1:
        _pay(opps[0], 1.5)
    elif blind_pay == 0.0:
        _pay(opps[0], 1.0)
        _pay(opps[1], 0.5)
    elif blind_pay == 0.5:
        _pay(opps[0], 1.0)
    else:
        _pay(opps[0], 0.5)

    def make_ctx(cards, to_call, equity=None):
        c = {"hero_cards": hero, "board_cards": cards, "pot": _pot(opps, hero_st),
             "to_call": to_call,
             "street": "preflop" if not cards else
             ("flop" if len(cards) == 3 else "turn" if len(cards) == 4 else "river"),
             "position": position, "limpers": limpers,
             "opponents": [{"aggression": 1.0, "range": rn} for rn in opp_ranges]}
        if equity is not None:
            c["hero_equity"] = equity
        return c

    stats = {"seed": seed, "street_end": "preflop", "showdown": False,
             "hero_win": False, "rake": 0.0, "net": 0.0,
             "n_opp": n_opp, "position": position}

    if debug:
        def dbg(msg):
            print(f"  [{hero_st['stack']:6.1f}BB] {msg}  (comm hero={hero_st['comm']:.1f}, "
                  f"pot={_pot(opps, hero_st):.1f})")
        dbg(f"hero={hero} opp={opp_hands} ranges={opp_ranges} board={board5} "
            f"pos={position} blind={blind_pay} limpers={limpers}")
        dbg(f"PREFLOP: raiser bet={raise_sz}, to_call={max(0.0, raise_sz - blind_pay)}")

    def hero_wins(msg):
        hero_st["stack"] += _pot(opps, hero_st)
        stats["street_end"] = msg
        stats["net"] = _pot(opps, hero_st) - hero_st["comm"]
        return stats

    # ---- PREFLOP ----
    if blind_pay == 1.0 and rng.random() < 0.12:
        return hero_wins("preflop_blinds")  # tutti foldano al buio di hero

    raiser = rng.randrange(n_opp)
    in_hand = []
    for i, o in enumerate(opps):
        if i == raiser:
            _pay(o, raise_sz - o["comm"])
            in_hand.append(i)
        elif rng.random() < 0.4:
            _pay(o, raise_sz - o["comm"])
            in_hand.append(i)
        else:
            o["in"] = False  # folda: i bui restano nel piatto

    to_call = max(0.0, raise_sz - blind_pay)
    rec = strat.recommend(make_ctx([], to_call))
    if debug:
        dbg(f"  -> preflop: {rec['action']} {rec.get('amount', 0)}")
    if rec["action"] == "fold":
        stats["net"] = -hero_st["comm"]
        stats["street_end"] = "preflop_fold"
        return stats
    if rec["action"] == "raise":
        _pay(hero_st, max(rec["amount"], to_call + 1))
        last_aggr = "hero"
        # avversari rispondono al rilancio
        survivors = []
        for i in in_hand:
            o = opps[i]
            if o["allin"]:
                survivors.append(i)
                continue
            st = _hand_tier(o["cards"])
            if st >= 7:
                act = "raise" if rng.random() < 0.35 else "call"
            elif st >= 4:
                act = "call" if rng.random() < 0.6 else "fold"
            else:
                act = "call" if rng.random() < 0.2 else "fold"
            if act == "fold":
                continue
            if act == "raise":
                r2 = min(rec["amount"] * 1.6, o["stack"] + o["comm"])
                _pay(o, max(0.0, r2 - o["comm"]))
                _pay(hero_st, max(0.0, r2 - hero_st["comm"]))
            else:
                _pay(o, max(0.0, rec["amount"] - o["comm"]))
            survivors.append(i)
        in_hand = survivors
    else:  # call o check
        if rec["action"] == "call":
            _pay(hero_st, to_call)
        last_aggr = raiser

    if not in_hand:
        return hero_wins("preflop_foldwin")

    # cappo a 2 avversari postflop
    while len(in_hand) > 2:
        drop = rng.choice(in_hand)
        in_hand.remove(drop)
        opps[drop]["in"] = False

    allin_any = hero_st["allin"] or any(opps[i]["allin"] for i in in_hand)
    board_revealed = []

    # ---- POSTFLOP ----
    for street_idx, ncards in enumerate((3, 4, 5)):
        if not in_hand:
            break
        board_revealed = board5[:ncards]
        stats["street_end"] = ("flop" if ncards == 3 else "turn" if ncards == 4 else "river")

        if allin_any:
            continue  # check-down fino allo showdown

        lead_opps = [i for i in in_hand if not opps[i]["allin"]]
        if last_aggr == "hero" or not lead_opps:
            # hero ha l'iniziativa: decide con to_call=0
            er = calc.run(hero, [{"cards": None, "range": rn} for rn in opp_ranges],
                          board_revealed)["hero"]
            er = (er["win"] + er["tie"] / 2.0) / 100.0
            rec = strat.recommend(make_ctx(board_revealed, 0, er))
            if debug:
                dbg(f"{stats['street_end']} hero lead: equity={er:.0%} -> {rec['action']} {rec.get('amount', 0)}")
            if rec["action"] in ("check", "fold"):
                last_aggr = None
                continue
            _pay(hero_st, max(rec["amount"], 1.0))
            last_aggr = "hero"
            survivors = []
            for i in in_hand:
                o = opps[i]
                if o["allin"]:
                    survivors.append(i)
                    continue
                cls = _strength(o["cards"], board_revealed)
                if cls >= 5:
                    act = "raise" if rng.random() < 0.5 else "call"
                elif cls >= 4:
                    r = rng.random()
                    act = "raise" if r < 0.2 else "call" if r < 0.8 else "fold"
                elif cls >= 2:
                    act = "call" if rng.random() < 0.55 else "fold"
                elif cls == 1:
                    act = "call" if rng.random() < 0.4 else "fold"
                else:
                    act = "call" if rng.random() < 0.3 else "fold"
                if act == "fold":
                    continue
                if act == "raise":
                    r2 = min(rec["amount"] + round(_pot(opps, hero_st) * 0.5),
                             o["stack"] + o["comm"])
                    _pay(o, max(0.0, r2 - o["comm"]))
                    _pay(hero_st, max(0.0, r2 - hero_st["comm"]))
                else:
                    _pay(o, max(0.0, rec["amount"] - o["comm"]))
                survivors.append(i)
            in_hand = survivors
            if not in_hand:
                return hero_wins(f"{stats['street_end']}_foldwin")
        else:
            # un avversario punta
            lead = max(lead_opps, key=lambda i: _strength(opps[i]["cards"], board_revealed))
            if rng.random() < 0.2 and _strength(opps[lead]["cards"], board_revealed) <= 3:
                lead = rng.choice(lead_opps)
            cls = _strength(opps[lead]["cards"], board_revealed)
            if cls >= 4:
                bet = round(0.75 * _pot(opps, hero_st)) if rng.random() < 0.9 else 0
            elif cls >= 2:
                bet = round(0.5 * _pot(opps, hero_st)) if rng.random() < 0.8 else 0
            elif cls == 1:
                bet = round(0.5 * _pot(opps, hero_st)) if rng.random() < 0.5 else 0
            else:
                bet = round(0.5 * _pot(opps, hero_st)) if rng.random() < 0.3 else 0
            if bet == 0:
                last_aggr = None
                continue
            _pay(opps[lead], min(bet, opps[lead]["stack"]))
            # altri avversari (non-lead) rispondono alla puntata
            survivors = [lead]
            for i in in_hand:
                if i == lead or opps[i]["allin"]:
                    if i != lead:
                        survivors.append(i)
                    continue
                o = opps[i]
                cls2 = _strength(o["cards"], board_revealed)
                call = rng.random() < (0.6 if cls2 >= 2 else 0.4 if cls2 == 1 else 0.25)
                if call:
                    _pay(o, min(bet, o["stack"]))
                    survivors.append(i)
            in_hand = survivors

            # hero decide
            er = calc.run(hero, [{"cards": None, "range": rn} for rn in opp_ranges],
                          board_revealed)["hero"]
            er = (er["win"] + er["tie"] / 2.0) / 100.0
            to_call = min(bet, hero_st["stack"])
            rec = strat.recommend(make_ctx(board_revealed, to_call, er))
            if debug:
                dbg(f"{stats['street_end']} vs bet {bet:.1f}: equity={er:.0%} pot_odds={to_call/(_pot(opps, hero_st)+to_call):.0%} "
                    f"-> {rec['action']} {rec.get('amount', 0)}")
            if rec["action"] == "fold":
                stats["net"] = -hero_st["comm"]
                stats["street_end"] = f"{stats['street_end']}_fold"
                return stats
            if rec["action"] == "call":
                _pay(hero_st, to_call)
                last_aggr = lead
            else:
                _pay(hero_st, max(rec["amount"], to_call + 1))
                last_aggr = "hero"
                survivors = []
                for i in in_hand:
                    o = opps[i]
                    if o["allin"]:
                        survivors.append(i)
                        continue
                    cls3 = _strength(o["cards"], board_revealed)
                    if cls3 >= 5:
                        act = "raise" if rng.random() < 0.5 else "call"
                    elif cls3 >= 4:
                        r = rng.random()
                        act = "raise" if r < 0.2 else "call" if r < 0.8 else "fold"
                    elif cls3 >= 2:
                        act = "call" if rng.random() < 0.55 else "fold"
                    else:
                        act = "call" if rng.random() < 0.35 else "fold"
                    if act == "fold":
                        continue
                    if act == "raise":
                        r2 = min(rec["amount"] + round(_pot(opps, hero_st) * 0.5),
                                 o["stack"] + o["comm"])
                        _pay(o, max(0.0, r2 - o["comm"]))
                        _pay(hero_st, max(0.0, r2 - hero_st["comm"]))
                    else:
                        _pay(o, max(0.0, rec["amount"] - o["comm"]))
                    survivors.append(i)
                in_hand = survivors
                if not in_hand:
                    return hero_wins(f"{stats['street_end']}_foldwin")

        allin_any = hero_st["allin"] or any(opps[i]["allin"] for i in in_hand)

    # ---- SHOWDOWN ----
    pot = _pot(opps, hero_st)
    if not in_hand:
        return hero_wins("showdown_foldwin")
    stats["showdown"] = True
    rake = 0.0
    if len(board_revealed) >= 3:
        rake = min(RAKE_CAP, round(RAKE_PCT * pot, 2))
    scores = {"hero": EVAL.evaluate([_tc(c) for c in hero], [_tc(c) for c in board5])}
    for i in in_hand:
        scores[i] = EVAL.evaluate([_tc(c) for c in opps[i]["cards"]], [_tc(c) for c in board5])
    best = min(scores.values())
    winners = [k for k, v in scores.items() if v == best]
    win_share = (pot - rake) / len(winners)
    stats["rake"] = rake
    if "hero" in winners:
        hero_st["stack"] += win_share
        stats["hero_win"] = True
        stats["net"] = win_share - hero_st["comm"]
    else:
        stats["net"] = -hero_st["comm"]
    return stats


def worker(args) -> dict:
    seed, iterations, stack0 = args
    try:
        return play_hand(seed, iterations, stack0)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "seed": seed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--iter", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args()

    stack = BUYIN
    reserve = START_BANKROLL - BUYIN
    t0 = time.time()
    total_rake = 0.0
    hands_done = 0
    showdowns = 0
    wins = 0
    preflop_folds = 0

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for bstart in range(0, args.hands, 50):
            batch = list(range(bstart + args.seed_offset, min(bstart + 50, args.hands) + args.seed_offset))
            results = list(pool.map(worker, [(s, args.iter, stack) for s in batch]))
            for r in results:
                if "error" in r:
                    print(f"  ERRORE hand {r['seed']}: {r['error']}")
                    continue
                hands_done += 1
                stack += r["net"]
                total_rake += r["rake"]
                if r["showdown"]:
                    showdowns += 1
                if r["hero_win"]:
                    wins += 1
                if r["street_end"] == "preflop_fold":
                    preflop_folds += 1
                # ricompra (regole 888: max 100BB, min 40BB)
                if stack < MIN_STACK:
                    need = BUYIN - stack
                    use = min(need, reserve)
                    stack += use
                    reserve -= use
                if stack <= 0 and reserve <= 0:
                    break
            if stack <= 0 and reserve <= 0:
                print("  (sessione terminata: bankroll esaurito)")
                break

    final = stack + reserve
    bb100 = (final - START_BANKROLL) / (hands_done / 100.0)
    print(f"\n=== SESSIONE CASH GAME (regole 888poker, NL25: 0.10€/0.25€, max buy-in 100BB) ===")
    print(f"Capitale iniziale: {START_BANKROLL:.0f}BB = {START_BANKROLL * 0.25:.2f}€  (2 buy-in da 100BB)")
    print(f"Mani giocate: {hands_done}/{args.hands}   Tempo: {time.time() - t0:.0f}s")
    print(f"\nCapitale finale:  {final:.2f}BB = {final * 0.25:.2f}€")
    print(f"  stack in gioco: {stack:.2f}BB | riserva: {reserve:.2f}BB")
    print(f"Risultato sessione: {final - START_BANKROLL:+.2f}BB "
          f"({(final - START_BANKROLL) * 0.25:+.2f}€)  = {bb100:+.2f} bb/100")
    print(f"Rake pagato: {total_rake:.2f}BB ({total_rake * 0.25:.2f}€)")
    if hands_done:
        print(f"Showdown: {showdowns} ({showdowns / hands_done:.0%}) | vinti da hero: {wins} "
              f"({wins / max(1, showdowns):.0%} degli showdown) | fold preflop: {preflop_folds}")
    return 0


if __name__ == "__main__":
    sys.exit(main())