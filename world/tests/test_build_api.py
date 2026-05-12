"""HTTP-level coverage of /build, /demolish, /catalog, /state.tiles."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from world.action_log import ActionLog
from world.api import create_app
from world.sim import World


def _client(tmp_path: Path) -> tuple[TestClient, ActionLog]:
    log = ActionLog(root=tmp_path / "runs")
    app = create_app(world=World(), action_log=log)
    return TestClient(app), log


def test_catalog_lists_civilian_tiles(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    catalog = client.get("/catalog").json()
    types = {entry["tile_type"] for entry in catalog["tiles"]}
    # Civilian tiles required by issue 02.
    for required in ("road", "house", "commercial", "industrial", "park", "pipeline"):
        assert required in types, types
    by_type = {entry["tile_type"]: entry for entry in catalog["tiles"]}
    assert by_type["road"]["capex"] == 500
    assert by_type["house"]["capex"] == 3000
    assert by_type["house"]["requires_road"] is True
    assert by_type["park"]["requires_road"] is False
    assert "description" in by_type["road"]


def test_state_tiles_lists_town_hall_after_reset(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    s = client.get("/state").json()
    halls = [t for t in s["tiles"] if t["type"] == "town_hall"]
    assert len(halls) == 1
    th = halls[0]
    assert th["x"] == s["config"]["world_w"] // 2
    assert th["y"] == s["config"]["world_h"] // 2
    assert "id" in th
    assert "built_day" in th
    assert th["operational"] is True


def test_build_road_and_demolish_round_trip(tmp_path: Path) -> None:
    client, log = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    cx = 16
    cy = 16
    treasury0 = client.get("/state").json()["treasury"]

    r = client.post("/build", json={"tile_type": "road", "x": cx + 1, "y": cy})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["treasury_after"] == treasury0 - 500

    # Demolish.
    r = client.post("/demolish", json={"x": cx + 1, "y": cy})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # 25% refund of 500 = 125.
    assert body["treasury_after"] == treasury0 - 500 + 125

    # Action log captured both calls.
    entries = [json.loads(line) for line in log.path.read_text().splitlines()]
    endpoints = [e["endpoint"] for e in entries]
    assert "/build" in endpoints
    assert "/demolish" in endpoints


def test_build_rejection_returns_200_with_error_and_logs(tmp_path: Path) -> None:
    client, log = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    # House without road adjacency.
    r = client.post("/build", json={"tile_type": "house", "x": 0, "y": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "no_road_adjacency"

    entries = [json.loads(line) for line in log.path.read_text().splitlines()]
    build_failures = [e for e in entries if e["endpoint"] == "/build" and e["ok"] is False]
    assert len(build_failures) == 1
    assert build_failures[0]["error"] == "no_road_adjacency"


def test_build_townhall_via_endpoint_rejected(tmp_path: Path) -> None:
    """`town_hall` is auto-placed; not buildable via /build."""
    client, _ = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    r = client.post("/build", json={"tile_type": "town_hall", "x": 0, "y": 0})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["error"] == "unknown_tile_type"


# -- Battery (issue 01) ----------------------------------------------------


def test_catalog_lists_battery_with_storage_and_efficiency(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    catalog = client.get("/catalog").json()
    by_type = {entry["tile_type"]: entry for entry in catalog["tiles"]}
    assert "battery" in by_type
    bat = by_type["battery"]
    assert bat["capex"] == 60_000
    assert bat["opex_per_day"] == 40
    assert bat["capacity_kw"] == 200
    assert bat["storage_kwh"] == 800
    assert bat["round_trip_efficiency"] == 0.85
    assert bat["requires_road"] is False
    assert bat["jobs"] == 0


def test_build_battery_appears_in_state_with_soc_and_setpoint(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    treasury0 = client.get("/state").json()["treasury"]
    r = client.post("/build", json={"tile_type": "battery", "x": 0, "y": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["treasury_after"] == treasury0 - 60_000
    s = client.get("/state").json()
    batteries = [t for t in s["tiles"] if t["type"] == "battery"]
    assert len(batteries) == 1
    bat = batteries[0]
    assert bat["soc_kwh"] == 0.0
    assert bat["charge_setpoint_kw"] == 0.0


def test_state_response_includes_soc_kwh_per_battery(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    client.post("/build", json={"tile_type": "battery", "x": 0, "y": 0})
    client.post("/build", json={"tile_type": "battery", "x": 0, "y": 1})
    s = client.get("/state").json()
    batteries = [t for t in s["tiles"] if t["type"] == "battery"]
    assert len(batteries) == 2
    for bat in batteries:
        assert "soc_kwh" in bat
        assert "charge_setpoint_kw" in bat
        assert bat["soc_kwh"] == 0.0
        assert bat["charge_setpoint_kw"] == 0.0


def test_control_battery_endpoint_sets_setpoint(tmp_path: Path) -> None:
    client, log = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    client.post("/build", json={"tile_type": "battery", "x": 0, "y": 0})
    bat_id = next(t["id"] for t in client.get("/state").json()["tiles"] if t["type"] == "battery")

    r = client.post("/control/battery", json={"tile_id": bat_id, "charge_kw": 50.0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["tile_id"] == bat_id
    assert body["result"]["charge_setpoint_kw"] == 50.0

    s = client.get("/state").json()
    bat = next(t for t in s["tiles"] if t["id"] == bat_id)
    assert bat["charge_setpoint_kw"] == 50.0

    entries = [json.loads(line) for line in log.path.read_text().splitlines()]
    control_calls = [e for e in entries if e["endpoint"] == "/control/battery"]
    assert len(control_calls) == 1
    assert control_calls[0]["ok"] is True


def test_control_battery_accepts_negative_setpoint(tmp_path: Path) -> None:
    """Negative charge_kw = discharge command; no clamp at this layer."""
    client, _ = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    client.post("/build", json={"tile_type": "battery", "x": 0, "y": 0})
    bat_id = next(t["id"] for t in client.get("/state").json()["tiles"] if t["type"] == "battery")
    r = client.post("/control/battery", json={"tile_id": bat_id, "charge_kw": -75.0})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["result"]["charge_setpoint_kw"] == -75.0


def test_control_battery_unknown_id(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    r = client.post("/control/battery", json={"tile_id": "battery-99", "charge_kw": 10.0})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "unknown_battery"


def test_control_battery_rejects_non_battery_tile(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.post("/reset", json={"seed": 42})
    th_id = next(t["id"] for t in client.get("/state").json()["tiles"] if t["type"] == "town_hall")
    r = client.post("/control/battery", json={"tile_id": th_id, "charge_kw": 10.0})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "unknown_battery"


def test_reset_clears_battery_soc_and_setpoint() -> None:
    """Slice 01 has no dispatch participation yet, so we poke the dataclass
    directly to seed non-zero state, then assert /reset truly clears it."""
    from world.sim import World

    w = World()
    w.reset(seed=42)
    w.build("battery", 0, 0)
    bat = next(t for t in w.state.tiles if t.type == "battery")
    bat.soc_kwh = 333.0
    bat.charge_setpoint_kw = 50.0

    w.reset(seed=42)
    assert [t for t in w.state.tiles if t.type == "battery"] == []
    # And a fresh build comes up zeroed.
    w.build("battery", 0, 0)
    bat = next(t for t in w.state.tiles if t.type == "battery")
    assert bat.soc_kwh == 0.0
    assert bat.charge_setpoint_kw == 0.0


def test_battery_workforce_efficiency_is_one() -> None:
    """Passive tile branch: jobs=0 → efficiency 1.0."""
    from world import workforce
    from world.sim import World

    w = World()
    w.reset(seed=42)
    w.build("battery", 0, 0)
    bat = next(t for t in w.state.tiles if t.type == "battery")
    assert workforce.efficiency(bat) == 1.0
