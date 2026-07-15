"""Configuration loading for the Semantic Knowledge Compiler."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dynaconf import Dynaconf
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "default.yaml"


class ConnectorConfig(BaseModel):
    """Configuration for metadata connectors."""

    type: str = "postgres"
    connection_string: str = ""
    ddl_path: str = ""


class PipelineConfig(BaseModel):
    """Configuration for the compilation pipeline."""

    output_dir: Path = Path("./output")
    fail_fast: bool = True
    checkpoint_enabled: bool = True
    resume_from: Path | None = None
    stages: dict[str, dict[str, Any]] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    """Configuration for language-model calls."""

    enabled: bool = False
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = 0.1
    max_tokens: int = 4096
    rate_limit_rpm: int = 60
    cache_responses: bool = True
    max_retries: int = 3


class Neo4jConfig(BaseModel):
    """Configuration for the Neo4j graph store."""

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = ""
    database: str = "skc"
    dry_run: bool = True
    batch_size: int = 1000
    incremental: bool = False


class ConfidenceConfig(BaseModel):
    """Configuration for confidence scoring."""

    auto_approve_threshold: float = 0.85
    mandatory_review_threshold: float = 0.60
    signal_weights: dict[str, float] = Field(default_factory=dict)


class ReviewConfig(BaseModel):
    """Configuration for human-in-the-loop review."""

    auto_approve_high: bool = True
    mode: str = "batch"
    api_port: int = 8000
    store_path: Path | None = None


class PluginConfig(BaseModel):
    """Configuration for plugins and extensions."""

    search_paths: list[Path] = Field(default_factory=lambda: [Path("./plugins")])
    enabled: list[str] = Field(default_factory=list)


class SKCConfig(BaseModel):
    """Top-level SKC configuration."""

    connector: ConnectorConfig = Field(default_factory=ConnectorConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    plugins: PluginConfig = Field(default_factory=PluginConfig)


def _settings_files(config_path: str | Path | None) -> list[str]:
    files = [str(DEFAULT_CONFIG_PATH)]
    if config_path is not None:
        files.append(str(Path(config_path).expanduser()))
    local_settings = PROJECT_ROOT / "configs" / "settings.yaml"
    if local_settings.exists():
        files.append(str(local_settings))
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        files.append(str(env_file))
    return files


def load_config(config_path: str | Path | None = None) -> SKCConfig:
    """Load and validate SKC configuration.

    Configuration is layered in this order:
    ``configs/default.yaml`` -> optional caller-supplied file ->
    ``configs/settings.yaml`` if present -> environment variables prefixed
    with ``SKC_``.
    """

    settings = Dynaconf(
        envvar_prefix="SKC",
        settings_files=_settings_files(config_path),
        environments=False,
        load_dotenv=True,
    )

    return SKCConfig(
        connector=settings.get("connector", {}),
        pipeline=settings.get("pipeline", {}),
        llm=settings.get("llm", {}),
        neo4j=settings.get("neo4j", {}),
        confidence=settings.get("confidence", {}),
        review=settings.get("review", {}),
        plugins=settings.get("plugins", {}),
    )
