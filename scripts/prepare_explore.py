from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUTPUT_DIR = ROOT / "data" / "processed"
YEAR = 2024
TIME_ZONE = ZoneInfo("Europe/Helsinki")
MINIMUM_DAILY_COVERAGE = 0.75
TIME_COLUMNS = {
    "Observation station",
    "Year",
    "Month",
    "Day",
    "Time [Local time]",
}


def expected_hours(day: date) -> int:
    start = datetime.combine(day, time.min, TIME_ZONE).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, TIME_ZONE).astimezone(
        timezone.utc
    )
    return int((end - start).total_seconds() // 3600)


def parse_value(raw: str | None) -> float | None:
    if raw is None or not raw.strip() or raw.strip() == "-":
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def read_file(path: Path) -> tuple[str, list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError(f"{path.name}: missing CSV header")
        missing_columns = TIME_COLUMNS.difference(reader.fieldnames)
        if missing_columns:
            raise ValueError(f"{path.name}: missing columns {sorted(missing_columns)}")
        value_columns = [column for column in reader.fieldnames if column not in TIME_COLUMNS]
        rows = []
        stations = set()
        for line_number, raw in enumerate(reader, start=2):
            try:
                stamp = datetime(
                    int(raw["Year"]),
                    int(raw["Month"]),
                    int(raw["Day"]),
                    int(raw["Time [Local time]"][:2]),
                    int(raw["Time [Local time]"][3:5]),
                )
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path.name}:{line_number}: invalid local timestamp") from error
            if stamp.year != YEAR:
                raise ValueError(f"{path.name}:{line_number}: expected year {YEAR}")
            station = raw["Observation station"].strip()
            stations.add(station)
            rows.append(
                {
                    "timestamp": stamp,
                    "date": stamp.date(),
                    "station": station,
                    "raw": {column: raw.get(column, "") or "" for column in value_columns},
                }
            )
    if len(stations) != 1:
        raise ValueError(f"{path.name}: expected one station, found {sorted(stations)}")
    return stations.pop(), value_columns, rows


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def date_grid() -> list[date]:
    first = date(YEAR, 1, 1)
    return [first + timedelta(days=offset) for offset in range(366)]


def summarize_source(path: Path, station: str, columns: list[str], rows: list[dict]) -> list[dict]:
    duplicate_rows = sum(count - 1 for count in Counter(r["timestamp"] for r in rows).values())
    by_day: dict[date, list[dict]] = defaultdict(list)
    for row in rows:
        by_day[row["date"]].append(row)

    summaries = []
    for column in columns:
        values = [parse_value(row["raw"][column]) for row in rows]
        valid_values = [value for value in values if value is not None]
        valid_days = 0
        for day in date_grid():
            observed = sum(
                parse_value(row["raw"][column]) is not None for row in by_day[day]
            )
            valid_days += observed >= math.ceil(expected_hours(day) * MINIMUM_DAILY_COVERAGE)
        summaries.append(
            {
                "station": station,
                "source_file": path.name,
                "variable": column,
                "rows": len(rows),
                "distinct_local_timestamps": len({row["timestamp"] for row in rows}),
                "extra_duplicate_local_timestamp_rows": duplicate_rows,
                "first_local_timestamp": min(row["timestamp"] for row in rows).isoformat(sep=" "),
                "last_local_timestamp": max(row["timestamp"] for row in rows).isoformat(sep=" "),
                "valid_values": len(valid_values),
                "missing_or_unparseable_values": len(values) - len(valid_values),
                "nonpositive_values": sum(value <= 0 for value in valid_values),
                "minimum": min(valid_values) if valid_values else "",
                "mean": round(sum(valid_values) / len(valid_values), 4) if valid_values else "",
                "maximum": max(valid_values) if valid_values else "",
                "days_meeting_75pct_coverage": valid_days,
                "days_in_year": len(date_grid()),
            }
        )
    return summaries


def prepare_no2(path: Path, station: str, column: str, rows: list[dict]) -> list[dict]:
    by_day: dict[date, list[float]] = defaultdict(list)
    for row in rows:
        value = parse_value(row["raw"][column])
        if value is not None:
            by_day[row["date"]].append(value)

    result = []
    for day in date_grid():
        values = by_day[day]
        expected = expected_hours(day)
        adequate = len(values) >= math.ceil(expected * MINIMUM_DAILY_COVERAGE)
        result.append(
            {
                "date": day.isoformat(),
                "station": station,
                "no2_daily_mean_ug_m3": round(sum(values) / len(values), 4) if adequate else "",
                "valid_hourly_values": len(values),
                "expected_local_hours": expected,
                "coverage_pct": round(100 * len(values) / expected, 2),
                "meets_75pct_coverage": adequate,
            }
        )
    return result


def no2_coverage_sensitivity(
    station: str, column: str, rows: list[dict]
) -> list[dict]:
    by_day: dict[date, list[float]] = defaultdict(list)
    for row in rows:
        value = parse_value(row["raw"][column])
        if value is not None:
            by_day[row["date"]].append(value)

    summaries = []
    for threshold in (0.75, 0.90, 1.00):
        accepted = []
        for day in date_grid():
            values = by_day[day]
            required = math.ceil(expected_hours(day) * threshold)
            if len(values) >= required:
                accepted.append((day, sum(values) / len(values)))
        weekday_values = [value for day, value in accepted if day.weekday() < 5]
        weekend_values = [value for day, value in accepted if day.weekday() >= 5]
        weekday_mean = (
            sum(weekday_values) / len(weekday_values) if weekday_values else None
        )
        weekend_mean = (
            sum(weekend_values) / len(weekend_values) if weekend_values else None
        )
        summaries.append(
            {
                "station": station,
                "minimum_daily_coverage_pct": int(threshold * 100),
                "valid_days": len(accepted),
                "weekday_days": len(weekday_values),
                "weekday_mean_ug_m3": round(weekday_mean, 4)
                if weekday_mean is not None
                else "",
                "weekend_days": len(weekend_values),
                "weekend_mean_ug_m3": round(weekend_mean, 4)
                if weekend_mean is not None
                else "",
                "weekend_minus_weekday_ug_m3": round(weekend_mean - weekday_mean, 4)
                if weekday_mean is not None and weekend_mean is not None
                else "",
            }
        )
    return summaries


def prepare_weather(
    station: str, columns: list[str], rows: list[dict]
) -> list[dict]:
    by_day: dict[date, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for column in columns:
            value = parse_value(row["raw"][column])
            if value is not None:
                by_day[row["date"]][column].append(value)

    result = []
    for day in date_grid():
        expected = expected_hours(day)
        day_values = by_day[day]
        output = {
            "date": day.isoformat(),
            "weather_station": station,
            "expected_local_hours": expected,
        }
        for column in columns:
            values = day_values[column]
            adequate = len(values) >= math.ceil(expected * MINIMUM_DAILY_COVERAGE)
            if "temperature" in column.lower():
                output["mean_temperature_c"] = (
                    round(sum(values) / len(values), 4) if adequate else ""
                )
                output["temperature_valid_hours"] = len(values)
            elif "wind" in column.lower():
                output["mean_hourly_max_wind_speed_m_s"] = (
                    round(sum(values) / len(values), 4) if adequate else ""
                )
                output["wind_valid_hours"] = len(values)
            elif "precipitation" in column.lower():
                output["sum_reported_precipitation_mm"] = (
                    round(sum(values), 4) if adequate else ""
                )
                output["precipitation_valid_hours"] = len(values)
            else:
                raise ValueError(f"Unrecognized weather variable {column!r}")
        result.append(output)
    return result


def no2_summaries(daily_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    station_days: dict[str, list[dict]] = defaultdict(list)
    for row in daily_rows:
        if row["no2_daily_mean_ug_m3"] != "":
            station_days[row["station"]].append(row)

    weekend_rows = []
    seasonal_rows = []
    seasons = {
        "winter": {12, 1, 2},
        "spring": {3, 4, 5},
        "summer": {6, 7, 8},
        "autumn": {9, 10, 11},
    }
    for station, rows in sorted(station_days.items()):
        parsed = [
            (date.fromisoformat(row["date"]), float(row["no2_daily_mean_ug_m3"]))
            for row in rows
        ]
        weekday_values = [value for day, value in parsed if day.weekday() < 5]
        weekend_values = [value for day, value in parsed if day.weekday() >= 5]
        weekday_mean = sum(weekday_values) / len(weekday_values)
        weekend_mean = sum(weekend_values) / len(weekend_values)
        weekend_rows.append(
            {
                "station": station,
                "daily_coverage_rule": "at least 75% of expected local hourly slots",
                "valid_days": len(parsed),
                "weekday_days": len(weekday_values),
                "weekday_mean_ug_m3": round(weekday_mean, 4),
                "weekend_days": len(weekend_values),
                "weekend_mean_ug_m3": round(weekend_mean, 4),
                "weekend_minus_weekday_ug_m3": round(weekend_mean - weekday_mean, 4),
            }
        )
        for season, months in seasons.items():
            values = [value for day, value in parsed if day.month in months]
            seasonal_rows.append(
                {
                    "station": station,
                    "season": season,
                    "valid_days": len(values),
                    "mean_daily_no2_ug_m3": round(sum(values) / len(values), 4)
                    if values
                    else "",
                }
            )
    return weekend_rows, seasonal_rows


def main() -> None:
    if not RAW_DIR.is_dir():
        raise FileNotFoundError(f"Raw-data directory not found: {RAW_DIR}")
    files = sorted(RAW_DIR.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {RAW_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    coverage_rows = []
    no2_daily_rows = []
    sensitivity_rows = []
    weather_daily_rows = []

    for path in files:
        station, columns, rows = read_file(path)
        coverage_rows.extend(summarize_source(path, station, columns, rows))
        no2_columns = [column for column in columns if column.lower().startswith("nitrogen dioxide")]
        if no2_columns:
            if len(no2_columns) != 1:
                raise ValueError(f"{path.name}: expected one nitrogen dioxide column")
            no2_daily_rows.extend(prepare_no2(path, station, no2_columns[0], rows))
            sensitivity_rows.extend(
                no2_coverage_sensitivity(station, no2_columns[0], rows)
            )
        else:
            weather_daily_rows.extend(prepare_weather(station, columns, rows))

    weekend_rows, seasonal_rows = no2_summaries(no2_daily_rows)
    write_csv(
        OUTPUT_DIR / "coverage.csv",
        [
            "station", "source_file", "variable", "rows", "distinct_local_timestamps",
            "extra_duplicate_local_timestamp_rows", "first_local_timestamp",
            "last_local_timestamp", "valid_values", "missing_or_unparseable_values",
            "nonpositive_values", "minimum", "mean", "maximum",
            "days_meeting_75pct_coverage", "days_in_year",
        ],
        coverage_rows,
    )
    write_csv(
        OUTPUT_DIR / "no2_daily.csv",
        [
            "date", "station", "no2_daily_mean_ug_m3", "valid_hourly_values",
            "expected_local_hours", "coverage_pct", "meets_75pct_coverage",
        ],
        no2_daily_rows,
    )
    if weather_daily_rows:
        weather_columns = list(dict.fromkeys(key for row in weather_daily_rows for key in row))
        write_csv(OUTPUT_DIR / "weather_daily.csv", weather_columns, weather_daily_rows)
    write_csv(
        OUTPUT_DIR / "no2_weekend_summary.csv",
        [
            "station", "daily_coverage_rule", "valid_days", "weekday_days",
            "weekday_mean_ug_m3", "weekend_days", "weekend_mean_ug_m3",
            "weekend_minus_weekday_ug_m3",
        ],
        weekend_rows,
    )
    write_csv(
        OUTPUT_DIR / "no2_season_summary.csv",
        ["station", "season", "valid_days", "mean_daily_no2_ug_m3"],
        seasonal_rows,
    )
    write_csv(
        OUTPUT_DIR / "no2_coverage_sensitivity.csv",
        [
            "station", "minimum_daily_coverage_pct", "valid_days", "weekday_days",
            "weekday_mean_ug_m3", "weekend_days", "weekend_mean_ug_m3",
            "weekend_minus_weekday_ug_m3",
        ],
        sensitivity_rows,
    )
    print(f"Processed {len(files)} source CSVs; outputs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
