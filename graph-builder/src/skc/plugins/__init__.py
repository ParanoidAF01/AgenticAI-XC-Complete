"""Plugin system — extensible domain knowledge providers."""
"""Plugin framework exports."""

from skc.plugins.base import SKCPlugin
from skc.plugins.loader import PluginLoader
from skc.plugins.registry import DEFAULT_REGISTRY, PluginRegistry

__all__ = ["DEFAULT_REGISTRY", "PluginLoader", "PluginRegistry", "SKCPlugin"]
