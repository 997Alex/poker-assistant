#!/usr/bin/env bash
# Poker Assistant launcher — imposta l'ambiente (X11 libs locali) e avvia il programma
cd "$(dirname "$0")"
export LD_LIBRARY_PATH="$HOME/xlibs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec .venv/bin/python -m src.main "$@"