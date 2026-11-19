# Analysis scripts

Run the preparation and exploratory summaries from the project root:

```sh
python3 scripts/prepare_explore.py
```

The script uses only the Python standard library. It reads CSV exports from
`data/raw/` and writes coverage, daily NO₂, separate daily weather, weekday /
weekend, seasonal, and coverage-sensitivity summaries to `data/processed/`. It
does not merge weather stations to air-quality sites or fit models.

Review the source metadata and the provisional aggregation choices in
`02-prepare.md` before using generated weather data in a model.
