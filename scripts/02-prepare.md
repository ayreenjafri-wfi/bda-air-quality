# 02-prepare

Run `python3 scripts/prepare_explore.py` from the project root. It:

- Reads the original CSV exports without modifying them.
- Treats `-`, blank, and unparsable measurement strings as missing; retains numeric NO₂ values, including nonpositive values, pending provider guidance.
- Groups observations by Helsinki local calendar date and preserves repeated fall-back clock-hour records.
- Computes expected hours for each local date (23, 24, or 25) and emits a daily value only when at least 75% of expected hourly observations are valid. Daily coverage counts remain in the output.
- Writes `coverage.csv`, `no2_daily.csv`, and separate `weather_daily.csv` files to `data/processed/`.

The 75% threshold is provisional and matches the candidate in `docs/decisions.md`.
No quality flags are present in the supplied CSV columns. Before modeling, verify
the provider's validation status, nonpositive-value conventions, units, station
identity, and timestamps. Weather data stay separate until the station matching
rule and precipitation accumulation period are confirmed; `weather_daily.csv`
contains provisional descriptive aggregates, not model-ready matched covariates.
