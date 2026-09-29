from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from carfinder.config import Settings
from carfinder.api.routes import create_router
from carfinder.db.engine import create_database_engine
from carfinder.db.migrations import migration_status


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.load()
    app = FastAPI(title="CarFinder", version="0.1.0")
    app.include_router(create_router(app_settings))

    @app.get("/api/health")
    def health() -> dict[str, object]:
        engine = create_database_engine(app_settings.database_path)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            current, head = migration_status(app_settings.database_path)
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail=f"Database unavailable: {error}") from error
        finally:
            engine.dispose()

        if current != head or head is None:
            raise HTTPException(status_code=503, detail={"database": "ok", "migration": {"current": current, "head": head}})
        return {"status": "ok", "database": "ok", "migration": {"current": current, "head": head}}

    frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def frontend_not_built() -> str:
            return "<main><h1>CarFinder</h1><p>Build the UI with <code>cd frontend && npm run build</code>.</p></main>"

    return app


app = create_app()
