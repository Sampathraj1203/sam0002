"""Desktop window (Tkinter, built into Python): sign-in screen, calculator keypad, live preview and history."""
from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from typing import Callable

from .auth import AccountStore, AuthError
from .engine import MAX_LENGTH, CalcError, evaluate, format_number

C = {"bg": "#15161c", "panel": "#1f2029", "field": "#2a2c38", "text": "#eef0f4", "dim": "#8c90a0",
     "accent": "#ff9f1c", "equals": "#2ec4b6", "error": "#ff5d73", "key": "#2a2c38", "func": "#3a3d4d"}
FONT = "Segoe UI"
MONO = "Consolas"
KEYS = (
    ("C", "⌫", "(", ")", "÷"),
    ("7", "8", "9", "×", "√"),
    ("4", "5", "6", "−", "^"),
    ("1", "2", "3", "+", "%"),
    ("±", "0", ".", "="),          # "=" spans the last two columns
)
OPERATORS = {"÷", "×", "−", "+", "^", "%", "√"}
MAX_HISTORY = 200


def _matching_bracket(text: str, open_index: int) -> int:
    """Index of the ')' that closes the '(' at open_index, or -1."""
    depth = 0
    for i in range(open_index, len(text)):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return i
    return -1


def _lighter(hex_color: str, amount: int = 22) -> str:
    r, g, b = (min(255, int(hex_color[i:i + 2], 16) + amount) for i in (1, 3, 5))
    return f"#{r:02x}{g:02x}{b:02x}"


def _button(parent: tk.Misc, text: str, command: Callable[[], None], *, bg: str, fg: str = C["text"],
            font: tuple = (FONT, 16)) -> tk.Button:
    button = tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=_lighter(bg),
                       activeforeground=fg, relief="flat", bd=0, highlightthickness=0, font=font, cursor="hand2")
    button.bind("<Enter>", lambda _e: button.config(bg=_lighter(bg)) if button["state"] == "normal" else None)
    button.bind("<Leave>", lambda _e: button.config(bg=bg))
    return button


def _entry(parent: tk.Misc, *, show: str = "", font: tuple = (FONT, 13), justify: str = "left") -> tk.Entry:
    return tk.Entry(parent, show=show, font=font, justify=justify, bg=C["field"], fg=C["text"],
                    insertbackground=C["text"], relief="flat", highlightthickness=1,
                    highlightbackground=C["field"], highlightcolor=C["accent"])


class LoginFrame(tk.Frame):
    """Sign in, or create an account. In demo mode the first demo account is pre-filled and stays filled."""

    def __init__(self, master: tk.Misc, store: AccountStore, on_success: Callable[[str], None]):
        super().__init__(master, bg=C["bg"])
        self.store = store
        self.on_success = on_success
        self.mode = "signin"
        self._tick: str | None = None

        card = tk.Frame(self, bg=C["panel"], padx=34, pady=28)
        card.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(card, text="SAM Calculator", font=(FONT, 22, "bold"), bg=C["panel"], fg=C["text"]).pack(anchor="w")
        self.subtitle = tk.Label(card, font=(FONT, 11), bg=C["panel"], fg=C["dim"])
        self.subtitle.pack(anchor="w", pady=(0, 16))

        tk.Label(card, text="Username", font=(FONT, 10), bg=C["panel"], fg=C["dim"]).pack(anchor="w")
        self.user = _entry(card)
        self.user.pack(fill="x", ipady=6, pady=(2, 10))
        tk.Label(card, text="Password", font=(FONT, 10), bg=C["panel"], fg=C["dim"]).pack(anchor="w")
        self.password = _entry(card, show="•")
        self.password.pack(fill="x", ipady=6, pady=(2, 10))
        self.confirm_label = tk.Label(card, text="Repeat password", font=(FONT, 10), bg=C["panel"], fg=C["dim"])
        self.confirm = _entry(card, show="•")

        self.button = _button(card, "Sign in", self.submit, bg=C["accent"], fg="#15161c", font=(FONT, 12, "bold"))
        self.button.pack(fill="x", ipady=6, pady=(6, 6))
        self.message = tk.Label(card, text="", font=(FONT, 10), bg=C["panel"], fg=C["error"], wraplength=300,
                                justify="left")
        self.message.pack(anchor="w")
        self.switch = tk.Label(card, font=(FONT, 10, "underline"), bg=C["panel"], fg=C["accent"], cursor="hand2")
        self.switch.pack(anchor="w", pady=(6, 0))
        self.switch.bind("<Button-1>", lambda _e: self.set_mode("signup" if self.mode == "signin" else "signin"))

        self.demo_box = tk.Frame(card, bg=C["panel"])
        if store.demo_accounts():
            self.demo_box.pack(fill="x", pady=(16, 0))
            tk.Label(self.demo_box, text="Demo accounts (click to fill)", font=(FONT, 10), bg=C["panel"],
                     fg=C["dim"]).pack(anchor="w")
            for name, secret in store.demo_accounts():
                _button(self.demo_box, f"{name} / {secret}", lambda n=name, s=secret: self.fill(n, s),
                        bg=C["field"], font=(MONO, 10)).pack(fill="x", pady=2, ipady=2)

        for widget in (self.user, self.password, self.confirm):
            widget.bind("<Return>", lambda _e: self.submit())
        self.reset()

    def fill(self, name: str, secret: str) -> None:
        for widget, value in ((self.user, name), (self.password, secret)):
            widget.delete(0, "end")
            widget.insert(0, value)

    def clear_fields(self) -> None:
        for widget in (self.user, self.password, self.confirm):
            widget.delete(0, "end")

    def reset(self) -> None:
        """Back to the start (also after logout): nothing of the last user is left in the form. In demo mode the
        first demo account is filled in again; without demo accounts and no saved account, show sign-up."""
        try:
            first_run = not self.store.demo_accounts() and not self.store.has_accounts()
        except AuthError as exc:
            first_run = False
            self.after_idle(lambda: self.message.config(text=str(exc), fg=C["error"]))
        self.set_mode("signup" if first_run else "signin")
        self._countdown()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        signup = mode == "signup"
        self.clear_fields()  # never carry a (hidden) demo or previous password into the other form
        demo = self.store.demo_accounts()
        if not signup and demo:
            self.fill(*demo[0])
        self.subtitle.config(text="Create your account" if signup else "Sign in to continue")
        self.button.config(text="Create account" if signup else "Sign in")
        self.switch.config(text="Have an account? Sign in" if signup else "New here? Create an account")
        if signup:
            self.confirm_label.pack(anchor="w", before=self.button)
            self.confirm.pack(fill="x", ipady=6, pady=(2, 10), before=self.button)
        else:
            self.confirm_label.pack_forget()
            self.confirm.pack_forget()
        self.message.config(text="")

    def submit(self) -> None:
        if self.store.seconds_locked(self.user.get()):
            self._countdown()
            return
        user, password = self.user.get(), self.password.get()
        try:
            if self.mode == "signup":
                self.store.create(user, password, self.confirm.get())
            name = self.store.login(user, password)
        except AuthError as exc:
            self.message.config(text=str(exc), fg=C["error"])
            self._countdown()
            return
        self.message.config(text="")
        if self.mode == "signup" or not self.store.demo_accounts():
            self.clear_fields()  # a real password never stays in the form
        self.on_success(name)

    def _countdown(self) -> None:
        if self._tick:
            self.after_cancel(self._tick)
            self._tick = None
        left = self.store.seconds_locked(self.user.get())
        if left:
            self.button.config(state="disabled")
            self.message.config(text=f"Too many attempts. Try again in {left} s", fg=C["error"])
            self._tick = self.after(500, self._countdown)
        else:
            if str(self.button["state"]) == "disabled":
                self.message.config(text="")
            self.button.config(state="normal")

    def focus_first(self) -> None:
        (self.password if self.user.get() else self.user).focus_set()


class CalcFrame(tk.Frame):
    """Keypad and typed input, live result preview, and a clickable history list."""

    def __init__(self, master: tk.Misc, on_logout: Callable[[], None]):
        super().__init__(master, bg=C["bg"], padx=16, pady=12)
        self.expressions: list[str] = []
        self._carry: tuple[str, Decimal] | None = None  # (last result as shown, its full-precision value)
        self._previewed = ""

        header = tk.Frame(self, bg=C["bg"])
        header.pack(fill="x", pady=(0, 10))
        self.who = tk.Label(header, text="", font=(FONT, 11), bg=C["bg"], fg=C["dim"])
        self.who.pack(side="left")
        _button(header, "Log out", on_logout, bg=C["func"], font=(FONT, 10)).pack(side="right", ipadx=10, ipady=2)

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True)

        display = tk.Frame(left, bg=C["panel"], padx=12, pady=10)
        display.pack(fill="x")
        self.result = tk.Label(display, text=" ", anchor="e", font=(MONO, 13), bg=C["panel"], fg=C["dim"])
        self.result.pack(fill="x")
        self.entry = _entry(display, font=(MONO, 26), justify="right")
        self.entry.configure(bg=C["panel"], highlightthickness=0)
        self.entry.pack(fill="x", ipady=4)
        self.entry.bind("<Return>", lambda _e: self.equals())
        self.entry.bind("<KP_Enter>", lambda _e: self.equals())
        self.entry.bind("<Escape>", lambda _e: self.clear())
        self.entry.bind("<KeyRelease>", lambda _e: self.preview())

        pad = tk.Frame(left, bg=C["bg"], pady=10)
        pad.pack(fill="both", expand=True)
        self.buttons: dict[str, tk.Button] = {}
        for r, row in enumerate(KEYS):
            pad.rowconfigure(r, weight=1)
            for c, key in enumerate(row):
                pad.columnconfigure(c, weight=1, uniform="keys")
                bg = C["equals"] if key == "=" else C["accent"] if key in OPERATORS else \
                    C["func"] if key in ("C", "⌫", "(", ")", "±") else C["key"]
                fg = "#15161c" if key in OPERATORS or key == "=" else C["text"]
                button = _button(pad, key, lambda k=key: self.press(k), bg=bg, fg=fg, font=(FONT, 17, "bold"))
                button.grid(row=r, column=c, columnspan=2 if key == "=" else 1, sticky="nsew", padx=3, pady=3)
                self.buttons[key] = button

        side = tk.Frame(body, bg=C["panel"], padx=10, pady=10, width=230)
        side.pack(side="right", fill="y", padx=(12, 0))
        side.pack_propagate(False)
        tk.Label(side, text="History", font=(FONT, 12, "bold"), bg=C["panel"], fg=C["text"]).pack(anchor="w")
        tk.Label(side, text="Click an entry to reuse it", font=(FONT, 9), bg=C["panel"], fg=C["dim"]).pack(anchor="w")
        self.history_list = tk.Listbox(side, bg=C["field"], fg=C["text"], font=(MONO, 11), relief="flat",
                                       highlightthickness=0, selectbackground=C["accent"],
                                       selectforeground="#15161c", activestyle="none")
        self.history_list.pack(fill="both", expand=True, pady=8)
        self.history_list.bind("<<ListboxSelect>>", lambda _e: self.reuse())
        _button(side, "Clear history", self.clear_history, bg=C["func"], font=(FONT, 10)).pack(fill="x", ipady=2)

    # -- actions -----------------------------------------------------------------------------------
    def set_user(self, name: str) -> None:
        self.who.config(text=f"Signed in as {name}")
        self.clear()

    def press(self, key: str) -> None:
        if key == "C":
            self.clear()
        elif key == "⌫":
            self.backspace()
        elif key == "=":
            self.equals()
        elif key == "±":
            self.toggle_sign()
        else:
            self.insert(key)
        self.entry.focus_set()

    def insert(self, text: str) -> None:
        if self.entry.selection_present():
            self.entry.delete("sel.first", "sel.last")
        self.entry.insert("insert", text)
        self.preview()

    def backspace(self) -> None:
        if self.entry.selection_present():
            self.entry.delete("sel.first", "sel.last")
        else:
            position = self.entry.index("insert")
            if position:
                self.entry.delete(position - 1)
        self.preview()

    def clear(self) -> None:
        self.entry.delete(0, "end")
        self.result.config(text=" ", fg=C["dim"])
        self._carry = None
        self._previewed = ""

    def toggle_sign(self) -> None:
        expr = self.entry.get().strip()
        if not expr:
            return
        self._sync_carry(expr)
        if self._carry and expr == self._carry[0]:  # a result on screen: negate its exact value
            value = -self._carry[1]
            self._carry = (format_number(value), value)
            self._set(self._carry[0])
        elif expr.startswith("-(") and _matching_bracket(expr, 1) == len(expr) - 1:
            self._set(expr[2:-1])  # undo an earlier ±, but not in "-(5)+(2)"
        else:
            if self._carry:  # continuing from a result: wrap its full-precision form so nothing changes meaning
                try:
                    expr = self._expand(expr)[0]
                except CalcError:
                    pass
                self._carry = None
            self._set(f"-({expr})")
        self.preview()

    def _sync_carry(self, expr: str) -> None:
        """The last result is carried forward only while it sits untouched at the start of the entry and is
        followed by an operator (or nothing); any edit into it drops the carry for good."""
        if self._carry:
            shown = self._carry[0]
            rest = expr[len(shown):]
            if not expr.startswith(shown) or (rest and rest[0] in "0123456789.eE"):
                self._carry = None

    def _expand(self, expr: str) -> tuple[str, str]:
        """(text to calculate, text to show in history). Continuing from a result uses its full precision
        ('0.333333333333333×3' is worked out as '(0.3333…3333)×3' = 1) and keeps a negative result's sign
        under ^ ('-3' then ^2 is (-3)^2 = 9); history shows the bracketed form so it reads the same way."""
        self._sync_carry(expr)
        if not self._carry:
            return expr, expr
        shown, value = self._carry
        rest = expr[len(shown):]
        full = f"({value}){rest}"
        if len(full) > MAX_LENGTH:
            raise CalcError(f"Expression is too long (max {MAX_LENGTH} characters)")
        return full, f"({shown}){rest}"

    def preview(self) -> None:
        expr = self.entry.get().strip()
        self._sync_carry(expr)  # e.g. the entry was emptied: the old result must not come back
        if expr == self._previewed:
            return  # unchanged (e.g. the key-release of Enter): keep the result or error that is showing
        self._previewed = expr
        try:
            text = f"= {format_number(evaluate(self._expand(expr)[0]))}" if expr else " "
        except CalcError:
            text = " "  # half-typed expressions are normal; errors are shown on "="
        self.result.config(text=text, fg=C["dim"])

    def equals(self) -> None:
        expr = self.entry.get().strip()
        if not expr:
            return
        try:
            full, readable = self._expand(expr)
            value = evaluate(full)
            shown = format_number(value)
        except CalcError as exc:
            self.result.config(text=str(exc), fg=C["error"])
            self._previewed = expr
            return
        expr = readable
        self.expressions.append(full)  # reusing a history entry repeats exactly this calculation
        self.history_list.insert("end", f"{expr} = {shown}")
        if len(self.expressions) > MAX_HISTORY:
            self.expressions.pop(0)
            self.history_list.delete(0)
        self.history_list.see("end")
        self.result.config(text=f"{expr} =", fg=C["dim"])
        self._carry = (shown, value)
        self._set(shown)
        self._previewed = shown

    def reuse(self) -> None:
        selection = self.history_list.curselection()
        if selection:
            self._carry = None
            self._set(self.expressions[selection[0]])
            self.preview()
            self.entry.focus_set()

    def clear_history(self) -> None:
        self.expressions.clear()
        self.history_list.delete(0, "end")

    def _set(self, text: str) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self.entry.icursor("end")

    def focus_first(self) -> None:
        self.entry.focus_set()


class CalculatorApp(tk.Tk):
    def __init__(self, store: AccountStore):
        super().__init__()
        self.title("SAM Calculator")
        self.configure(bg=C["bg"])
        self.geometry("780x580")
        self.minsize(640, 500)
        self.login_frame = LoginFrame(self, store, on_success=self._signed_in)
        self.calc_frame = CalcFrame(self, on_logout=self._logout)
        self.current: tk.Frame | None = None
        self._show(self.login_frame)

    def _show(self, frame: tk.Frame) -> None:
        for other in (self.login_frame, self.calc_frame):
            other.pack_forget()
        frame.pack(fill="both", expand=True)
        self.current = frame
        frame.focus_first()

    def _signed_in(self, name: str) -> None:
        self.calc_frame.set_user(name)
        self._show(self.calc_frame)

    def _logout(self) -> None:
        self.calc_frame.clear()
        self.calc_frame.clear_history()  # the next person must not see this user's calculations
        self.login_frame.reset()
        self._show(self.login_frame)
