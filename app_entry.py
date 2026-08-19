"""Punto d'ingresso per l'eseguibile standalone (PyInstaller).

Reindirizza stdout/stderr nel file di log utente così gli errori non si
perdono quando il programma gira come app a finestra.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _setup_windows_dll_paths() -> None:
    """Prima di importare torch (Windows congelato): aggiunge le cartelle
    delle DLL torch al percorso di ricerca, altrimenti c10.dll fallisce con
    WinError 1114 quando una sua dipendenza non viene trovata."""
    if not (getattr(sys, "frozen", False) and sys.platform == "win32"):
        return
    base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    for sub in ("torch/lib", "torch/bin", "lib", ""):
        p = os.path.join(base, sub)
        if os.path.isdir(p):
            try:
                os.add_dll_directory(p)
            except (AttributeError, OSError):  # noqa: BLE001
                pass


_setup_windows_dll_paths()

_DEBUG_LOG = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "PokerAssistant", "boot_debug.log"
)

try:
    from src import paths  # noqa: E402
except Exception:  # noqa: BLE001
    import traceback
    try:
        os.makedirs(os.path.dirname(_DEBUG_LOG), exist_ok=True)
        with open(_DEBUG_LOG, "a") as f:
            f.write("=== import src.paths fallito ===\n")
            traceback.print_exc(file=f)
    except Exception:  # noqa: BLE001
        pass
    raise


def _redirect_console() -> None:
    log = os.path.join(paths.logs_dir(), "console.log")
    try:
        sys.stdout = open(log, "a", encoding="utf-8")
        sys.stderr = sys.stdout
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    if getattr(sys, "frozen", False):
        _redirect_console()
    try:
        from src.main import main as run
        return run()
    except Exception:  # noqa: BLE001
        import traceback
        crash = os.path.join(paths.logs_dir(), "crash.log")
        try:
            with open(crash, "a", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            try:
                os.makedirs(os.path.dirname(_DEBUG_LOG), exist_ok=True)
                with open(_DEBUG_LOG, "a") as f:
                    f.write(f"crash.log non scrivibile: {e}\n{tb}\n")
            except Exception:  # noqa: BLE001
                pass
        raise


if __name__ == "__main__":
    sys.exit(main())