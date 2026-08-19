"""Riepilogo di una sessione di gioco dal log JSONL.

Uso: .venv/bin/python scripts/log_review.py [percorso_log.jsonl]
Senza argomenti mostra l'ultima sessione in logs/.
"""
from __future__ import annotations

import glob
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from src.session_log import summarize  # noqa: E402

LOGS = os.path.join(BASE, "logs")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(LOGS, "*.jsonl")), reverse=True)
        if not files:
            print("Nessun log trovato in", LOGS)
            sys.exit(1)
        path = files[0]
    summarize(path)