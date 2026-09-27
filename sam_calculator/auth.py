"""Sign-in for the calculator.

Real accounts are stored as salted PBKDF2-SHA256 hashes in a local JSON file outside the repository, never as
plain text. Demo mode (on by default) also accepts the demo accounts below, which the login screen shows and
pre-fills so the app can be demonstrated without typing; start with --no-demo to hide and refuse them.
After 5 wrong passwords an account is locked for 30 seconds; the lock is saved, so restarting does not reset it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

# Shown on screen in demo mode only, so they are deliberately not secret. "admin/password" is the original app's login.
DEMO_ACCOUNTS: tuple[tuple[str, str], ...] = (("admin", "password"), ("demo", "demo1234"))
ITERATIONS = 200_000
MAX_ITERATIONS = 10_000_000   # a saved record asking for more is treated as damaged
MAX_ATTEMPTS = 5
LOCK_SECONDS = 30
STALE_LOCK_SECONDS = 30
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


class AuthError(ValueError):
    """Sign-in or sign-up problem; the message is written to be shown to the user."""


def default_data_dir() -> Path:
    """%APPDATA%\\sam0002 on Windows, ~/.config/sam0002 elsewhere; SAM0002_HOME overrides both."""
    if os.environ.get("SAM0002_HOME"):
        return Path(os.environ["SAM0002_HOME"])
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "sam0002"


def _hash(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not allowed in the accounts files")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):  # 1e999 would otherwise become inf and be saved back as Infinity
        raise ValueError(f"{text} is out of range in the accounts files")
    return value


def _retry(action: Callable[[], object], seconds: float = 2.0) -> object:
    """Run a file operation, retrying briefly on the PermissionError Windows gives while another process has
    the file open or is replacing it."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            return action()
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)


class AccountStore:
    def __init__(self, path: Path | None = None, *, demo: bool = True, iterations: int = ITERATIONS,
                 clock: Callable[[], float] = time.time):
        self.path = Path(path) if path else default_data_dir() / "accounts.json"
        self.state_path = self.path.with_name(self.path.stem + ".lockout.json")
        self.demo = demo
        self.iterations = iterations
        self._clock = clock

    # -- files -------------------------------------------------------------------------------------
    # On Windows a file that another reader has open cannot be replaced (and is briefly unreadable while it is
    # being replaced), so reads, replaces and the lock file retry for a moment before giving up.
    def _read_json(self, path: Path, key: str, *, strict: bool) -> dict:
        try:
            doc = json.loads(_retry(lambda: path.read_text(encoding="utf-8")), parse_constant=_reject_constant,
                             parse_float=_finite_float)
            section = doc.get(key, {}) if isinstance(doc, dict) else None
            if not isinstance(section, dict):
                raise ValueError("unexpected layout")
            return section
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            if strict:
                raise AuthError(f"Cannot read the accounts file {path}: {exc}") from None
            return {}  # a damaged lockout file only loses lockout counters

    def _write_json(self, path: Path, key: str, data: dict) -> None:
        tmp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, key: data}, fh, indent=1, allow_nan=False)
            _retry(lambda: os.replace(tmp, path))
            tmp = None
        except (OSError, ValueError) as exc:  # ValueError: never write NaN/Infinity that the reader refuses
            raise AuthError(f"Cannot save {path}: {exc}") from None
        finally:
            if tmp is not None:  # never leave a copy of the password hashes lying around
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """One writer at a time across windows and processes, via an exclusive lock file."""
        lock = self.path.with_name(self.path.name + ".lock")
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AuthError(f"Cannot use the data folder {lock.parent}: {exc}") from None
        deadline = time.monotonic() + 5
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except (FileExistsError, PermissionError) as exc:
                try:
                    age = time.time() - lock.stat().st_mtime
                except FileNotFoundError:
                    if isinstance(exc, PermissionError):  # no lock file at all: the folder is not writable
                        raise AuthError(f"Cannot use the data folder {lock.parent}: {exc}") from None
                    continue  # the other writer just finished; try again at once
                except OSError:
                    age = 0.0  # Windows "delete pending": the other writer is finishing, so wait
                if age > STALE_LOCK_SECONDS:
                    try:
                        lock.unlink()  # left behind by a crash
                    except OSError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    raise AuthError("The accounts file is busy; please try again") from None
                time.sleep(0.05)
            except OSError as exc:
                raise AuthError(f"Cannot use the data folder {lock.parent}: {exc}") from None
        try:
            yield
        finally:
            os.close(fd)
            try:
                lock.unlink()
            except OSError:
                pass

    def _accounts(self) -> dict[str, dict]:
        return self._read_json(self.path, "accounts", strict=True)

    def has_accounts(self) -> bool:
        return bool(self._accounts())

    def demo_accounts(self) -> tuple[tuple[str, str], ...]:
        return DEMO_ACCOUNTS if self.demo else ()

    # -- sign up -----------------------------------------------------------------------------------
    def create(self, username: str, password: str, confirm: str | None = None) -> str:
        name = username.strip()
        if not _USERNAME.match(name):
            raise AuthError("Username must be 3-32 letters, digits, '.', '_' or '-'")
        if any(name.lower() == demo.lower() for demo, _ in DEMO_ACCOUNTS):
            raise AuthError(f"'{name}' is a demo account name; choose another")
        if len(password) < 6:
            raise AuthError("Password must be at least 6 characters")
        if len(password) > 128:
            raise AuthError("Password is too long")
        if confirm is not None and confirm != password:
            raise AuthError("The two passwords do not match")
        salt = secrets.token_bytes(16)
        record = {"name": name, "salt": salt.hex(), "iterations": self.iterations,
                  "hash": _hash(password, salt, self.iterations), "created": int(time.time())}
        with self._locked():  # hash first, then a short load-check-save under the lock
            accounts = self._accounts()
            if name.lower() in accounts:
                raise AuthError(f"The account '{name}' already exists")
            accounts[name.lower()] = record
            self._write_json(self.path, "accounts", accounts)
        return name

    # -- sign in and lockout -----------------------------------------------------------------------
    def seconds_locked(self, username: str) -> int:
        entry = self._read_json(self.state_path, "lockout", strict=False).get(username.strip().lower(), {})
        until = entry.get("locked_until", 0) if isinstance(entry, dict) else 0
        if not isinstance(until, (int, float)) or isinstance(until, bool):
            return 0
        try:
            until = float(until)  # a 400-digit integer from a damaged file raises OverflowError here
        except OverflowError:
            return 0
        if not math.isfinite(until):
            return 0  # damaged value: ignore it rather than lock forever or crash
        remaining = until - self._clock()
        if remaining > LOCK_SECONDS + 1:
            return 0  # further ahead than any real lock: damaged or tampered, so ignore it
        return max(0, int(remaining + 0.999))

    def _update_state(self, key: str, change: Callable[[dict], None]) -> None:
        with self._locked():
            state = self._read_json(self.state_path, "lockout", strict=False)
            entry = state.get(key)
            state[key] = entry if isinstance(entry, dict) else {}
            change(state[key])
            if not state[key]:
                del state[key]
            self._write_json(self.state_path, "lockout", state)

    def login(self, username: str, password: str) -> str:
        """Return the display name on success; raise AuthError otherwise (5 failures lock the name for 30 s)."""
        name = username.strip()
        key = name.lower()
        wait = self.seconds_locked(key)
        if wait:
            raise AuthError(f"Too many attempts. Try again in {wait} s")
        if self._check(name, password):
            if key in self._read_json(self.state_path, "lockout", strict=False):
                self._update_state(key, dict.clear)
            return self._display_name(name)

        outcome: dict[str, bool] = {}

        def fail(entry: dict) -> None:
            entry["failures"] = int(entry.get("failures", 0)) + 1 if isinstance(entry.get("failures"), int) else 1
            if entry["failures"] >= MAX_ATTEMPTS:
                entry.clear()
                entry["locked_until"] = self._clock() + LOCK_SECONDS
                outcome["locked"] = True

        self._update_state(key, fail)
        if outcome.get("locked"):
            raise AuthError(f"Too many attempts. Try again in {LOCK_SECONDS} s")
        raise AuthError("Incorrect username or password")

    def _check(self, name: str, password: str) -> bool:
        for demo_name, demo_password in self.demo_accounts():
            if name.lower() == demo_name and hmac.compare_digest(password.encode(), demo_password.encode()):
                return True
        record = self._accounts().get(name.lower())
        if record is None:
            _hash(password, b"timing-equaliser", self.iterations)  # same work whether or not the user exists
            return False
        try:
            iterations = record["iterations"]
            if not isinstance(iterations, int) or isinstance(iterations, bool) or not 1 <= iterations <= MAX_ITERATIONS:
                raise ValueError("bad iteration count")
            expected = _hash(password, bytes.fromhex(record["salt"]), iterations)
            return hmac.compare_digest(expected, str(record["hash"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise AuthError(f"The saved account '{name}' is damaged; create it again") from None

    def _display_name(self, name: str) -> str:
        record = self._accounts().get(name.lower())
        return record.get("name", name) if isinstance(record, dict) else name.lower()
