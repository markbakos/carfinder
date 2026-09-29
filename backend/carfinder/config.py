from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from carfinder.paths import AppPaths


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseConfig(_ConfigModel):
    path: Path | None = None


class ScrapingConfig(_ConfigModel):
    detail_recheck_hours: int = Field(default=24, ge=1)
    removed_after_missing_runs: int = Field(default=3, ge=1)
    request_delay_seconds: float = Field(default=2.5, ge=0)
    max_concurrent_detail_requests: int = Field(default=1, ge=1)


class PolovniConfig(_ConfigModel):
    enabled: bool = False
    headless: bool = True
    browser_profile: Path | None = None


class ProvidersConfig(_ConfigModel):
    polovniautomobili: PolovniConfig = Field(default_factory=PolovniConfig)


class LlmConfig(_ConfigModel):
    enabled: bool = False
    provider: Literal["codex_exec", "gemini_cli", "openai_compatible", "external", "none"] = "codex_exec"
    model: str = ""
    timeout_seconds: int = Field(default=180, ge=1)
    command: list[str] = Field(default_factory=lambda: ["codex"])


class ImageStorageConfig(_ConfigModel):
    mode: Literal["none", "thumbnail", "all"] = "none"


class StorageConfig(_ConfigModel):
    images: ImageStorageConfig = Field(default_factory=ImageStorageConfig)


class ServerConfig(_ConfigModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8420, ge=1, le=65535)


class Settings(_ConfigModel):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    scraping: ScrapingConfig = Field(default_factory=ScrapingConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    config_path: Path | None = Field(default=None, exclude=True)

    @classmethod
    def load(cls) -> Settings:
        paths = AppPaths.from_environment()
        config_path = paths.config_file
        values = tomllib.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}

        if database_path := os.environ.get("CARFINDER_DATABASE_PATH"):
            values.setdefault("database", {})["path"] = database_path
        if host := os.environ.get("CARFINDER_HOST"):
            values.setdefault("server", {})["host"] = host
        if port := os.environ.get("CARFINDER_PORT"):
            values.setdefault("server", {})["port"] = port

        settings = cls.model_validate(values)
        return settings.model_copy(update={"config_path": config_path})

    @property
    def database_path(self) -> Path:
        configured = self.database.path
        if configured is None:
            return AppPaths.from_environment().database_file
        path = configured.expanduser()
        if not path.is_absolute() and self.config_path:
            path = self.config_path.parent / path
        return path.resolve()

    @property
    def browser_profile(self) -> Path:
        configured = self.providers.polovniautomobili.browser_profile
        if configured is None:
            return AppPaths.from_environment().browser_dir / "polovni"
        return configured.expanduser().resolve()
