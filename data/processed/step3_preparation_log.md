# Preparation log

- Source exports were preserved unchanged in `data/raw/`.
- Daily air-quality and weather windows use Europe/Helsinki local calendar dates.
- NO2 columns are numeric; `-` and blanks are missing. The provisional completeness rule is at least 75% of expected local hourly slots (rounded up). This rule was applied consistently across 2024.
- Provider quality/validation columns were not present in the supplied exports. Negative and zero readings were retained in the source coverage audit and are not silently converted; they need provider convention confirmation before likelihood selection.
- The daily outcome is the arithmetic mean of valid hourly NO2 readings when the day meets the completeness rule; otherwise the daily NO2 outcome is missing.
- Weather is aggregated from the supplied weather exports to local calendar-day values. Maximum wind-speed fields are treated as mean hourly maxima, not mean wind speed. Precipitation and temperature conventions remain provisional until parameter metadata is confirmed.
- The joined station-day table contains only the assigned weather station ID for each NO2 station.
- Missingness is reported separately by station, season, and weekday/weekend status in `step3_missingness_by_calendar.csv`.
