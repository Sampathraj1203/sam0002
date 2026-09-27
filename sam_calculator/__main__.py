"""python -m sam_calculator [--cli] [--no-demo] [--data-dir DIR]"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, cli
from .auth import AccountStore, default_data_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sam_calculator", description="SAM Calculator: desktop calculator with sign-in")
    parser.add_argument("--cli", action="store_true", help="run in the console instead of a window (also used when no display is available)")
    parser.add_argument("--no-demo", action="store_true", help="hide and refuse the demo accounts (for real use); SAM_DEMO=0 does the same")
    parser.add_argument("--data-dir", type=Path, help=f"where accounts are stored (default {default_data_dir()})")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    demo = not args.no_demo and os.environ.get("SAM_DEMO", "1") != "0"
    store = AccountStore((args.data_dir / "accounts.json") if args.data_dir else None, demo=demo)
    if args.cli:
        return cli.run(store)
    try:
        import tkinter

        from .gui import CalculatorApp
    except ImportError as exc:  # Python built without Tk
        print(f"Tkinter is not available ({exc}); starting the console calculator.")
        return cli.run(store)
    try:
        app = CalculatorApp(store)
    except tkinter.TclError as exc:  # no display, e.g. Colab or a headless server
        print(f"Cannot open a window ({exc}); starting the console calculator.")
        root = getattr(tkinter, "_default_root", None)
        if root is not None:
            root.destroy()
        return cli.run(store)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
