"""Plugin loader for SKC."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid5, NAMESPACE_URL

import yaml

from skc.ir.kir import BusinessEntity, BusinessRule, Metric
from skc.plugins.base import SKCPlugin
from skc.plugins.registry import PluginRegistry


class PluginLoader:
    """Loader for SKC YAML-based plugins."""

    def __init__(self, registry: PluginRegistry) -> None:
        """Initialize the plugin loader.

        Args:
            registry: The plugin registry to register loaded plugins with.
        """
        self.registry = registry

    def load_from_directory(self, directory: Path) -> list[SKCPlugin]:
        """Load all YAML plugins from a directory.

        Iterates through subdirectories and loads plugins from `plugin.yaml` and
        associated files (`ontology.yaml`, `metrics.yaml`, `rules.yaml`, `synonyms.yaml`).

        Args:
            directory: The base directory containing plugin subdirectories.
        """
        loaded: list[SKCPlugin] = []
        if not directory.is_dir():
            return loaded

        for subdir in directory.iterdir():
            if not subdir.is_dir():
                continue

            plugin_yaml_path = subdir / "plugin.yaml"
            if not plugin_yaml_path.exists():
                continue

            with plugin_yaml_path.open("r", encoding="utf-8") as f:
                plugin_meta = yaml.safe_load(f) or {}

            meta_name = plugin_meta.get("name", subdir.name)
            meta_version = plugin_meta.get("version", "0.1.0")
            meta_description = plugin_meta.get("description", "")
            meta_industries = plugin_meta.get("industries", [])
            meta_trust_score = float(plugin_meta.get("trust_score", 0.75))

            class DynamicYAMLPlugin(SKCPlugin):
                @property
                def name(self) -> str:
                    return meta_name

                @property
                def version(self) -> str:
                    return meta_version

                @property
                def description(self) -> str:
                    return meta_description

                @property
                def industries(self) -> list[str]:
                    return meta_industries

                @property
                def trust_score(self) -> float:
                    return meta_trust_score

                def get_ontology(self) -> list[BusinessEntity]:
                    return getattr(self, "_ontology", [])

                def get_metrics(self) -> list[Metric]:
                    return getattr(self, "_metrics", [])

                def get_rules(self) -> list[BusinessRule]:
                    return getattr(self, "_rules", [])

                def get_synonyms(self) -> dict[str, list[str]]:
                    return getattr(self, "_synonyms", {})

                def get_validators(self) -> list[Any]:
                    return []

            plugin_instance = DynamicYAMLPlugin()

            plugin_instance._ontology = self._load_models(
                subdir / "ontology.yaml",
                BusinessEntity,
                plugin_instance,
                "entity",
            )
            plugin_instance._metrics = self._load_models(
                subdir / "metrics.yaml",
                Metric,
                plugin_instance,
                "metric",
            )
            plugin_instance._rules = self._load_models(
                subdir / "rules.yaml",
                BusinessRule,
                plugin_instance,
                "rule",
            )

            # Parse synonyms
            synonyms_path = subdir / "synonyms.yaml"
            synonyms_data: dict[str, list[str]] = {}
            if synonyms_path.exists():
                with synonyms_path.open("r", encoding="utf-8") as f:
                    synonyms_data = yaml.safe_load(f) or {}
            plugin_instance._synonyms = synonyms_data

            self.registry.register(plugin_instance)
            loaded.append(plugin_instance)

        return loaded

    def _load_models(
        self,
        path: Path,
        model_type: type[BusinessEntity] | type[Metric] | type[BusinessRule],
        plugin: SKCPlugin,
        id_prefix: str,
    ) -> list[Any]:
        if not path.exists():
            return []

        with path.open("r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or []

        if isinstance(raw_data, dict):
            for key in ("entities", "metrics", "rules", "items"):
                if key in raw_data:
                    raw_data = raw_data[key]
                    break

        models: list[Any] = []
        for raw_item in raw_data:
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            item.setdefault("id", self._stable_id(plugin.name, id_prefix, item.get("name", "")))
            item.setdefault("provenance", [plugin._make_provenance()])
            item.setdefault("confidence", plugin._make_confidence(self._plugin_trust_score(plugin)))

            provenance = item.get("provenance")
            if provenance is not None and not isinstance(provenance, list):
                item["provenance"] = [provenance]

            models.append(model_type(**item))

        return models

    @staticmethod
    def _stable_id(plugin_name: str, id_prefix: str, name: str) -> str:
        raw = f"skc:plugin:{plugin_name}:{id_prefix}:{name}"
        return f"{plugin_name}_{id_prefix}_{uuid5(NAMESPACE_URL, raw).hex[:12]}"

    @staticmethod
    def _plugin_trust_score(plugin: SKCPlugin) -> float:
        return float(getattr(plugin, "trust_score", 0.75))
