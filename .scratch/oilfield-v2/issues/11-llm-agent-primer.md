# 11 — LLM agent primer + state summary

Status: needs-triage

## Parent

`.scratch/oilfield-v2/PRD.md`

## What to build

Update the LLM agent's primer and compressed state so its policy is calibrated against the new oilfield rules. Scope is limited to prompt/state-summary changes — no logic rewrite of the agent itself (that's a separate concern).

## Acceptance criteria

- [ ] `agents/prompts.py` primer rewritten to cover: reservoir identity (`reservoir_id`), rate-based pressure (yesterday's rates, same-reservoir + Chebyshev > 1 gate, 0.5 cap), quadratic drill cost formula + `world_depth`, new survey pricing `(size/4)²` + default size 4, pipeline connectivity (orthogonal adjacency, per-network routing, orphan raw sale at $40/bbl).
- [ ] Primer no longer references the old cumulative-injection pressure or flat drill cost.
- [ ] `agents/state_summary.py` includes per-well `reservoir_id`, `yesterday_rate_bbl_day`, and (for producers) `yesterday_inj_rate_bbl_day` + `pressure_boost`.
- [ ] `agents/state_summary.py` includes a top-level `pipeline_networks` summary plus `orphan_well_ids` / `orphan_refinery_ids`.
- [ ] Manual sanity check: run the LLM agent for a few days against seed 42 and confirm it surveys at size 4, places injectors in the same reservoir at distance ≥ 2, and lays pipeline before refining. (Quality of strategy is out of scope; we only verify the primer is calibrated.)
- [ ] `make check` passes.

## Blocked by

- `.scratch/oilfield-v2/issues/02-ui-reservoir-coloring.md`
- `.scratch/oilfield-v2/issues/04-rate-pressure-observability.md`
- `.scratch/oilfield-v2/issues/05-quadratic-drill-cost.md`
- `.scratch/oilfield-v2/issues/06-survey-cost-rescale.md`
- `.scratch/oilfield-v2/issues/09-pipelines-ui.md`
