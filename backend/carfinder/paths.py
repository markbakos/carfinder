from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    state_dir: Path

    @classmethod
    def from_environment(cls) -> AppPaths:
        override = os.environ.get("CARFINDER_HOME")
        if override:
            root = Path(override).expanduser().resolve()
            return cls(root / "config", root / "data", root / "state")

        home = Path.home()
        return cls(
            Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")).expanduser() / "carfinder",
            Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")).expanduser() / "carfinder",
            Path(os.environ.get("XDG_STATE_HOME", home / ".local/state")).expanduser() / "carfinder",
        )

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "carfinder.sqlite3"

    @property
    def browser_dir(self) -> Path:
        return self.data_dir / "browser"

    @property
    def image_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def lock_file(self) -> Path:
        if os.environ.get("CARFINDER_HOME"):
            return self.state_dir / "run.lock"
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir:
            return Path(runtime_dir) / "carfinder-run.lock"
        return self.state_dir / "run.lock"

    def ensure(self) -> None:
        for directory in (self.config_dir, self.data_dir, self.state_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)
