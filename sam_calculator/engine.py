"""Calculator engine: parses and evaluates arithmetic safely, without eval().

Supports + - * / ^ (power), % (percent: 50% = 0.5, 200*10% = 20), sqrt / √, parentheses, unary minus,
implicit multiplication like 2(3+4), scientific notation like 1.5e-3, and the display symbols × ÷ −.
Uses Decimal, so 0.1+0.2 is exactly 0.3. Results too big for Decimal's range are reported, never computed forever.
"""
from __future__ import annotations

from decimal import MAX_EMAX, MIN_EMIN, Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext

MAX_LENGTH = 200       # characters in one expression
MAX_DEPTH = 60         # nested brackets / signs / roots, well inside Python's recursion limit
PRECISION = 34         # significant digits used while calculating
DISPLAY_DIGITS = 15    # significant digits shown to the user

_ALIASES = (("**", "^"), ("×", "*"), ("÷", "/"), ("−", "-"), ("–", "-"), ("√", "sqrt"))
_NUMBER_CHARS = frozenset("0123456789.")


class CalcError(ValueError):
    """A problem with the expression; the message is written to be shown to the user."""


def tokenize(text: str) -> list[tuple[str, object]]:
    if len(text) > MAX_LENGTH:
        raise CalcError(f"Expression is too long (max {MAX_LENGTH} characters)")
    for old, new in _ALIASES:
        text = text.replace(old, new)
    tokens: list[tuple[str, object]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in _NUMBER_CHARS:  # ASCII only: str.isdigit() also accepts '²' or '٣', which Decimal rejects
            j = i
            while j < len(text) and text[j] in _NUMBER_CHARS:
                j += 1
            number = text[i:j]
            if number.count(".") > 1 or number == ".":
                raise CalcError(f"'{number}' is not a valid number")
            # scientific notation, e.g. 1e15 or 1.5e-12 (the form results are displayed in)
            k = j + 1 if j < len(text) and text[j] in "eE" else j
            if k > j and k < len(text) and text[k] in "+-":
                k += 1
            if k > j and k < len(text) and text[k].isascii() and text[k].isdigit():
                while k < len(text) and text[k].isascii() and text[k].isdigit():
                    k += 1
                number = text[i:k]
                j = k
            try:
                tokens.append(("num", Decimal(number)))
            except (InvalidOperation, ValueError):  # an exponent beyond what Decimal can even represent
                raise CalcError("Number too large") from None
            i = j
        elif text.startswith("sqrt", i):
            tokens.append(("fn", "sqrt"))
            i += 4
        elif ch in "+-*/^%()":
            tokens.append(("op", ch))
            i += 1
        else:
            raise CalcError(f"Unexpected character '{ch}'")
    return tokens


class _Parser:
    """Recursive descent over the grammar (lowest to highest precedence):

        expr    := term (('+' | '-') term)*
        term    := unary (('*' | '/') unary | <implicit *> unary)*
        unary   := ('+' | '-') unary | power
        power   := postfix ('^' unary)?          right-associative; -2^2 = -4, 2^-1 = 0.5
        postfix := primary '%'*
        primary := number | '(' expr ')' | 'sqrt' postfix
    """

    def __init__(self, tokens: list[tuple[str, object]]):
        self.tokens = tokens
        self.i = 0
        self.depth = 0

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CalcError("Too many nested brackets or signs")

    def peek(self) -> tuple[str | None, object]:
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def take(self) -> tuple[str | None, object]:
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self) -> Decimal:
        if not self.tokens:
            raise CalcError("Enter a calculation")
        value = self.expr()
        if self.i < len(self.tokens):
            raise CalcError(f"Unexpected '{self.peek()[1]}'")
        return value

    def expr(self) -> Decimal:
        value = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            rhs = self.term()
            value = _snap(value + rhs if op == "+" else value - rhs, value, rhs)
        return value

    def term(self) -> Decimal:
        value = self.unary()
        while True:
            kind, tok = self.peek()
            if (kind, tok) in (("op", "*"), ("op", "/")):
                self.take()
                rhs = self.unary()
                if tok == "*":
                    value = value * rhs
                elif rhs == 0:
                    raise CalcError("Cannot divide by zero")
                else:
                    value = value / rhs
            elif kind == "fn" or (kind, tok) == ("op", "("):
                value = value * self.unary()  # 2(3+4), 2√9, (1+2)(3+4); "2 3" stays an error
            else:
                return value

    def unary(self) -> Decimal:
        if self.peek() in (("op", "-"), ("op", "+")):
            sign = self.take()[1]
            self._enter()
            value = self.unary()
            self.depth -= 1
            return -value if sign == "-" else value
        return self.power()

    def power(self) -> Decimal:
        base = self.postfix()
        if self.peek() == ("op", "^"):
            self.take()
            return _power(base, self.unary())
        return base

    def postfix(self) -> Decimal:
        value = self.primary()
        while self.peek() == ("op", "%"):
            self.take()
            value = value / 100
        return value

    def primary(self) -> Decimal:
        kind, tok = self.take()
        if kind == "num":
            return +tok  # type: ignore[operator]  # through the trapped context: out-of-range literals -> Overflow
        if (kind, tok) == ("op", "("):
            self._enter()
            value = self.expr()
            if self.take() != ("op", ")"):
                raise CalcError("Missing ')'")
            self.depth -= 1
            return value
        if (kind, tok) == ("fn", "sqrt"):
            if self.peek()[0] is None:
                raise CalcError("√ needs a number")
            self._enter()
            arg = self.postfix()
            self.depth -= 1
            if arg < 0:
                raise CalcError("Cannot take the square root of a negative number")
            return arg.sqrt()
        if kind is None:
            raise CalcError("The calculation is incomplete")
        raise CalcError(f"Unexpected '{tok}'")


def _snap(result: Decimal, lhs: Decimal, rhs: Decimal) -> Decimal:
    """Treat a sum or difference as 0 when it is only the rounding left over at 34 digits, e.g.
    0.9999…9 (1/3*3) - 1 = 1e-34 -> 0; real small differences such as 1.0000000001-1 are kept."""
    if result and abs(result) < max(abs(lhs), abs(rhs)).scaleb(-(PRECISION - 2)):
        return Decimal(0)
    return result


def _power(base: Decimal, exponent: Decimal) -> Decimal:
    # Decimal's ** is fast even for huge exponents; results beyond its range raise Overflow -> "Number too large".
    if exponent == 0:
        return Decimal(1)  # including 0^0, as on most calculators
    if base == 0 and exponent < 0:
        raise CalcError("Cannot divide by zero")
    if base < 0 and exponent != exponent.to_integral_value():
        raise CalcError("The result is not a real number")
    return base ** exponent


def evaluate(text: str) -> Decimal:
    """Evaluate an expression; raises CalcError with a user-friendly message on any problem."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        for trap in (DivisionByZero, Overflow, InvalidOperation):
            ctx.traps[trap] = True
        try:
            return _Parser(tokenize(text)).parse()
        except DivisionByZero:
            raise CalcError("Cannot divide by zero") from None
        except Overflow:
            raise CalcError("Number too large") from None
        except InvalidOperation:
            raise CalcError("Invalid calculation") from None
        except RecursionError:  # backstop; MAX_DEPTH normally stops this first
            raise CalcError("Too many nested brackets or signs") from None


def format_number(value: Decimal) -> str:
    """Up to 15 significant digits, no trailing zeros; scientific notation (which the engine also reads back)
    only for very big or very small numbers."""
    with localcontext() as ctx:
        # the widest exponent range and no traps: rounding 9.99...e999999 to 15 digits must not overflow
        ctx.prec, ctx.Emax, ctx.Emin = DISPLAY_DIGITS, MAX_EMAX, MIN_EMIN
        for trap in ctx.traps:
            ctx.traps[trap] = False
        rounded = (+value).normalize()
        if not rounded.is_finite():
            raise CalcError("Number too large")
        if rounded.is_zero():
            return "0"
        exponent = rounded.adjusted()
        if -10 <= exponent < DISPLAY_DIGITS:
            text = format(rounded, "f")
            return text.rstrip("0").rstrip(".") if "." in text else text
        mantissa, _, power = f"{rounded:E}".partition("E")
    if "." in mantissa:
        mantissa = mantissa.rstrip("0").rstrip(".")
    return f"{mantissa}e{int(power)}"


def calculate(text: str) -> str:
    """Evaluate and format in one step, e.g. calculate('12+30') == '42'."""
    return format_number(evaluate(text))
