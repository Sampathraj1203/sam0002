"""Console calculator: works in a terminal and in Google Colab (python -m sam_calculator --cli)."""
from __future__ import annotations

import getpass
from typing import Callable

from .auth import AccountStore, AuthError
from .engine import CalcError, calculate

HELP = """Type a calculation and press Enter, for example:
  12+30        2.5*-4        (1+2)*3       2^10        200*10%       sqrt(16)   or   √16
Commands: history, clear (clears history), help, quit"""


def _sign_in(store: AccountStore, ask: Callable[[str], str], ask_secret: Callable[[str], str],
             out: Callable[[str], None]) -> str | None:
    demo = store.demo_accounts()
    try:
        first_run = not demo and not store.has_accounts()
    except AuthError as exc:  # e.g. a damaged accounts file
        out(str(exc))
        return None
    if demo:
        out("Demo accounts: " + ", ".join(f"{u} / {p}" for u, p in demo) + "  (press Enter to use the first)")
    elif first_run:
        out("No account yet - create one.")
        while True:
            try:
                name = store.create(ask("New username: "), ask_secret("New password: "),
                                    ask_secret("Repeat password: "))
                out(f"Account '{name}' created.")
                break
            except AuthError as exc:
                out(f"  {exc}")
    while True:
        default_user, default_password = demo[0] if demo else ("", "")
        user = ask(f"Username [{default_user}]: " if default_user else "Username: ").strip() or default_user
        password = ask_secret("Password (Enter = demo password): " if default_password else "Password: ")
        if not password and default_password and user.lower() == default_user:
            password = default_password
        try:
            return store.login(user, password)
        except AuthError as exc:
            out(f"  {exc}")
            if str(exc).startswith(("Too many attempts", "Cannot ")):
                return None  # locked (the lock is saved, so a restart waits too) or the data folder is unusable


def run(store: AccountStore, *, ask: Callable[[str], str] = input,
        ask_secret: Callable[[str], str] = getpass.getpass, out: Callable[[str], None] = print) -> int:
    out("Welcome to SAM Calculator!")
    try:
        name = _sign_in(store, ask, ask_secret, out)
        if name is None:
            return 1
        out(f"Signed in as {name}. {HELP}")
        history: list[str] = []
        while True:
            line = ask("calc> ").strip()
            command = line.lower()
            if not line:
                continue
            if command in ("quit", "exit", "q"):
                out("Goodbye!")
                return 0
            if command == "help":
                out(HELP)
            elif command == "history":
                out("\n".join(history[-20:]) if history else "(no calculations yet)")
            elif command == "clear":
                history.clear()
                out("History cleared.")
            else:
                try:
                    result = calculate(line)
                except CalcError as exc:
                    out(f"Error: {exc}")
                else:
                    history.append(f"{line} = {result}")
                    out(f"= {result}")
    except (EOFError, KeyboardInterrupt):
        out("\nGoodbye!")
        return 0
