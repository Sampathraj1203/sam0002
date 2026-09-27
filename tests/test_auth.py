import json
import tempfile
import unittest
from pathlib import Path

from sam_calculator.auth import LOCK_SECONDS, MAX_ATTEMPTS, AccountStore, AuthError


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class AccountTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "accounts.json"
        self.clock = Clock()

    def tearDown(self):
        self._tmp.cleanup()

    def store(self, demo=True):
        return AccountStore(self.path, demo=demo, iterations=1000, clock=self.clock)

    def test_demo_accounts_only_in_demo_mode(self):
        self.assertEqual(self.store().login("admin", "password"), "admin")
        self.assertEqual(self.store().login("  DEMO ", "demo1234"), "demo")
        with self.assertRaises(AuthError):
            self.store(demo=False).login("admin", "password")
        self.assertEqual(self.store(demo=False).demo_accounts(), ())

    def test_created_account_is_hashed_not_plain_text(self):
        store = self.store(demo=False)
        self.assertFalse(store.has_accounts())
        self.assertEqual(store.create("Sampath", "s3cret-pass", "s3cret-pass"), "Sampath")
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("s3cret-pass", raw)
        record = json.loads(raw)["accounts"]["sampath"]
        self.assertEqual(len(bytes.fromhex(record["salt"])), 16)
        self.assertEqual(store.login("sampath", "s3cret-pass"), "Sampath")  # usernames are case-insensitive
        with self.assertRaises(AuthError):
            store.login("Sampath", "wrong-pass")

    def test_sign_up_rules(self):
        store = self.store()
        for args, fragment in ((("ab", "123456"), "3-32"), (("ok_name", "12345"), "at least 6"),
                               (("ok_name", "123456", "654321"), "do not match"), (("Admin", "123456"), "demo account"),
                               (("bad name", "123456"), "3-32")):
            with self.assertRaises(AuthError) as ctx:
                store.create(*args)
            self.assertIn(fragment, str(ctx.exception))
        store.create("ok_name", "123456")
        with self.assertRaises(AuthError) as ctx:
            store.create("OK_NAME", "abcdef")
        self.assertIn("already exists", str(ctx.exception))

    def test_lockout_after_repeated_failures(self):
        store = self.store()
        for _ in range(MAX_ATTEMPTS - 1):
            with self.assertRaisesRegex(AuthError, "Incorrect"):
                store.login("admin", "nope")
        with self.assertRaisesRegex(AuthError, "Too many attempts"):
            store.login("admin", "nope")
        with self.assertRaisesRegex(AuthError, "Too many attempts"):
            store.login("admin", "password")  # even the right password waits
        self.assertEqual(store.seconds_locked("admin"), LOCK_SECONDS)
        self.assertEqual(store.login("demo", "demo1234"), "demo")  # the lock is per account
        self.clock.now += LOCK_SECONDS
        self.assertEqual(store.login("admin", "password"), "admin")

    def test_lockout_survives_a_restart(self):
        for _ in range(MAX_ATTEMPTS):
            with self.assertRaises(AuthError):
                self.store().login("admin", "nope")  # a new store (= a new app run) every time
        with self.assertRaisesRegex(AuthError, "Too many attempts"):
            self.store().login("admin", "password")

    def test_corrupt_accounts_file_is_reported(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(AuthError, "Cannot read the accounts file"):
            self.store(demo=False).has_accounts()

    def test_wrong_shaped_or_damaged_files_are_auth_errors(self):
        for text in ("[]", "null", '"x"', '{"accounts": []}'):
            self.path.write_text(text, encoding="utf-8")
            with self.assertRaises(AuthError, msg=text):
                self.store(demo=False).has_accounts()
        self.path.write_text(json.dumps({"accounts": {"sam": {"name": "sam", "hash": "00"}}}), encoding="utf-8")
        with self.assertRaisesRegex(AuthError, "damaged"):
            self.store(demo=False).login("sam", "whatever")
        self.path.with_name("accounts.lockout.json").write_text("garbage", encoding="utf-8")
        self.assertEqual(self.store().login("admin", "password"), "admin")  # a bad lockout file is ignored

    def test_absurd_numbers_in_the_files_do_not_crash(self):
        state = self.path.with_name("accounts.lockout.json")
        for value in ("1e999", "-1e999", "NaN", "Infinity", "99999999999999999999"):
            state.write_text('{"lockout": {"admin": {"locked_until": %s, "failures": 1}}}' % value, encoding="utf-8")
            self.assertEqual(self.store().login("admin", "password"), "admin", value)
        for iterations in ("1e30", "99999999999999999999", "0", "true"):
            self.path.write_text('{"accounts": {"sam": {"name": "sam", "salt": "00", "hash": "00", "iterations": %s}}}'
                                 % iterations, encoding="utf-8")
            with self.assertRaisesRegex(AuthError, "damaged", msg=iterations):
                self.store(demo=False).login("sam", "whatever")

    def test_giant_integers_and_out_of_range_floats_are_handled(self):
        state = self.path.with_name("accounts.lockout.json")
        state.write_text('{"lockout": {"admin": {"locked_until": %s}}}' % ("1" + "0" * 400), encoding="utf-8")
        self.assertEqual(self.store().login("admin", "password"), "admin")  # no OverflowError
        self.path.write_text('{"accounts": {"old": {"name": "old", "salt": "00", "iterations": 1000, "hash": "00",'
                             ' "created": 1e999}}}', encoding="utf-8")
        with self.assertRaisesRegex(AuthError, "Cannot read the accounts file"):
            self.store(demo=False).has_accounts()                    # reported as damage, never saved back
        self.assertNotIn("Infinity", self.path.read_text(encoding="utf-8"))

    def test_unwritable_folder_fails_fast_instead_of_waiting(self):
        from unittest import mock
        real_open = __import__("os").open

        def deny_lock(path, *args, **kwargs):
            if str(path).endswith(".lock"):
                raise PermissionError(13, "Access is denied", str(path))
            return real_open(path, *args, **kwargs)

        import time
        with mock.patch("sam_calculator.auth.os.open", side_effect=deny_lock):
            start = time.monotonic()
            with self.assertRaisesRegex(AuthError, "Cannot use the data folder"):
                self.store(demo=False).create("sampath", "abc123")
            self.assertLess(time.monotonic() - start, 1.0)

    def test_failed_save_leaves_no_copy_of_the_hashes(self):
        from unittest import mock
        with mock.patch("sam_calculator.auth._retry", side_effect=lambda action, seconds=2.0: action()), \
                mock.patch("sam_calculator.auth.os.replace", side_effect=PermissionError("in use")):
            with self.assertRaisesRegex(AuthError, "Cannot save"):
                self.store(demo=False).create("sampath", "abc123")
        self.assertEqual([p.name for p in Path(self._tmp.name).iterdir() if p.suffix == ".tmp"], [])

    def test_save_waits_while_another_program_briefly_holds_the_file(self):
        import threading
        store = self.store(demo=False)
        store.create("alice", "abc123")
        handle = open(self.path, encoding="utf-8")  # on Windows this blocks os.replace until closed
        threading.Timer(0.3, handle.close).start()
        store.create("bobby", "abc123")
        self.assertEqual(sorted(json.loads(self.path.read_text(encoding="utf-8"))["accounts"]), ["alice", "bobby"])

    def test_unwritable_data_folder_is_an_auth_error(self):
        blocker = Path(self._tmp.name) / "not-a-folder"
        blocker.write_text("x", encoding="utf-8")
        store = AccountStore(blocker / "accounts.json", demo=False, iterations=1000)
        with self.assertRaisesRegex(AuthError, "Cannot"):
            store.create("sampath", "abc123")

    def test_simultaneous_sign_ups_keep_both_accounts(self):
        import threading
        errors = []

        def sign_up(name):
            try:
                AccountStore(self.path, demo=False, iterations=20000).create(name, "abc123")
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=sign_up, args=(n,)) for n in ("alice", "bobby", "carol")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(json.loads(self.path.read_text(encoding="utf-8"))["accounts"]), ["alice", "bobby", "carol"])


if __name__ == "__main__":
    unittest.main()
