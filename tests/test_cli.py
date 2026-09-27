import tempfile
import unittest
from pathlib import Path

from sam_calculator import cli
from sam_calculator.auth import AccountStore


def run(lines, secrets, demo=True, path=None):
    lines, secrets, out = iter(lines), iter(secrets), []

    def ask(prompt):
        out.append(prompt)
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None  # what input() raises when the input ends

    def ask_secret(prompt):
        out.append(prompt)
        try:
            return next(secrets)
        except StopIteration:
            raise EOFError from None

    with tempfile.TemporaryDirectory() as tmp:
        store = AccountStore(path or Path(tmp) / "accounts.json", demo=demo, iterations=1000)
        code = cli.run(store, ask=ask, ask_secret=ask_secret, out=out.append)
    return code, "\n".join(out)


class CliTests(unittest.TestCase):
    def test_demo_login_with_enter_then_calculate(self):
        code, text = run(["", "12+30", "2^10", "1/0", "history", "quit"], [""])
        self.assertEqual(code, 0)
        self.assertIn("Signed in as admin", text)
        self.assertIn("= 42", text)
        self.assertIn("= 1024", text)
        self.assertIn("Error: Cannot divide by zero", text)
        self.assertIn("12+30 = 42\n2^10 = 1024", text)

    def test_wrong_password_then_right(self):
        code, text = run(["admin", "admin", "quit"], ["bad", "password"])
        self.assertIn("Incorrect username or password", text)
        self.assertIn("Signed in as admin", text)

    def test_first_run_without_demo_creates_an_account(self):
        code, text = run(["sampath", "sampath", "5*5", "quit"], ["abc123", "abc123", "abc123"], demo=False)
        self.assertIn("Account 'sampath' created.", text)
        self.assertIn("= 25", text)

    def test_lockout_ends_the_session(self):
        code, text = run(["x"] * 5, ["bad"] * 5)
        self.assertEqual(code, 1)
        self.assertIn("Too many attempts", text)

    def test_damaged_accounts_file_is_a_message_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "accounts.json"
            path.write_text("[]", encoding="utf-8")
            code, text = run([], [], demo=False, path=path)
        self.assertEqual(code, 1)
        self.assertIn("Cannot read the accounts file", text)

    def test_end_of_input_exits_cleanly(self):
        code, text = run([""], [""])  # input runs out after sign-in
        self.assertEqual(code, 0)
        self.assertIn("Goodbye!", text)


if __name__ == "__main__":
    unittest.main()
