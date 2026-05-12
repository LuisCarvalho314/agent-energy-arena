---
Status: needs-triage
---

# Engaged-rollup UI + LLM state summary

## Parent

`.scratch/reservoir-scale-and-stacked-completions/PRD.md`

## What to build

Surface the engaged-rollup signal in the two places a player and the LLM agent read reservoir state.

**Wells-tab UI.** The reservoir group header gains an `engaged` term between `est` and `remaining`:

```
Reservoir R3 — est 320k bbl · engaged 85k · remaining 78k · 12 revealed vox · 1P + 1I
```

Number formatting goes through the existing `fmtBblCompact`. When `engaged_bbl == 0` (no wells in this reservoir), still render `engaged 0` — the explicit zero is the "drill here" affordance. No CSS changes beyond the existing `reservoir-group-header` class.

**LLM state summary.** `agents/state_summary.py` RESERVOIRS block gains `engaged=` and `engaged_remain=` terms per entry, slotted between `remaining=` and `revealed=`. Stays one line per reservoir, stays inside the existing 6,000-char ceiling tested by `test_summarize_state_token_budget`.

## Acceptance criteria

- [ ] Wells-tab header renders the new `engaged` term in the order `est · engaged · remaining · revealed · NP + NI`
- [ ] Header renders `engaged 0` (not hidden) when there are no wells in the reservoir
- [ ] `agents/state_summary.py` RESERVOIRS block contains `engaged=` and `engaged_remain=` terms in the documented position
- [ ] `test_summarize_state_token_budget` still passes (output stays under 6,000 chars)
- [ ] Zero-well reservoir surfaces in the RESERVOIRS block with the explicit zero values
- [ ] `make check` is green

## Blocked by

- `.scratch/reservoir-scale-and-stacked-completions/issues/05-engaged-rollup-backend.md` (needs the `/state` keys this slice renders)
