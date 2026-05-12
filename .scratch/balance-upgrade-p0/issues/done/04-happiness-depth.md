Status: needs-triage

## Parent

PRD: `.scratch/balance-upgrade-p0/PRD.md`

## What to build

Give happiness spatial depth and replace the binary growth tripwire with a smooth ramp, so park placement and zoning become real decisions and a single bad day no longer permanently zeroes growth.

- **Remove** the flat `happiness += 0.05 * park_count` term entirely.
- **Park benefit**, averaged over houses:
  ```
  bonus_per_house = min(0.30, 0.10 * nearby_parks_within_chebyshev_2)
  park_benefit = mean(bonus_per_house for each house), or 0 if no houses
  ```
- **Noise penalty** from industrial + refinery tiles within Chebyshev-2 of a house: -0.03 per source, halved to -0.015 if any park sits within Chebyshev-2 of both the house and the source. Averaged over houses.
- **Smooth growth gate** replaces the binary 0.5 cutoff:
  ```
  growth_multiplier = max(0.0, (happiness - 0.3) / 1.2)
  growth = base_growth_rate * pop * growth_multiplier
  ```
  At h=1.0 this gives 58% of base growth (intentional rebalance); at h=1.5 it gives 100%.
- Decline branch threshold shifts from `happiness < 0.5` to `happiness < 0.3` to stay consistent with the new gate.
- The park-#1 off-by-one is fixed implicitly — no `park_count - 1` anywhere.

## Acceptance criteria

- [ ] `test_first_park_within_chebyshev_2_of_house_contributes` in `test_population.py`.
- [ ] `test_park_outside_chebyshev_2_contributes_zero` (regression for radius rule).
- [ ] `test_industrial_adjacent_to_house_drops_happiness`.
- [ ] `test_park_between_industrial_and_house_halves_penalty`.
- [ ] `test_smooth_growth_at_happiness_0_6` (multiplier = 0.25 ± epsilon).
- [ ] `test_growth_zero_at_happiness_below_0_3` (regression for new decline threshold).
- [ ] `make check` passes.

## Blocked by

None - can start immediately.
