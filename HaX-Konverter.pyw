# SPDX-License-Identifier: GPL-3.0-or-later
"""Startet den HaX-Konverter per Doppelklick ohne Konsolenfenster (Windows)."""

import runpy
import sys
import traceback
from pathlib import Path


def show_start_error(details: str) -> None:
    """Startfehler sichtbar machen – pythonw hat keine Konsole."""
    title = "HaX-Konverter – Startfehler"
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, details)
        root.destroy()
        return
    except Exception:
        pass
    try:  # Tk selbst startet nicht: Windows-Meldungsfenster als Rückfall
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, details, title, 0x10)
    except Exception:
        pass


try:
    runpy.run_path(str(Path(__file__).with_name("HaX-Konverter.py")), run_name="__main__")
except Exception:
    show_start_error(traceback.format_exc())
    sys.exit(1)
