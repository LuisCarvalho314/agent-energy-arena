# 09 — Pipelines: UI render + orphan badges

Status: needs-triage

## Parent

`.scratch/oilfield-v2/PRD.md`

## What to build

Render pipeline tiles distinctively on the map and surface orphan status visibly so a player can trace network connectivity and spot wasted infrastructure at a glance. No demolish gate — players can rearrange networks without ceremony.

## Acceptance criteria

- [ ] Pipeline tiles render in a distinct colour (e.g. pale blue) on the map canvas. No icon needed.
- [ ] Production wells appearing in `orphan_well_ids` get a yellow "selling raw" indicator (badge or border) on the map and in the wells table.
- [ ] Refineries appearing in `orphan_refinery_ids` get a red "no crude" indicator on the map and in the refineries table.
- [ ] Catalog `pipeline` description updated to call out that connectivity is now load-bearing.
- [ ] No demolish-stranding modal: right-clicking a pipeline tile demolishes immediately (existing behaviour preserved; do not add a `would_disconnect` gate).
- [ ] Manual verification: build one well + one refinery joined by a straight pipeline, observe routing; demolish the bridging tile, observe both go orange/yellow next day.
- [ ] `make check` passes.

## Blocked by

- `.scratch/oilfield-v2/issues/08-pipelines-sim-routing.md`
