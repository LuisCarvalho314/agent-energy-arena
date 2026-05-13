"""Shipped stress scenarios (open-source-arena slice 05).

Each module under this package exports a single concrete `Scenario`
subclass with its replay seed declared as a class attribute and its
tuning surface (window start/end days, clip magnitudes, multipliers)
exposed as named class attributes — no magic numbers inside `apply`.

The agent CLI / API loads a scenario by dotted path, e.g.
`load_scenario("scenarios.grid_stress")` resolves to `GridStress`.
"""
