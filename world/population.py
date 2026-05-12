"""Population dynamics + daily tax revenue (brief §4.8).

A single end-of-day routine, `update_population(world)`, that:

  1. Sums housing capacity and jobs from the current tile set.
  2. Computes happiness from a spatial park benefit (averaged over
     houses), a noise penalty from industrial/refinery tiles near
     houses (halved by an intervening park), prior-day blackout +
     brownout hours, and a coal-proximity term.
  3. Selects exactly one of four cascading branches — grow, housing-exodus,
     job-driven decline, or happiness decline — matching the brief's
     pseudocode line-for-line.
  4. Accrues `DAILY_TAX_PER_CAPITA × population` to the treasury and to
     `state.today_summary_so_far["tax_revenue"]`.

No RNG is consumed here; the determinism contract in `sim._advance_one_day`
is unaffected as long as this is called *outside* the mandatory daily
`sim_rng.standard_normal()` draw.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world import workforce

if TYPE_CHECKING:
    from world.sim import World

DAILY_TAX_PER_CAPITA: float = 4.0

# Per-hour outage penalties. The brief's daily-aggregate
# `-0.10 * (yest_blackout_hours / 24)` capped happiness loss at 0.10 even
# under 24h/day blackouts, leaving population effectively immune. Per-hour
# coefficients make the brief's "blackouts cost happiness" wording bite;
# after the §3.3 smooth-growth rewrite the decline threshold is 0.3, so
# 15h+ of blackout (0.05 × 15 = 0.75 → h≤0.25) trips the decline branch.
BLACKOUT_HAPPINESS_PER_HOUR: float = 0.05
BROWNOUT_HAPPINESS_PER_HOUR: float = 0.02


def update_population(world: World) -> None:
    state = world.state
    config = world.config

    capacity = sum(t.housing_capacity for t in state.tiles)
    jobs = sum(t.jobs for t in state.tiles)
    parks = [t for t in state.tiles if t.type == "park"]
    houses = [t for t in state.tiles if t.type == "house"]
    house_count = len(houses)
    noise_sources = [t for t in state.tiles if t.type in ("industrial", "refinery")]

    # Coal-proximity term: chebyshev distance ≤ 3 between any house and any
    # operational coal plant. PRD §"Subsurface" pins chebyshev as the metric.
    coal_plants = [t for t in state.tiles if t.type == "coal_plant" and t.operational]
    coal_houses_within_3 = sum(
        1 for h in houses if any(max(abs(h.x - c.x), abs(h.y - c.y)) <= 3 for c in coal_plants)
    )

    # Park benefit: per-house min(0.30, 0.10 * nearby_parks_within_chebyshev_2),
    # averaged over houses. Noise penalty: per-house -0.03 per industrial/refinery
    # within chebyshev-2, halved to -0.015 if any park sits within chebyshev-2 of
    # both the house and the source. Averaged over houses.
    park_benefit = 0.0
    noise_penalty = 0.0
    if house_count > 0:
        bonus_total = 0.0
        penalty_total = 0.0
        for h in houses:
            nearby_parks = [p for p in parks if max(abs(h.x - p.x), abs(h.y - p.y)) <= 2]
            bonus_total += min(0.30, 0.10 * len(nearby_parks))
            for src in noise_sources:
                if max(abs(h.x - src.x), abs(h.y - src.y)) > 2:
                    continue
                shielded = any(
                    max(abs(h.x - p.x), abs(h.y - p.y)) <= 2
                    and max(abs(src.x - p.x), abs(src.y - p.y)) <= 2
                    for p in parks
                )
                penalty_total += 0.015 if shielded else 0.03
        park_benefit = bonus_total / house_count
        noise_penalty = penalty_total / house_count

    happiness = 1.0
    happiness += park_benefit
    happiness -= noise_penalty
    happiness -= BLACKOUT_HAPPINESS_PER_HOUR * state.yesterday_blackout_hours
    happiness -= BROWNOUT_HAPPINESS_PER_HOUR * state.yesterday_brownout_hours
    happiness -= 0.05 * coal_houses_within_3 / max(1, house_count)
    happiness = max(0.0, min(1.5, happiness))

    pop_before = state.population
    pop = float(pop_before)

    if jobs >= pop and capacity > pop and happiness >= 0.3:
        growth_multiplier = max(0.0, (happiness - 0.3) / 1.2)
        growth = config.base_growth_rate * pop * growth_multiplier
        growth = min(growth, capacity - pop, jobs - pop)
        pop = pop + growth
    elif capacity < pop:
        pop = max(float(capacity), pop - 5.0)
    elif jobs < 0.7 * pop:
        pop = max(jobs / 0.7, pop * 0.99)
    elif happiness < 0.3:
        pop = pop * 0.99

    target_pop = max(0, int(pop))
    delta = pop_before - target_pop
    if delta > 0:
        workforce.drain_n(state, delta)
    elif delta < 0:
        state.population = target_pop
        workforce.hire_to_fill(state)
    state.happiness = happiness

    tax = DAILY_TAX_PER_CAPITA * state.population
    state.treasury += tax
    state.today_summary_so_far["tax_revenue"] = tax
