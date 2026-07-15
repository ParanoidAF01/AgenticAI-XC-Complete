"""Plugin registry for SKC."""

from __future__ import annotations

from typing import Any

from skc.ir.kir import BusinessRule, Metric
from skc.plugins.base import SKCPlugin


class PluginRegistry:
    """Registry for managing SKC plugins."""

    def __init__(self) -> None:
        """Initialize the plugin registry."""
        self._plugins: dict[str, SKCPlugin] = {}

    def register(self, plugin: SKCPlugin) -> None:
        """Register a new plugin.

        Args:
            plugin: The plugin instance to register.
        """
        self._plugins[plugin.name] = plugin

    def clear(self) -> None:
        """Remove all registered plugins."""
        self._plugins.clear()

    def get_all(self) -> list[SKCPlugin]:
        """Get all registered plugins.

        Returns:
            A list of all registered plugin instances.
        """
        return list(self._plugins.values())

    def get_by_industry(self, industry: str) -> list[SKCPlugin]:
        """Get plugins that support a specific industry.

        Args:
            industry: The industry to filter by.

        Returns:
            A list of plugins supporting the industry.
        """
        return [p for p in self._plugins.values() if industry in p.industries]

    def get_ontology_seeds(self) -> list[Any]:
        """Get all ontology seeds from all registered plugins.

        Returns:
            A list of BusinessEntity objects representing the ontology seeds.
        """
        seeds = []
        for plugin in self._plugins.values():
            seeds.extend(plugin.get_ontology())
        return seeds

    def get_metrics(self) -> list[Metric]:
        """Get all metric definitions from registered plugins."""
        metrics: list[Metric] = []
        for plugin in self._plugins.values():
            metrics.extend(plugin.get_metrics())
        return metrics

    def get_rules(self) -> list[BusinessRule]:
        """Get all business rules from registered plugins."""
        rules: list[BusinessRule] = []
        for plugin in self._plugins.values():
            rules.extend(plugin.get_rules())
        return rules

    def get_all_synonyms(self) -> dict[str, list[str]]:
        """Get all synonyms from all registered plugins.

        Returns:
            A dictionary mapping terms to their synonyms.
        """
        all_synonyms: dict[str, list[str]] = {}
        for plugin in self._plugins.values():
            synonyms = plugin.get_synonyms()
            for term, syns in synonyms.items():
                if term not in all_synonyms:
                    all_synonyms[term] = []
                all_synonyms[term].extend(syns)
        return all_synonyms


DEFAULT_REGISTRY = PluginRegistry()
