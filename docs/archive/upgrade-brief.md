# Energy–AI Nexus — Balance Upgrade Brief

**Status:** Proposal. Companion to `docs/hackathon-brief.md`. Where this brief
conflicts with the original, this brief wins; otherwise, the original brief
applies unchanged.

**Audience:** Implementer agents extending `world/` and the catalog. Every
formula here must appear as a named function or constant in code with the
same variable names, matching the convention of the original brief.

**Why this exists:** A code-grounded audit of the current implementation
(see §A "Findings") shows that ~40% of the catalog is either strictly
dominated, never-triggered, or decorative. The five named events all push
the player toward the same answer (build more gas). This brief specifies
the minimal set of changes that restore component diversity and force the
player to actually adapt to event mixes.

---

## 1. Goals

1. **Every catalog item has a regime where it is the right call.**
   No strict domination, no purely cosmetic tiles.
2. **Each event class has a distinct counter.** Heatwave ≠ demand surprise
   ≠ fuel shock ≠ plant failure ≠ regulatory tightening, in terms of which
   component prevents the score loss.
3. **Operations is a lever, not just construction.** Currently agents only
   *build*; dispatch is automatic, well rates are set-and-forget. Add at
   least one operational decision that meaningfully moves score.
4. **Maintain the ~2000-line readability budget.** Each change has a target
   line count; cumulative additions must stay under +600 lines of world
   code.

Non-goals (deliberately deferred to v3):
- Grid topology, transmission losses
- Reactive power, frequency stability
- Refined product slate (gasoline vs diesel vs petchem)
- Multi-player / scenario editor
- Authentication / persistence

---

## 2. Summary of changes

| # | Change | Files | LOC | Priority |
|---|---|---|---:|---|
| 1 | Coal viability rebalance | `power.py`, `catalog.py`, `events.py` | ~40 | P0 |
| 2 | **Batteries** (new tile + dispatch step) | `power.py`, `state.py`, `catalog.py`, `api.py` | ~180 | P0 |
| 3 | Happiness depth (smooth gate + park radius + noise) | `population.py` | ~60 | P0 |
| 4 | Pipeline transport cost & capacity | `pipelines.py`, `economy.py` | ~80 | P1 |
| 5 | Refinery tiers + crude import market | `economy.py`, `catalog.py` | ~90 | P1 |
| 6 | Reservoir decline + water cut | `subsurface.py`, `pricing.py` | ~70 | P1 |
| 7 | CCS-mode injection wells | `subsurface.py`, `economy.py`, `state.py` | ~80 | P2 |

P0 = required for "minimum viable balance pass." P1/P2 are scoped
extensions; can ship independently.

---

## 3. Per-change specs

### 3.1 Coal viability rebalance (P0)

**Problem.** At default carbon price $25/t:
- Coal margin: $80 − $20 fuel − $22.5 carbon = **$37.5/MWh**
- Gas margin:  $80 − $30 fuel − $10 carbon = **$40.0/MWh**

Coal also has 5× slower ramp (10%/h vs 50%/h), a 25% must-run minimum
(burns fuel & emits CO₂ even at low demand), $200k CAPEX vs $80k, and the
−0.05 happiness penalty for houses within chebyshev-3. There is no regime
in which coal is the right build.

**Solution.** Reposition coal as the "cheap baseload anchor for big
cities" it is in reality. Three coordinated changes:

```python
# world/catalog.py — coal_plant spec
capacity_kw = 1500          # was 800
fuel_cost_per_mwh = 12      # was 20

# world/events.py — fuel_price_shock per-fuel multipliers
GAS_FUEL_SHOCK_MULT  = 2.5  # gas is the volatile fuel in reality
COAL_FUEL_SHOCK_MULT = 1.3  # coal contracts are long-dated
# (replaces the current uniform ×2)

# world/events.py — plant_failure type weighting
PLANT_FAILURE_WEIGHTS = {"gas_peaker": 0.7, "coal_plant": 0.3}
# (replaces uniform sampling across all fossil plants)
```

**Realism.** Henry Hub gas spot has historically moved 3–10× over a
decade; thermal coal is contracted on annual cycles and rarely moves
more than 30%. Gas turbines have shorter MTBF than steam-cycle coal
(more thermal cycling, more high-speed rotating mass).

**Result after change.** Coal margin becomes $80 − $12 − $22.5 =
**$45.5/MWh**, beating gas on a per-MWh basis. Gas keeps the ramp
advantage and CAPEX advantage for cities under ~800 kW continuous load.
Asymmetric fuel shock means coal-heavy fleets survive gas-price spikes;
diversified fleets handle either shock cheaply.

**Tests.**
- `test_dispatch.py::test_coal_cheaper_per_mwh_than_gas_at_default_carbon`
- `test_events.py::test_fuel_shock_hits_gas_harder`
- `test_events.py::test_plant_failure_samples_gas_more_often_over_n_trials`

---

### 3.2 Batteries — the missing component (P0)

**Problem.** The original brief explicitly excludes batteries. As a
result:
- Renewable share is hard-capped by diurnal mismatch
- Curtailment exists only as a 50% haircut, never recoverable
- Brownout protection requires fossil over-build
- Agents have no operational decisions — only construction

The score's R-term (10% weight) is functionally uncontested because no
mechanism converts surplus midday solar into evening supply.

**Solution.** Add a `battery` tile and a dispatch step between
must-take renewables (step 1) and coal must-run (step 2).

```python
# world/catalog.py
battery = TileSpec(
    tile_type="battery",
    capex=60_000,
    opex_per_day=40,
    capacity_kw=200,           # charge/discharge power rating
    storage_kwh=800,            # energy capacity (4h at rated power)
    round_trip_efficiency=0.85,
    requires_road=False,
    description="200 kW / 800 kWh storage. Charges on surplus, "
                "discharges on shortage. 85% round-trip efficient.",
)

# world/state.py — Tile fields
soc_kwh: float = 0.0           # state of charge, [0, storage_kwh]
charge_setpoint_kw: float = 0  # agent override; -200..+200, default 0 = auto

# world/power.py — new dispatch step 1.5
def battery_dispatch(batteries, supply, demand, prev_R):
    """Auto-policy: charge on surplus (R>1.05), discharge on shortage
    (R<0.95). Agent overrides via charge_setpoint_kw clamp this."""
    net = 0.0
    for b in batteries:
        rated = TILE_CATALOG["battery"].capacity_kw * efficiency(b)
        store_cap = TILE_CATALOG["battery"].storage_kwh * efficiency(b)
        eta = TILE_CATALOG["battery"].round_trip_efficiency

        if b.charge_setpoint_kw != 0:
            # Manual override: clamp to rated power, soc bounds
            cmd = clip(b.charge_setpoint_kw, -rated, +rated)
        else:
            # Auto policy
            R = supply / max(demand, 1)
            if R > 1.05:
                cmd = +rated           # charge
            elif R < 0.95:
                cmd = -rated           # discharge
            else:
                cmd = 0

        if cmd > 0:                    # charging
            room = store_cap - b.soc_kwh
            cmd = min(cmd, room)
            b.soc_kwh += cmd * sqrt(eta)
            net -= cmd                 # drawn from supply
        elif cmd < 0:                  # discharging
            avail = b.soc_kwh
            cmd = max(cmd, -avail)
            b.soc_kwh += cmd / sqrt(eta)
            net -= cmd                 # added to supply
    return net  # net contribution (+ = added supply, − = drawn for charge)
```

**API.** New endpoint:

```
POST /control/battery   { "tile_id": str, "charge_kw": float }
  charge_kw: positive = charge, negative = discharge, 0 = auto
```

**Scoring impact.** Renewables term R can credibly exceed 60% with
4–6 batteries paired with adequate solar/wind. The 0.1 weight now
matters in practice.

**Realism.** 60k$ / 800 kWh = $75/kWh installed. Real-world utility
battery storage is $200–400/kWh today, trending toward $100/kWh by
2030; for hackathon purposes $75/kWh is "near-future."  Round-trip
85% matches lithium-ion typical (90% one-way × 95% inverter).

**Tests.**
- `test_dispatch.py::test_battery_charges_during_curtailment`
- `test_dispatch.py::test_battery_discharges_to_avoid_brownout`
- `test_dispatch.py::test_battery_round_trip_loses_15_percent`
- `test_api_smoke.py::test_control_battery_endpoint`

---

### 3.3 Happiness depth (P0)

**Problem.** With no coal and no outages, happiness pins at 1.0. The
park `max(0, park_count − 1)` formula silently nullifies park #1.
The 0.5 growth gate is a tripwire — 24h of brownout zeroes happiness
even after recovery.

**Solution.** Three coordinated changes in `world/population.py`:

```python
# 1. Fix off-by-one: every park contributes
happiness += 0.05 * park_count          # was 0.05 * max(0, park_count - 1)

# 2. Park radius-of-effect — replaces the flat +0.05*park_count term
def park_benefit(state):
    bonus = 0.0
    for h in houses:
        nearby_parks = sum(1 for p in parks
                          if chebyshev(h, p) <= 2)
        bonus += min(0.30, 0.10 * nearby_parks)
    return bonus / max(1, len(houses))   # average per-house bonus

# 3. Noise pollution from industrial / refinery
def noise_penalty(state):
    penalty = 0.0
    for h in houses:
        for src in industrial_tiles + refinery_tiles:
            if chebyshev(h, src) <= 2:
                # Park between halves the penalty
                has_park_between = any(
                    chebyshev(p, h) <= 2 and chebyshev(p, src) <= 2
                    for p in parks
                )
                penalty += 0.015 if has_park_between else 0.03
    return penalty / max(1, len(houses))

# 4. Smooth growth gate (replaces binary 0.5 cutoff)
growth_multiplier = max(0.0, (happiness - 0.3) / 1.2)
# happiness 0.3 → 0% growth; 0.5 → 17% growth; 1.0 → 58%; 1.5 → 100%
growth = config.base_growth_rate * pop * growth_multiplier
```

The decline branch (`happiness < 0.5 → pop *= 0.99`) becomes `happiness < 0.3`
to match the new gate.

**Result.**
- Park #1 actually does something
- Park placement matters spatially (radius-2 from houses)
- Industrial near houses creates a real zoning puzzle (offset with parks)
- One bad day no longer zeroes growth — recovery is gradual

**Realism.** Amenity proximity premium, NIMBY industrial siting, and
green-buffer mitigation are standard urban-economics levers. The smooth
gate matches real population dynamics (gradual response, not threshold
behavior).

**Tests.**
- `test_population.py::test_first_park_contributes`
- `test_population.py::test_park_within_2_boosts_adjacent_house_happiness`
- `test_population.py::test_industrial_adjacent_to_house_drops_happiness`
- `test_population.py::test_park_between_industrial_and_house_halves_penalty`
- `test_population.py::test_smooth_growth_at_happiness_0_6`

---

### 3.4 Pipeline transport cost & capacity (P1)

**Problem.** Pipelines exist (`world/pipelines.py`) but only as a binary
connectivity check. Building 10 pipelines costs the same in delivered
crude as building 1.

**Solution.** Per-tile flow capacity + per-tile transport fee:

```python
# world/pipelines.py
PIPELINE_CAPACITY_BBL_DAY = 200
PIPELINE_FEE_USD_PER_BBL = 0.20

def route_with_cost(producers, refineries, network):
    """BFS shortest path from each producer to nearest refinery on the
    same connected component. Returns dict[producer_id, dict] with:
      crude_to_refinery, refinery_id, hops, transport_cost_usd.

    Caps each pipeline tile's daily flow at PIPELINE_CAPACITY_BBL_DAY.
    Excess production at a node with no remaining downstream capacity
    sells at the orphan crude price (CRUDE_PRICE_USD_PER_BBL).
    """
```

Transport cost is deducted from oil revenue, surfaced in
`today_summary_so_far["transport_cost"]`.

**Result.** Co-located refinery (1 hop) costs $0.20/bbl × 500 = $100/day,
negligible. Distant field (10 hops) costs $2/bbl × 500 = $1000/day, and
needs 3 parallel pipelines if production > 200 bbl/day per route. Now
network topology and capacity planning matter.

**Realism.** Real midstream tariffs are quoted in cents/bbl/100mi with
capacity rights — this is the exact structure.

**Tests.**
- `test_pipelines.py::test_co_located_refinery_pays_one_hop_fee`
- `test_pipelines.py::test_pipeline_capacity_caps_throughput`
- `test_pipelines.py::test_excess_routes_to_second_refinery`

---

### 3.5 Refinery tiers + crude import market (P1)

**Problem.** Refinery is $150k all-or-nothing. Useless before wells,
suddenly transformative after. Mid-game refining is impossible.

**Solution.** Two changes.

**Mini refinery tier.**

```python
mini_refinery = TileSpec(
    tile_type="mini_refinery",
    capex=40_000,
    opex_per_day=100,
    max_throughput_bbl_day=100,
    yield_rate=0.80,           # slightly worse than full refinery's 0.85
    kwh_per_bbl=240,           # slightly less efficient
    co2_per_bbl=0.35,
    jobs=8,
    requires_road=True,
    description="100 bbl/day. Lower yield, higher specific energy.",
)
```

**Crude import market.** Any refinery can purchase crude when its setpoint
exceeds locally available production:

```python
CRUDE_IMPORT_PRICE_USD_PER_BBL = 55  # above well crude, below refined

def imported_crude(refinery, locally_routed):
    deficit = refinery.setpoint_rate_bbl_day - locally_routed
    if deficit <= 0:
        return 0.0
    return min(deficit, refinery.effective_max)  # subject to cap × efficiency
```

Cost is deducted from treasury at end of day, surfaced as
`today_summary_so_far["crude_import_cost"]`.

**Result.** Refining margin on imported crude:
$76.5 − $55 = **$21.5/bbl**, positive but worse than producing your own
($76.5 − ~$2 transport ≈ $74.5/bbl). Refinery becomes viable on day 60
even without surveys; exploration becomes a margin optimization, not an
unlock gate.

**Realism.** ~90% of global refining is merchant (buy crude, sell
products). Vertical integration is the exception.

**Tests.**
- `test_economy.py::test_mini_refinery_breaks_even_at_60_bbl_day`
- `test_economy.py::test_imported_crude_charges_55_usd_per_bbl`
- `test_economy.py::test_refinery_prefers_local_crude_over_imports`

---

### 3.6 Reservoir decline + water cut (P1)

**Problem.** `well_production = Q_MAX · k_eff · (V_remain / V_init)` is
linear in remaining oil. Real reservoirs produce on hyperbolic decline
with rising water cut — late-life wells produce less oil per barrel of
total fluid.

**Solution.** Two coordinated tweaks in `world/subsurface.py`:

```python
# Hyperbolic decline exponent
DECLINE_EXPONENT = 0.6

def well_production_bbl_day(w, world):
    pool = voxels_in_3x3x3(w.x, w.y, w.target_z)
    V_init   = sum(v.oil_in_place_bbl for v in pool)
    V_remain = sum(v.oil_remaining_bbl for v in pool)
    if V_init == 0:
        return 0, 0, 0

    fraction = V_remain / V_init
    # Hyperbolic (was linear) — front-loads production, steeper tail
    effective_fraction = fraction ** DECLINE_EXPONENT

    # Water cut rises as fraction falls, capped at 95%
    water_cut = clip(1.0 - fraction, 0.0, 0.95)

    # Injection cuts both supports rate AND reduces water
    inj = injection_support(pool)
    pressure_boost = min(0.5, inj / V_init)
    effective_fraction = min(1.0, effective_fraction + pressure_boost)
    water_cut = max(0.0, water_cut - 0.5 * pressure_boost)

    k_eff = mean_perm(pool) / 500.0
    q_oil = Q_MAX_WELL_BBL_DAY * k_eff * effective_fraction
    q_oil = min(w.setpoint_rate_bbl_day, q_oil)

    return q_oil, water_cut, V_remain
```

Selling price drops with water cut to model separation cost:

```python
# world/pricing.py
def well_realized_price(water_cut):
    return CRUDE_PRICE_USD_PER_BBL * (1.0 - 0.5 * water_cut)
# At wc=0: $40/bbl. At wc=0.5: $30/bbl. At wc=0.95: $21/bbl.
```

**Result.**
- Drilling earlier captures more value (front-loaded decline)
- Late-life wells produce at $21–30/bbl, not $40 — abandonment decisions exist
- Injection has *two* visible effects: rate boost AND water-cut reduction
- A field needs both producers and injectors to fully harvest

**Realism.** Hyperbolic Arps decline and water cut are how every
operator forecasts production. The exponent 0.6 is in the typical range
for sandstone reservoirs (0.4–0.8).

**Tests.**
- `test_subsurface.py::test_first_year_production_higher_under_hyperbolic`
- `test_subsurface.py::test_water_cut_rises_with_depletion`
- `test_subsurface.py::test_injection_reduces_water_cut`
- `test_subsurface.py::test_well_realized_price_drops_with_water_cut`

---

### 3.7 CCS-mode injection wells (P2)

**Problem.** Once a reservoir is depleted, every facility on top of it
is stranded asset. Injection wells in particular have no second use.
The regulatory_tightening event (permanent ×1.5 carbon) is pure punishment
— no component lets the player turn it into an opportunity.

**Solution.** Let injection wells run in `mode = "water" | "co2"`. CO₂
mode stores emissions from the city's coal/gas/refinery output up to
the well's daily rate, earning the carbon price back as a credit:

```python
# world/subsurface.py — Well model
mode: str = "water"   # "water" or "co2"

# world/economy.py — daily CCS step (runs before carbon billing)
def ccs_capture(world):
    co2_wells = [w for w in world.wells
                 if w.type == "injection" and w.mode == "co2"]
    if not co2_wells:
        return 0.0
    total_capacity_t = sum(w.setpoint_rate_bbl_day * CO2_T_PER_BBL_EQUIV
                           for w in co2_wells)
    captured_t = min(total_capacity_t, world.state.today_summary_so_far["co2_emitted_t"])
    credit = captured_t * world.state.carbon_price * CCS_CREDIT_FRACTION
    world.state.treasury += credit
    world.state.today_summary_so_far["ccs_credit"] = credit
    world.state.today_summary_so_far["co2_captured_t"] = captured_t
    return captured_t
```

Constants:
```
CO2_T_PER_BBL_EQUIV   = 0.4    # tons CO2 per bbl-equivalent volume
CCS_CREDIT_FRACTION   = 0.8    # 80% of the avoided carbon cost is credited
```

**API.** Extend `/control/well` to accept an optional `mode` field, or
add a sibling `/control/well/mode` endpoint.

**Result.** Regulatory tightening becomes a *signal to deploy CCS*, not
just a cost. Depleted fields become carbon-storage assets. Late-game
operators have a reason to keep injection capacity online after oil is
gone.

**Realism.** CCS is exactly this: depleted oil reservoirs are the
preferred storage formation. Carbon credits at 80% of avoided price
match how 45Q tax credits (US) and ETS allowances (EU) currently work
for early CCS projects.

**Tests.**
- `test_subsurface.py::test_co2_well_captures_emissions`
- `test_subsurface.py::test_co2_well_credits_carbon_price`
- `test_economy.py::test_ccs_more_valuable_after_regulatory_tightening`

---

## 4. Event-counter matrix after upgrade

| Event | Effect | Required counter | Components activated |
|---|---|---|---|
| Heatwave | residential ×1.40, **solar derate −20%** [new] | Store morning solar; wind unaffected | **Batteries**, wind |
| Plant failure | one plant zeroes; gas-weighted [new] | Fleet diversification | **Coal**, batteries |
| Fuel shock | gas ×2.5, coal ×1.3 [new] | Coal baseload + renewables | **Coal**, solar, wind |
| Demand surprise | commercial+industrial ×1.30 | Ramp headroom + discharge | **Batteries**, gas reserve |
| Reg. tightening | carbon ×1.5 permanent | Replace fossil + deploy CCS | **CCS injection wells**, renewables+batteries |

The "solar derate −20% on heatwave" is a free add-on (5 lines in
`weather.py`) that makes heatwaves bite even on sunny seeds: PV panel
efficiency drops about −0.4%/°C above 25°C, so a 40°C heatwave really
does cost ~6% output. Setting it to −20% exaggerates for hackathon
legibility.

---

## 5. Minimum viable pass

If only three changes ship, do these in order:

1. **§3.2 Batteries** — fixes the curtailment trap, gives operations a
   real knob, makes renewables score-relevant.
2. **§3.1 Coal rebalance** — revives coal, makes fleet diversity matter.
3. **§3.3 Happiness depth** — turns happiness from a tripwire into a
   continuous mechanic, makes parks and zoning real decisions.

After those three, every catalog item has a regime where it's correct,
and every event has at least one distinct counter beyond "build more gas."

§3.4–§3.7 are polish: they deepen specific subsystems (midstream,
refining, reservoir, CCS) and can ship independently in any order.

---

## 6. Scoring implications

No change to the score formula itself:

```
score = 0.5·min(P/P_ref, 3.0) + 0.4·0.5·(1+tanh(T/T_ref)) + 0.1·R
```

But the **achievable score distribution shifts**:

| Term | Current ceiling | After upgrade |
|---|---:|---:|
| P (population) | ~1.5 (rare; jobs+power gate) | ~1.5 (easier: batteries unblock evening peak) |
| T (treasury) | ~0.4 (saturates fast) | ~0.4 (unchanged) |
| R (renewable) | ~0.04 in practice | ~0.08 with batteries |

The R-term goes from "tie-breaker noise" to "real contested 5–10% of
score." Combined fleets (solar + wind + batteries + small coal
baseload) become competitive with pure-gas fleets, where today pure-gas
wins by ~15%.

The baselines in `baselines/seed_42.json` will need to be regenerated
after each P0 change (the scripted agent must be re-run). The eval-seed
baseline is regenerated at scoring time by organizers, so no committed
file changes there.

---

## 7. Migration & determinism

All changes are gated behind a configuration flag for one release cycle:

```python
# world/config.py
upgrade_pack_enabled: bool = _bool("UPGRADE_PACK", default=False)
```

Determinism contracts are preserved by:

- **Battery dispatch step** consumes no RNG (auto-policy is deterministic
  in supply/demand)
- **Plant failure weighting** consumes the same single `daily_event_rng`
  draw, just with a weighted choice instead of uniform
- **Hyperbolic decline** is closed-form; no extra RNG
- **CCS capture** is deterministic in the daily emissions total

`test_determinism.py` must add a parameterized variant with the upgrade
pack enabled, asserting byte-identical replay on seed 42.

---

## 8. Out of scope

Explicit non-goals for the upgrade pack — agents and the brief should
not assume these will be added:

- Grid topology / transmission losses / line capacity
- Reactive power, frequency, voltage stability
- Refined product slate (gasoline vs diesel vs jet)
- Reservoir uncertainty quantification (Bayesian updates from production
  history)
- Tile aging / efficiency decay
- Workforce skill levels (workforce.py stays binary staffed/unstaffed)
- Multi-player or scenario editor
- Persistence across container restarts
- Authentication or rate-limiting

---

## Appendix A — Findings from the current build

Read directly from `world/`:

1. **Coal is strictly dominated** (`power.py:155–157` + `catalog.py`
   coal_plant spec). Gas margin > coal margin at every carbon price
   between $0 and $100/t.
2. **Park #1 has zero effect** — `population.py:59`:
   `happiness += 0.05 * max(0, park_count − 1)`.
3. **Happiness is a tripwire** — `population.py:68–77`. Binary gate at
   0.5 means one bad day (24h brownout = −0.48) recovers slowly; one
   bad day with both modes triggers immediate decline.
4. **Pipelines are decorative** — `pipelines.py` routes crude on a
   connectivity check; no capacity, no per-tile fee.
5. **Curtailment is wasted revenue** — `power.py:236–237` and
   `config.py:59` (`grid_price_export=0.04`, half the retail price).
   With no storage, surplus solar/wind is permanently lost value.
6. **Refinery is all-or-nothing** — only one tier ($150k, 500 bbl/day).
   No mid-game refining option.
7. **Reservoir decline is linear** — `subsurface.py:476`:
   `effective_fraction = min(1.0, fraction + pressure_boost)`. Real
   wells decline hyperbolically with rising water cut.
8. **No operational endpoint for plants or batteries** — the brief
   mentions `/control/plant` but it isn't implemented; agents have no
   dispatch knob at all.
9. **Score-cap arithmetic is hardcoded** — `scoring.py:33–36`. The
   0.5/0.4/0.1 split is fine but the population cap of 3× is generous;
   the treasury tanh saturates by ~`T_ref`, making cash-hoard
   strategies non-rewarding.

---

*End of upgrade brief.*
