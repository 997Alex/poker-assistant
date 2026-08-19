# Poker Assistant

Analisi poker in tempo reale per client desktop (es. 888): rileva le carte a schermo
con YOLO, le separa per soggetto (tu / avversari / board), calcola l'equity esatta
via Monte Carlo e consiglia la mossa con una strategia esploitativa.

**Nota:** l'uso di bot o assistenti automatici durante il gioco con soldi reali
viola i termini di servizio dei siti di poker. Usa questo strumento per studio
e analisi, non per automatizzare decisioni.

## Installazione

```bash
git clone <url-repo>
cd poker-assistant
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Su Windows (da cmd o PowerShell):
```bat
git clone <url-repo>
cd poker-assistant
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python src\main.py
```

Su Linux senza sudo (librerie Qt mancanti):
```bash
mkdir -p ~/xlibs && cd ~/xlibs
apt-get download libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 \
  libxcb-shape0 libxcb-util1
for f in *.deb; do dpkg -x "$f" .; done
```

> Il modello `models/poker_best.pt` (YOLO11, 5.5 MB) è incluso nella repo:
> senza bisogno di addestrare nulla, il programma funziona subito.

## Uso

```bash
./run.sh                          # avvia il programma (profilo auto-rilevato)
./run.sh --profile sisal          # forza un profilo specifico
```

### Scelta del monitor

All'avvio (solo se ci sono più display) compare la finestra **"Scegli il monitor
con il tavolo"** con l'anteprima di ogni schermo: seleziona quello dove vedi la
partita e spunta "Ricorda la scelta". La scelta viene salvata e riproposta alla
volta successiva. Il monitor dell'HUD può essere diverso (es. il tavolo sul
monitor 2, l'HUD sul monitor 1).

### Profili per piattaforma (apprendimento automatico dello scenario)

Il programma **impara da solo la disposizione del tavolo** di ogni piattaforma
(888, Sisal, play-money, PokerStars...) e la salva in `config/profiles/<nome>.json`.

- **Al primo avvio** (o premendo "Scopri tavolo automaticamente") cattura ~12 frame,
  rileva il tavolo (segmentazione verde + ellisse) e le carte (YOLO), raggruppa i
  seggiolini per clustering e propone il layout con i rettangoli colorati:
  verdi = tu, arancioni = avversari, blu = board, rosa = pot. **Confermi e dai un
  nome alla piattaforma** (es. "888", "sisal"), oppure sistemi i rettangoli a mano.
- **Alle volte successive** il profilo viene scelto automaticamente confrontando
  risoluzione e posizione del tavolo; nella HUD c'è il menu **"Piattaforma"** per
  cambiarlo al volo (ricarica le regioni senza riavviare).
- **Auto-adeguamento**: ogni N mani (default 10, `adapt_hands`) i rettangoli dei
  seggiolini vengono corretti verso la posizione media delle carte rilevate
  (max 12px a correzione, max 3 per seggiolino; `adapt_seats: false` per disattivare).
  Le correzioni sono registrate nel log di sessione.

Al primo avvio si apre la **selezione regioni**: trascina un rettangolo sul tuo
seggiolino (ruolo Hero), uno per ogni avversario, e uno sulle carte comuni.
Salva come profilo piattaforma (oppure in `config/config.json` se annulli il nome).

Nella HUD (finestra in alto):
- carte rilevate per seggiolino e board
- equity: Vittoria / Pareggio / Sconfitta (Monte Carlo)
- **mano corrente** (Coppia, Scala...) + **draw e outs esatti** (es. gutshot 4 outs)
- mossa consigliata con sizing e motivazione
- **Pot** e **Da chiamare**: pulsanti −/+ con step rapido (oppure OCR opzionale
  dell'area pot se selezioni il ruolo "Pot" e installi easyocr)
- **Posizione** (early/middle/late/blind) e **limper** da selezionare a ogni mano
  (influenzano i range preflop)
- **Reset mano** per azzerare la sessione (il reset è comunque automatico
  quando il board si svuota, ossia inizia una nuova mano)

### Log di sessione

Ogni mano viene registrata in `logs/session_*.jsonl` (carte, equity, outs,
consiglio, pot). Riepilogo a fine sessione:

```bash
.venv/bin/python scripts/log_review.py            # ultima sessione
.venv/bin/python scripts/log_review.py logs/session_XXX.jsonl
```

### Calibrazione

`config/config.json` → `settings`:
- `conf_threshold`: soglia confidenza YOLO (0.6 default; 0.5 se molte carte non viste)
- `imgsz`: risoluzione inferenza (640 veloce / 960 preciso)
- `mc_iterations`: iterazioni Monte Carlo (30000 default)
- `position`: early/middle/late/blind (impatto sui range preflop)
- soglie esploitative: `raise_equity_threshold`, `fold_margin`, `raise_threshold`, `bet_pct`
- per seggiolino: `range` = random/tight10/loose25/loose50,
  `aggression` = 0.8 (passivo) ... 1.2 (aggressivo)

### Fine-tuning sulle carte della tua piattaforma

1. `./run.sh` → con la partita aperta lancia
   `scripts/capture_training.py` e gioca qualche mano (salva i crop in `dataset/crops/`)
2. `scripts/finetune.py --epochs 30` (su GPU/Colab: installa ultralytics, carica i crop,
   esegui lo script) → produce `models/poker_best_ft.pt`
3. sostituisci `models/poker_best.pt` con il modello fine-tunato

## Eseguibile standalone (Windows e Linux)

L'app può essere compilata in un eseguibile autonomo con tutte le dipendenze
(2 GB circa) tramite PyInstaller. Lo spec è lo stesso per entrambi i sistemi.

### Windows (exe)

Requisiti: Python 3.10–3.12 a 64 bit (da python.org, con "py" nel PATH).

1. Copia la cartella del progetto sul PC Windows
2. Doppio click su `build_windows.bat` (crea il venv, installa torch CPU + dipendenze, compila)
3. L'eseguibile è in `dist\PokerAssistant\PokerAssistant.exe` — **copia l'intera cartella**
   `dist\PokerAssistant` dove vuoi (desktop, USB...) e crea un collegamento all'exe

Config, profili e log finiscono in `%APPDATA%\PokerAssistant`; in caso di errori
controlla `%APPDATA%\PokerAssistant\logs\crash.log`.

### Linux

```bash
./build_linux.sh
./dist/PokerAssistant/PokerAssistant   # o doppio click
```

Config, profili e log finiscono in `~/.poker-assistant/`.

### Note di build

- `torch` va installato **solo in versione CPU** (lo fanno gli script): la build
  CUDA pesa il doppio e non serve su macchine senza GPU dedicata.
- Il modello `models/poker_best.pt` è incluso nell'eseguibile; per usare un
  modello fine-tunato, sostituiscilo **prima** di compilare.
- Primo avvio su una macchina nuova: nessun profilo → si apre la finestra
  "Scopri tavolo automaticamente".

## Test

```bash
.venv/bin/python scripts/integration_test.py <immagine>   # rilevamento + stato
.venv/bin/python scripts/e2e_test.py                      # pipeline completa (GUI simulata)
.venv/bin/python scripts/gui_smoke_test.py                # apertura GUI
.venv/bin/python scripts/test_scenario.py                 # scenario learning (tavolo sintetico)
.venv/bin/python scripts/auto_learn.py sisal --frames 15  # apprendi il layout dalla CLI
```

## Struttura

```
src/
  main.py           loop: cattura -> YOLO -> stato -> equity -> consiglio -> HUD
  table_detector.py rilevamento automatico tavolo/seggiolini/board (scenario learning)
  profiles.py       profili per piattaforma + auto-selezione
  seat_config.py    selezione regioni + apprendimento automatico con anteprima
  monitor_picker.py scelta del monitor all'avvio con anteprima
  capture.py        cattura schermo (mss, multi-monitor)
  detector.py       YOLO 52 classi, deduplicazione box
  state_tracker.py  stato carte per soggetto, debounce, reset automatico mano
  equity.py         Monte Carlo con treys + range avversari
  strategy.py       motore esploitativo (preflop range + pot odds postflop)
  hud.py            finestra overlay sempre in primo piano (menu Piattaforma)
  qt_env.py         fix plugin Qt (cv2)
models/             poker_best.pt (YOLO11, MIT — Gholamrezadar, incluso nella repo)
scripts/            test + cattura dati + fine-tuning + auto-learn
config/profiles/    profili per piattaforma (<nome>.json) — dati utente, NON in git
config/config.json  configurazione legacy (migrata al primo avvio)
```

> `config/`, `logs/` e i venv sono esclusi dalla repo: ogni PC crea i propri
> profili al primo avvio con l'apprendimento automatico del tavolo.