"""hello_agents — Gemini-powered agent with multi-tier memory & RAG."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hello-agents")
except PackageNotFoundError:
    __version__ = "0.1.0-dev"

__all__ = ["__version__"]
