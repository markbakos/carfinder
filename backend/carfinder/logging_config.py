from __future__ import annotations

import logging

from carfinder.paths import AppPaths


def configure_logging() -> None:
    paths = AppPaths.from_environment()
    paths.ensure()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(paths.log_dir / "carfinder.log", encoding="utf-8")],
    )
