#!/usr/bin/env bash
# Build PokerAssistant standalone per Linux (stesso spec di Windows).
# Prodotto: dist/PokerAssistant/PokerAssistant
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "[1/4] Creo l'ambiente virtuale..."
  python3 -m venv .venv
fi

echo "[2/4] Installo le dipendenze..."
.venv/bin/pip install --upgrade pip
echo "  - torch CPU (obbligatorio: la build CUDA rende l'exe enorme e instabile)"
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pyinstaller

echo "[3/4] Compilo l'eseguibile standalone..."
.venv/bin/pyinstaller poker-assistant.spec --noconfirm

echo "[4/4] Fatto!"
echo
echo "Eseguibile:  dist/PokerAssistant/PokerAssistant"
echo "Config e log:  ~/.poker-assistant"
echo "Suggerimento: crea un collegamento sul desktop o copia la cartella dove vuoi."