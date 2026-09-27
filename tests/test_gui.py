import tempfile
import unittest
from pathlib import Path

try:
    import tkinter as tk
except ImportError:  # Python built without Tk (e.g. slim Linux images): nothing to test here
    raise unittest.SkipTest("tkinter is not available")

from sam_calculator.auth import MAX_ATTEMPTS, AccountStore


def make_app(demo=True):
    from sam_calculator.gui import CalculatorApp

    tmp = tempfile.TemporaryDirectory()
    app = CalculatorApp(AccountStore(Path(tmp.name) / "accounts.json", demo=demo, iterations=1000))
    app.withdraw()
    app.update()
    return app, tmp


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            tk.Tk().destroy()
        except tk.TclError as exc:  # no display (CI / Colab)
            raise unittest.SkipTest(f"no display: {exc}")

    def setUp(self):
        self.app, self._tmp = make_app()

    def tearDown(self):
        self.app.destroy()
        self._tmp.cleanup()

    def test_demo_account_is_prefilled_and_stays_after_logout(self):
        login = self.app.login_frame
        self.assertEqual((login.user.get(), login.password.get()), ("admin", "password"))
        login.submit()
        self.assertIs(self.app.current, self.app.calc_frame)
        self.app._logout()
        self.assertIs(self.app.current, login)
        self.assertEqual((login.user.get(), login.password.get()), ("admin", "password"))

    def test_keypad_calculates_and_records_history(self):
        self.app.login_frame.submit()
        calc = self.app.calc_frame
        for key in ("1", "2", "+", "3", "0"):
            calc.press(key)
        self.assertEqual(calc.result.cget("text"), "= 42")  # live preview
        calc.press("=")
        self.assertEqual(calc.entry.get(), "42")
        self.assertEqual(calc.history_list.get(0), "12+30 = 42")
        for key in ("×", "2", "="):
            calc.press(key)
        self.assertEqual(calc.entry.get(), "84")
        calc.press("±")
        self.assertEqual(calc.entry.get(), "-84")  # ± on a result negates the result itself
        calc.press("⌫")
        calc.press("⌫")
        calc.press("C")
        self.assertEqual(calc.entry.get(), "")
        for key in ("1", "÷", "0", "="):
            calc.press(key)
        self.assertEqual(calc.result.cget("text"), "Cannot divide by zero")
        calc.history_list.selection_set(0)
        calc.reuse()
        self.assertEqual(calc.entry.get(), "12+30")

    def test_wrong_password_and_lockout(self):
        login = self.app.login_frame
        login.fill("admin", "nope")
        for _ in range(MAX_ATTEMPTS):
            login.submit()
        self.assertIn("Too many attempts", login.message.cget("text"))
        self.assertEqual(str(login.button["state"]), "disabled")
        self.assertIs(self.app.current, login)

    def type(self, calc, keys):
        for key in keys:
            calc.press(key)

    def test_chaining_keeps_precision_and_sign(self):
        self.app.login_frame.submit()
        calc = self.app.calc_frame
        self.type(calc, "1÷3=")
        self.assertEqual(calc.entry.get(), "0.333333333333333")
        self.type(calc, "×3=")
        self.assertEqual(calc.entry.get(), "1")                 # not 0.999999999999999
        self.type(calc, "C7−10=^2=")
        self.assertEqual(calc.entry.get(), "9")                 # (-3)^2, not -(3^2)
        self.type(calc, "C10^15=×2=")
        self.assertEqual(calc.entry.get(), "2e15")              # e-notation results can be reused
        self.type(calc, "±")
        self.assertEqual(calc.entry.get(), "-2e15")
        self.type(calc, "C42=5")
        self.assertEqual(calc.entry.get(), "425")               # typing a digit extends the number
        self.type(calc, "=")
        self.assertEqual(calc.entry.get(), "425")

    def test_history_records_what_was_really_calculated(self):
        self.app.login_frame.submit()
        calc = self.app.calc_frame
        self.type(calc, "7−10=^2=")
        self.assertEqual(calc.history_list.get(1), "(-3)^2 = 9")
        self.type(calc, "C1÷3=×3=")
        self.assertEqual(calc.history_list.get(3), "(0.333333333333333)×3 = 1")
        for index, expected in ((1, "9"), (3, "1")):  # reusing an entry repeats exactly that calculation
            calc.press("C")
            calc.history_list.selection_clear(0, "end")
            calc.history_list.selection_set(index)
            calc.reuse()
            calc.press("=")
            self.assertEqual(calc.entry.get(), expected)

    def test_plus_minus_keeps_a_carried_result(self):
        self.app.login_frame.submit()
        calc = self.app.calc_frame
        self.type(calc, "7−10=^2±=")
        self.assertEqual(calc.entry.get(), "-9")                # -( (-3)^2 )
        self.type(calc, "C1÷3=×3±=")
        self.assertEqual(calc.entry.get(), "-1")                # not -0.999999999999999
        self.type(calc, "C1÷3=×3=−1=")
        self.assertEqual(calc.entry.get(), "0")                 # the visible 1 minus 1 is 0

    def test_editing_into_a_result_stops_carrying_it(self):
        self.app.login_frame.submit()
        calc = self.app.calc_frame
        self.type(calc, "7−10=⌫⌫")
        self.assertEqual(calc.entry.get(), "")
        self.type(calc, "-3^2=")
        self.assertEqual(calc.entry.get(), "-9")  # typed fresh: the engine's own rule, not the old result

    def test_plus_minus_only_unwraps_its_own_brackets(self):
        self.app.login_frame.submit()
        calc = self.app.calc_frame
        self.type(calc, "5±+(2)")
        self.assertEqual(calc.entry.get(), "-(5)+(2)")
        self.type(calc, "±")
        self.assertEqual(calc.entry.get(), "-(-(5)+(2))")
        self.type(calc, "=")
        self.assertEqual(calc.entry.get(), "3")

    def test_error_stays_visible_after_the_enter_key_is_released(self):
        self.app.login_frame.submit()
        calc = self.app.calc_frame
        calc.entry.insert(0, "1/0")
        calc.preview()
        calc.equals()
        calc.preview()  # what the <KeyRelease> of Enter triggers
        self.assertEqual(calc.result.cget("text"), "Cannot divide by zero")

    def test_logout_clears_history_and_switching_to_sign_up_clears_the_demo_password(self):
        login = self.app.login_frame
        login.submit()
        self.type(self.app.calc_frame, "6×7=")
        self.app._logout()
        self.assertEqual(self.app.calc_frame.history_list.size(), 0)
        login.set_mode("signup")
        self.assertEqual((login.user.get(), login.password.get(), login.confirm.get()), ("", "", ""))
        login.set_mode("signin")
        self.assertEqual((login.user.get(), login.password.get()), ("admin", "password"))

    def test_without_demo_logout_leaves_no_credentials(self):
        app, tmp = make_app(demo=False)
        try:
            login = app.login_frame
            login.fill("sampath", "abc123")
            login.confirm.insert(0, "abc123")
            login.submit()
            self.assertIs(app.current, app.calc_frame)
            app._logout()
            self.assertEqual((login.mode, login.user.get(), login.password.get()), ("signin", "", ""))
            login.submit()  # pressing Sign in on the empty form must not get back in
            self.assertIs(app.current, login)
        finally:
            app.destroy()
            tmp.cleanup()

    def test_without_demo_first_screen_is_sign_up(self):
        app, tmp = make_app(demo=False)
        try:
            login = app.login_frame
            self.assertEqual(login.mode, "signup")
            self.assertEqual(login.user.get(), "")
            login.fill("sampath", "abc123")
            login.confirm.insert(0, "abc123")
            login.submit()
            self.assertIs(app.current, app.calc_frame)
            self.assertIn("sampath", app.calc_frame.who.cget("text"))
        finally:
            app.destroy()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
