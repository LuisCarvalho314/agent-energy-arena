"""FastAPI surface for the simulation skeleton.

Only the endpoints required by issue 01 are wired:
  /state, /step, /reset, /seed, /catalog, /forecast.
All mutating calls (success or failure) are appended to
runs/{run_id}/actions.jsonl.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from world.action_log import ActionLog
from world.catalog import build_catalog
from world.sim import World


class ResetBody(BaseModel):
    seed: int | None = None


class StepBody(BaseModel):
    days: int = Field(default=7, ge=1, le=7)


def create_app(world: World | None = None, action_log: ActionLog | None = None) -> FastAPI:
    app = FastAPI(title="Energy-AI Nexus", version="0.1.0")

    app.state.world = world or World()
    app.state.action_log = action_log or ActionLog()

    @app.get("/seed")
    def get_seed() -> dict[str, int]:
        return {"seed": app.state.world.state.seed}

    @app.get("/catalog")
    def get_catalog() -> dict[str, Any]:
        return build_catalog()

    @app.get("/state")
    def get_state() -> dict[str, Any]:
        return app.state.world.state_dict()

    @app.get("/forecast")
    def get_forecast(hours: int = 24) -> dict[str, Any]:
        if hours < 1 or hours > 168:
            raise HTTPException(status_code=400, detail="hours must be in [1, 168]")
        return app.state.world.forecast(hours=hours)

    @app.post("/reset")
    def post_reset(body: ResetBody) -> dict[str, Any]:
        params = body.model_dump()
        try:
            app.state.world.reset(seed=body.seed)
            result = {
                "ok": True,
                "treasury_after": app.state.world.state.treasury,
                "result": {"seed": app.state.world.state.seed, "day": 0},
            }
            app.state.action_log.append("/reset", params, ok=True, result=result["result"])
            return result
        except Exception as exc:  # pragma: no cover - defensive
            app.state.action_log.append("/reset", params, ok=False, error=str(exc))
            raise

    @app.post("/step")
    def post_step(body: StepBody) -> dict[str, Any]:
        params = body.model_dump()
        try:
            summary = app.state.world.step(days=body.days)
            result = {
                "ok": True,
                "day_completed": summary.day_completed,
                "summary": summary.summary,
                "treasury_after": summary.treasury_after,
            }
            app.state.action_log.append("/step", params, ok=True, result={
                "day_completed": summary.day_completed
            })
            return result
        except ValueError as exc:
            app.state.action_log.append("/step", params, ok=False, error=str(exc))
            raise HTTPException(status_code=400, detail=str(exc))

    # Static UI -----------------------------------------------------------
    ui_dir = Path(__file__).parent / "ui"
    if ui_dir.exists():
        app.mount("/ui", StaticFiles(directory=ui_dir), name="ui")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(ui_dir / "index.html")

    return app


app = create_app()
