"""open-primeagent - RLM runtime for the coding agent you already use."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: the installed distribution. A hand-written literal
    # here would drift from pyproject.toml the first time anyone forgot.
    __version__ = version("open-primeagent")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare tree
    __version__ = "0.0.0+unknown"
