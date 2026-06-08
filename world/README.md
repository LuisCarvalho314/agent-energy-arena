# World Module

`world/` owns the authoritative simulation state and mechanics behind the
browser UI and agent HTTP API. The main external references are:

- [`../API.md`](../API.md) for endpoint shapes and agent-facing payloads.
- [`../RULES.md`](../RULES.md) for formulas and gameplay rules.
- [`catalog.py`](catalog.py) for buildable tile specs exposed by `GET /catalog`.
- [`sim.py`](sim.py) for `World.build`, `World.drill`, `World.step`, and reset setup.
- [`grid.py`](grid.py) for road, transmission, and power-connectivity rules.

## Buildable Grid Infrastructure

Power-grid components are ordinary buildable tiles:

- `transmission_line`: place with `POST /build {"tile_type": "transmission_line", "x": X, "y": Y}`.
- `substation`: place with `POST /build {"tile_type": "substation", "x": X, "y": Y}`.

Both appear in `GET /catalog.tiles`, successful `/build.result`, and
`GET /state.tiles`.

## Connectivity Fields

Grid-relevant tile views expose `connected_to_power` in `/state.tiles` and
successful `/build.result`.

Current semantics:

- Transmission lines are powered by generator adjacency in the surrounding 8
  cells, then propagate power through orthogonal line-to-line chains.
- Substations connect from a powered line or generator in the surrounding 8
  cells, then serve a 7x7 area.
- Town hall is a starter service node: when powered by a line in the
  surrounding 8 cells, it serves a 7x7 area.
- Houses and commercial tiles need 7x7 service from a generator, connected
  substation, or connected town hall.
- Industrial uses the same 7x7 service rule and can also connect by adjacency
  to a powered transmission line.
- Batteries need generator adjacency in the surrounding 8 cells or 7x7 service
  from a connected substation/town hall.
- Generators produce only when they can reach at least one consumer.

Connectivity is not a build-validity rule. Unconnected tiles can exist, but
the relevant behavior is gated: generators produce 0 kW, batteries do not
charge/discharge, and unpowered civic/consumer tiles produce no demand or
economic/civic output.

## Starter Grid

Production/manual sessions can opt into `seed_starter_grid=True`. Reset then
places a free starter coal plant, road bridge, and transmission bridge so the
starter coal plant can power the town hall under the connectivity rules. These
starter tiles use `capex_paid = 0.0`.

## Agent Integration Notes

Agents do not need new API methods for this feature:

- Read `GET /catalog` to discover tile costs and descriptions.
- Build grid infrastructure through the existing `/build` endpoint.
- Inspect `connected_to_power` after build or in each `/state` snapshot.
- Prefer planning expansions around connected generators/substations instead
  of assuming a globally connected bus.
