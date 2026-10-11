"""Model-Router package: intelligence-aware inference routing on LiteLLM."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("model-router")
except PackageNotFoundError:  # source tree before installation
    __version__ = "0.2.1"
