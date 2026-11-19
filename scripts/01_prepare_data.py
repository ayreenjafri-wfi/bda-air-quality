import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

# Paths relative to repository root (bda-2026/)
REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

AQ_FILES = {
    "100762": {
        "name": "Helsinki Mäkelänkatu",
        "env": "Urban traffic",
        "file": "Helsinki Mäkelänkatu_ 1.1.2024 - 31.12.2024_48ee77b9-d804-4e3b-a0e2-dd8c5a8782d5.csv",
        "weather_id": "101004",  # Kumpula
    },
    "100662": {
        "name": "Helsinki Kallio 2",
        "env": "Urban background",
        "file": "Helsinki Kallio 2_ 1.1.2024 - 31.12.2024_80609b8b-f3aa-4e8c-bfbb-66f8d7cf2010.csv",
        "weather_id": "100971",  # Kaisaniemi
    },
    "100691": {
        "name": "Espoo Leppävaara Läkkisepänkuja",
        "env": "Urban traffic",
        "file": "Espoo Leppävaara Läkkisepänkuja_ 1.1.2024 - 31.12.2024_1b316b47-3cf3-44e2-9c22-7dd8dfaaa7fd.csv",
        "weather_id": "100971",  # Kaisaniemi
    },
    "100763": {
        "name": "Vantaa Tikkurila Neilikkatie",
        "env": "Urban traffic",
        "file": "Vantaa Tikkurila Neilikkatie_ 1.1.2024 - 31.12.2024_4d73082a-f003-47c1-bbbc-121395434ef0.csv",
        "weather_id": "100968",  # Helsinki-Vantaa airport
    },
}

WEATHER_FILES = {
    "100971": {
        "name": "Helsinki Kaisaniemi",
        "file": "Helsinki Kaisaniemi_ 1.1.2024 - 31.12.2024_e85ace4e-83be-4d3d-b916-7806d99c6b2d.csv",
    },
    "101004": {
        "name": "Helsinki Kumpula",
        "file": "Helsinki Kumpula_ 1.1.2024 - 31.12.2024_51f3ca23-ed4c-43f5-8359-1a77c3e3921f.csv",
    },
    "100968": {
        "name": "Helsinki-Vantaa airport",
        "file": "Helsinki-Vantaa airport_ 1.1.2024 - 31.12.2024_1d9b9e1b-b19a-41cc-a5a2-1bde6a20b6ca.csv",
    },
}


def sha256_checksum(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_fmi_csv(filepath: Path) -> pd.DataFrame:
    df = pd.read_csv(filepath, na_values=["-", ""], encoding="utf-8", encoding_errors="replace")
    df.columns = [c.replace("碌g/m3", "µg/m3").strip() for c in df.columns]
    df["date"] = pd.to_datetime(df[["Year", "Month", "Day"]])
    return df


def find_column(df: pd.DataFrame, label: str) -> str:
    matches = [column for column in df.columns if label in column.casefold()]
    if len(matches) != 1:
        raise ValueError(f"Expected one column containing {label!r}; found {matches}")
    return matches[0]


# --- STEP 2: Generate Provenance Manifest ---
manifest = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "provider": "Finnish Meteorological Institute (FMI) / HSY Air Quality Monitoring",
    "source_url": "https://ilmatieteenlaitos.fi",
    "license": "CC BY 4.0 (https://ilmatieteenlaitos.fi)",
    "query_parameters": {
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "timezone": "Europe/Helsinki (Local time)",
        "resolution": "1 hour",
    },
    "files": [],
}

for category, group in [("air_quality", AQ_FILES), ("weather", WEATHER_FILES)]:
    for fmisid, meta in group.items():
        fpath = RAW_DIR / meta["file"]
        manifest["files"].append({
            "category": category,
            "fmisid": fmisid,
            "station_name": meta["name"],
            "filename": meta["file"],
            "sha256": sha256_checksum(fpath),
            "size_bytes": fpath.stat().st_size,
        })

with open(PROCESSED_DIR / "provenance_manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)


# --- STEP 1 & 3: Coverage Table & Daily Aggregation ---
aq_daily_list = []
coverage_records = []

for station_id, meta in AQ_FILES.items():
    df = load_fmi_csv(RAW_DIR / meta["file"])
    no2_col = find_column(df, "nitrogen dioxide")
    df[no2_col] = pd.to_numeric(df[no2_col], errors="coerce")
    df = df[df["Year"] == 2024].copy()

    non_positive_hours = int((df[no2_col] <= 0).sum())

    daily = df.groupby("date", as_index=False).agg(
        no2_daily=(no2_col, "mean"),
        valid_hours=(no2_col, "count"),
        expected_hours=(no2_col, "size"),
    )
    daily["station_id"] = station_id
    daily["station_name"] = meta["name"]
    daily["environment"] = meta["env"]
    daily["weather_station_id"] = meta["weather_id"]
    daily["completeness_pct"] = (daily["valid_hours"] / daily["expected_hours"]) * 100
    daily["usable_day"] = daily["completeness_pct"] >= 75.0
    daily.loc[~daily["usable_day"], "no2_daily"] = np.nan

    aq_daily_list.append(daily)
    coverage_records.append({
        "station_id": station_id,
        "station_name": meta["name"],
        "environment": meta["env"],
        "start_date": daily["date"].min().strftime("%Y-%m-%d"),
        "end_date": daily["date"].max().strftime("%Y-%m-%d"),
        "total_days": len(daily),
        "usable_days": int(daily["usable_day"].sum()),
        "missing_days": int((~daily["usable_day"]).sum()),
        "non_positive_hours": non_positive_hours,
        "weather_station_id": meta["weather_id"],
    })

coverage_df = pd.DataFrame(coverage_records)
coverage_df.to_csv(PROCESSED_DIR / "step1_coverage_table.csv", index=False)

weather_daily_list = []
for w_id, meta in WEATHER_FILES.items():
    wdf = load_fmi_csv(RAW_DIR / meta["file"])
    wdf = wdf[wdf["Year"] == 2024].copy()

    wind_col = find_column(wdf, "wind speed")
    temp_col = find_column(wdf, "temperature")
    precip_col = find_column(wdf, "precipitation")

    for col in [wind_col, temp_col, precip_col]:
        wdf[col] = pd.to_numeric(wdf[col], errors="coerce")

    w_daily = wdf.groupby("date", as_index=False).agg(
        wind_speed=(wind_col, "mean"),
        temperature=(temp_col, "mean"),
        precipitation=(precip_col, lambda s: s.sum(min_count=18)),
    )
    w_daily["weather_station_id"] = w_id
    weather_daily_list.append(w_daily)

weather_all = pd.concat(weather_daily_list, ignore_index=True)

analysis_df = (
    pd.concat(aq_daily_list, ignore_index=True)
    .merge(weather_all, on=["date", "weather_station_id"], how="left")
    .assign(
        weekend=lambda d: (d["date"].dt.dayofweek >= 5).astype(int),
        day_of_year=lambda d: d["date"].dt.dayofyear,
    )
)

cols = [
    "station_id", "station_name", "environment", "date",
    "no2_daily", "valid_hours", "expected_hours", "usable_day",
    "wind_speed", "temperature", "precipitation",
    "weekend", "day_of_year", "weather_station_id",
]
analysis_df = analysis_df[cols].sort_values(["station_id", "date"]).reset_index(drop=True)
analysis_df.to_csv(PROCESSED_DIR / "step3_analysis_table.csv", index=False)

print("Coverage Table:\n", coverage_df.to_string(index=False))
