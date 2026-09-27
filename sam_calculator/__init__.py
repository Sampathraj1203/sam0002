"""SAM Calculator: a desktop calculator with sign-in, history and a safe expression engine."""
from .engine import CalcError, calculate, evaluate

__version__ = "2.0.0"
__all__ = ["CalcError", "calculate", "evaluate", "__version__"]
