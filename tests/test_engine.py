import unittest
from decimal import Decimal

from sam_calculator.engine import CalcError, calculate, evaluate, format_number


class ArithmeticTests(unittest.TestCase):
    def check(self, expr, expected):
        self.assertEqual(calculate(expr), expected, expr)

    def test_original_app_behaviour_still_works(self):
        self.check("12+30", "42")          # the 2023 app only added two numbers
        self.check("2.5+-1", "1.5")

    def test_four_operations_and_precedence(self):
        self.check("7-10", "-3")
        self.check("6*7", "42")
        self.check("1/4", "0.25")
        self.check("2+3*4", "14")
        self.check("(2+3)*4", "20")
        self.check("10-4-3", "3")          # left-associative
        self.check("100/10/5", "2")

    def test_display_symbols(self):
        self.check("8×3−4÷2", "22")
        self.check("√16", "4")
        self.check("sqrt(2)*sqrt(2)", "2")

    def test_rounding_leftovers_cancel_to_zero(self):
        self.check("1/3*3-1", "0")
        self.check("(1/3*3)-1+5", "5")
        self.check("1.0000000001-1", "0.0000000001")   # a real small difference is kept
        self.check("1e-20-0", "1e-20")

    def test_decimals_are_exact(self):
        self.check("0.1+0.2", "0.3")
        self.check("1/3", "0.333333333333333")
        self.check("2/3", "0.666666666666667")

    def test_power_and_unary_minus(self):
        self.check("2^10", "1024")
        self.check("2**3", "8")
        self.check("2^3^2", "512")         # right-associative
        self.check("-2^2", "-4")           # power before unary minus
        self.check("(-2)^2", "4")
        self.check("2^-1", "0.5")
        self.check("9^0.5", "3")
        self.check("--5", "5")

    def test_percent_and_implicit_multiplication(self):
        self.check("50%", "0.5")
        self.check("200*10%", "20")
        self.check("2(3+4)", "14")
        self.check("(1+2)(3+4)", "21")
        self.check("2√9", "6")

    def test_formatting(self):
        self.assertEqual(format_number(Decimal("-0")), "0")
        self.assertEqual(format_number(Decimal("100")), "100")
        self.assertEqual(format_number(Decimal("1E20")), "1e20")
        self.assertEqual(format_number(Decimal("1.5E-12")), "1.5e-12")
        self.assertEqual(calculate("10^14"), "100000000000000")
        self.assertEqual(calculate("10^15"), "1e15")


class ErrorTests(unittest.TestCase):
    def fails(self, expr, fragment):
        with self.assertRaises(CalcError) as ctx:
            evaluate(expr)
        self.assertIn(fragment, str(ctx.exception), expr)

    def test_user_mistakes(self):
        self.fails("", "Enter a calculation")
        self.fails("1/0", "divide by zero")
        self.fails("5/(2-2)", "divide by zero")
        self.fails("0^-1", "divide by zero")
        self.fails("1.2.3", "not a valid number")
        self.fails("(1+2", "Missing ')'")
        self.fails("1+2)", "Unexpected ')'")
        self.fails("3+", "incomplete")
        self.fails("2 3", "Unexpected '3'")
        self.fails("sqrt(-4)", "negative")
        self.fails("(-8)^0.5", "not a real number")
        self.fails("√", "needs a number")

    def test_huge_numbers_are_refused_quickly(self):
        self.fails("9^9^9", "too large")
        self.fails("10^1000000", "too large")
        self.assertEqual(calculate("10^1000"), "1e1000")
        self.assertTrue(calculate("2^100000").startswith("9.99002093014"))  # big but within range

    def test_long_powers_that_are_normal_calculations(self):
        self.assertEqual(calculate("(1+0.05/365)^(365*10)"), "1.64866481376547")  # daily compound interest
        self.assertEqual(calculate("1.0001^5000"), "1.64868005593118")  # checked with 50-digit Decimal
        self.assertEqual(calculate("0.1^1001"), "1e-1001")
        self.assertEqual(calculate("0^0"), "1")
        self.assertEqual(calculate("(2-2)^0"), "1")

    def test_scientific_notation_round_trips(self):
        self.assertEqual(calculate("1e15*2"), "2e15")
        self.assertEqual(calculate("1.5e-12*2"), "3e-12")
        self.assertEqual(calculate("2E3"), "2000")
        self.assertEqual(calculate(calculate("10^20") + "/10"), "1e19")  # a displayed result can be typed back
        self.fails("1e", "Unexpected character 'e'")
        self.fails("e5", "Unexpected character 'e'")

    def test_extreme_results_format_without_crashing(self):
        self.assertEqual(calculate("9.9999999999999999*(10^1000)^999*10^999"), "1e1000000")
        self.assertEqual(calculate("(0.1^1000)^1000*0.1^20"), "1e-1000020")
        self.assertEqual(calculate("-(0.1^1000)^1000*0.1^20"), "-1e-1000020")

    def test_out_of_range_literals_are_errors_not_crashes(self):
        for expr in ("1e1000000000000000000", "9e-99999999999999999999", "1e" + "9" * 190,
                     "9.99999999999999999e999999999999999999", "1e999999999999999999"):
            with self.assertRaises(CalcError, msg=expr) as ctx:
                calculate(expr)
            self.assertIn("too large", str(ctx.exception).lower())

    def test_deep_nesting_is_an_error_not_a_crash(self):
        self.fails("(" * 165 + "1", "nested")
        self.fails("-" * 150 + "1", "nested")
        self.fails("√" * 120 + "4", "nested")
        self.assertEqual(calculate("(" * 40 + "1" + ")" * 40), "1")

    def test_no_code_execution(self):
        for expr in ("__import__('os').system('echo hi')", "open('x')", "a+1", "1;2", "lambda: 1", "1e5e5"):
            with self.assertRaises(CalcError, msg=expr):
                evaluate(expr)

    def test_non_ascii_digits_are_a_friendly_error(self):
        for expr in ("2²", "٣+1", "１+1"):  # superscript two, Arabic-Indic three, full-width one
            with self.assertRaises(CalcError, msg=expr):
                evaluate(expr)

    def test_length_limit(self):
        self.fails("1+" * 150 + "1", "too long")


if __name__ == "__main__":
    unittest.main()
