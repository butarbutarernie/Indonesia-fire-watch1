"""Data and geospatial logic for Indonesia Fire Watch.

Satellite detections are observations, not confirmed wildfire incidents.
"""
from __future__ import annotations

from io import StringIO
import re
from typing import Any

import geopandas as gpd
import pandas as pd
import requests


BBOX = "94,-12,142,7"  # west,south,east,north
FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/IDN"
SENSORS = {
    "VIIRS NOAA-20 (NRT)": "VIIRS_NOAA20_NRT",
    "VIIRS NOAA-21 (NRT)": "VIIRS_NOAA21_NRT",
}


class DataSourceError(RuntimeError):
    """Raised when an upstream service or file does not provide valid data."""


def build_firms_url(map_key: str, sensor: str, days: int) -> str:
    """Build a NASA FIRMS Area API URL; a single request supports 1-5 days."""
    if not map_key or not re.fullmatch(r"[A-Za-z0-9_-]+", map_key):
        raise ValueError("FIRMS MAP_KEY is missing or invalid.")
    if sensor not in SENSORS.values():
        raise ValueError(f"Unsupported FIRMS sensor: {sensor}")
    if not isinstance(days, int) or not 1 <= days <= 5:
        raise ValueError("NASA FIRMS Area API accepts 1-5 days per request.")
    return f"{FIRMS_BASE}/{map_key}/{sensor}/{BBOX}/{days}"


def parse_firms_csv(csv_text: str, source: str) -> pd.DataFrame:
    """Parse and normalize a VIIRS FIRMS CSV without manufacturing detections."""
    if not csv_text or not csv_text.strip():
        raise DataSourceError("Empty CSV response.")
    try:
        data = pd.read_csv(StringIO(csv_text), low_memory=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise DataSourceError("Could not parse the NASA FIRMS CSV.") from exc

    required = {"latitude", "longitude", "acq_date", "acq_time"}
    missing = required - set(data.columns)
    if missing:
        raise DataSourceError(
            "CSV is not in the expected FIRMS format. Missing: "
            + ", ".join(sorted(missing))
        )

    data = data.copy()
    data["latitude"] = pd.to_numeric(data["latitude"], errors="coerce")
    data["longitude"] = pd.to_numeric(data["longitude"], errors="coerce")
    data = data.dropna(subset=["latitude", "longitude"])
    data = data.loc[
        data["latitude"].between(-90, 90)
        & data["longitude"].between(-180, 180)
    ].copy()

    if "source" not in data.columns:
        data["source"] = source
    else:
        data["source"] = data["source"].fillna(source)
    if "confidence" not in data.columns:
        data["confidence"] = "unknown"
    if "frp" not in data.columns:
        data["frp"] = pd.NA
    if "satellite" not in data.columns:
        data["satellite"] = source

    data["frp"] = pd.to_numeric(data["frp"], errors="coerce")
    data["confidence_raw"] = data["confidence"].astype(str)
    confidence_lookup = {
        "h": "High", "high": "High", "n": "Nominal",
        "nominal": "Nominal", "l": "Low", "low": "Low",
    }
    data["confidence_class"] = (
        data["confidence_raw"].str.strip().str.lower()
        .map(confidence_lookup).fillna("Unknown")
    )

    data["acq_date"] = data["acq_date"].astype(str).str.strip()
    data["acq_time"] = (
        data["acq_time"].astype(str)
        .str.replace(r"\.0$", "", regex=True).str.zfill(4)
    )
    data["acq_datetime_utc"] = pd.to_datetime(
        data["acq_date"] + " " + data["acq_time"],
        format="%Y-%m-%d %H%M", errors="coerce", utc=True,
    )
    data = data.dropna(subset=["acq_datetime_utc"])

    # Only drop identical records, not near-coincident cross-satellite detections.
    data = data.drop_duplicates().reset_index(drop=True)
    return data


def fetch_firms_csv(map_key: str, sensor: str, days: int) -> pd.DataFrame:
    url = build_firms_url(map_key, sensor, days)
    try:
        response = requests.get(
            url, timeout=(12, 90),
            headers={"User-Agent": "IndonesiaFireWatch/1.0 (Streamlit research dashboard)"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # Do not expose the URL because it contains the map key.
        raise DataSourceError(
            f"Could not retrieve FIRMS {sensor}. Check MAP_KEY, network and service status."
        ) from exc
    return parse_firms_csv(response.text, source=sensor)


def fetch_boundary(level: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Fetch full-resolution gbOpen Indonesian boundaries and provenance."""
    if level not in ("ADM0", "ADM1"):
        raise ValueError("Supported admin levels: ADM0 and ADM1.")
    api_url = f"{GEOBOUNDARIES_API}/{level}/"
    try:
        metadata_request = requests.get(api_url, timeout=(12, 35))
        metadata_request.raise_for_status()
        metadata = metadata_request.json()
        download_url = metadata["gjDownloadURL"]
        if not download_url.startswith("https://"):
            raise DataSourceError("Boundary download URL is not HTTPS.")
        geometry_request = requests.get(download_url, timeout=(12, 100))
        geometry_request.raise_for_status()
        geojson = geometry_request.json()
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise DataSourceError(f"Could not load geoBoundaries {level} for Indonesia.") from exc
    if geojson.get("type") != "FeatureCollection" or not geojson.get("features"):
        raise DataSourceError(f"Invalid or empty boundary GeoJSON for {level}.")
    return geojson, {
        "level": level,
        "year": str(metadata.get("boundaryYearRepresented", "Not provided")),
        "source": str(metadata.get("boundarySource", "Not provided")),
        "license": str(metadata.get("boundaryLicense", "See geoBoundaries")),
        "boundary_id": str(metadata.get("boundaryID", "Not provided")),
    }


def geojson_to_gdf(geojson: dict[str, Any]) -> gpd.GeoDataFrame:
    if geojson.get("type") != "FeatureCollection" or not geojson.get("features"):
        raise DataSourceError("Boundary data must be a non-empty GeoJSON FeatureCollection.")
    gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
    if gdf.empty:
        raise DataSourceError("Boundary layer contains no features.")
    return gdf.loc[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()


def assign_country_and_province(
    df: pd.DataFrame,
    national_geojson: dict[str, Any],
    provincial_geojson: dict[str, Any],
) -> pd.DataFrame:
    """Perform actual spatial clipping, then annotate provinces.

    The national bbox alone is NOT used to classify a point as Indonesian.
    """
    required = {"latitude", "longitude"}
    if required - set(df.columns):
        raise DataSourceError("Data lacks latitude and/or longitude fields.")

    countries = geojson_to_gdf(national_geojson)
    provinces = geojson_to_gdf(provincial_geojson)
    name_candidates = ("shapeName", "NAME_1", "name", "NAME", "province")
    province_col = next((name for name in name_candidates if name in provinces.columns), None)
    if province_col is None:
        raise DataSourceError("No province name column in ADM1 boundary file.")

    if df.empty:
        out = df.copy()
        out["province"] = pd.Series(dtype="str")
        return out

    data = df.drop(columns=["index_right", "__row_id", "province", "geometry"], errors="ignore").copy()
    data["__row_id"] = range(len(data))
    points = gpd.GeoDataFrame(
        data,
        geometry=gpd.points_from_xy(data["longitude"], data["latitude"]),
        crs="EPSG:4326",
    )
    within_country = gpd.sjoin(
        points, countries[["geometry"]], how="inner", predicate="intersects",
    )
    if within_country.empty:
        out = data.iloc[:0].copy()
        out["province"] = pd.Series(dtype="str")
        return out.drop(columns=["__row_id"], errors="ignore")

    within_country = within_country.drop(columns=["index_right"])
    within_country = within_country.drop_duplicates(subset=["__row_id"])
    admin = provinces[[province_col, "geometry"]].rename(columns={province_col: "province"})
    attributed = gpd.sjoin(
        within_country, admin, how="left", predicate="intersects",
    )
    # Border intersections can match two polygons. Keep one per detection.
    attributed = attributed.sort_values(["__row_id", "province"], na_position="last")
    attributed = attributed.drop_duplicates(subset=["__row_id"])
    attributed["province"] = attributed["province"].fillna("Province not identified")
    attributed = attributed.sort_values("__row_id")
    return pd.DataFrame(
        attributed.drop(columns=["geometry", "index_right", "__row_id"], errors="ignore")
    ).reset_index(drop=True)

# v2: NASA API single-call maximum is five days. For seven days use 5 most
# recent UTC dates and an older, explicit 2-day window; no overlapping dates.
from datetime import datetime, timedelta, timezone  # noqa: E402


def build_firms_url_dated(map_key: str, sensor: str, days: int, start_date=None) -> str:
    base = build_firms_url(map_key, sensor, days)
    if start_date is None:
        return base
    try:
        from datetime import date
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        if not isinstance(start_date, date):
            raise ValueError("Invalid date")
    except ValueError as exc:
        raise ValueError("Tanggal awal harus berformat ISO YYYY-MM-DD.") from exc
    return f"{base}/{start_date.isoformat()}"


def fetch_recent_firms(map_key: str, sensor: str, days: int, today_utc=None) -> pd.DataFrame:
    """Fetch 1,2,3,5,7 recent UTC calendar dates, not continuous rolling hours."""
    if days not in (1, 2, 3, 5, 7):
        raise ValueError("Periode FIRMS yang didukung: 1, 2, 3, 5, 7 hari.")
    from datetime import date
    current = today_utc or datetime.now(timezone.utc).date()
    if isinstance(current, str):
        current = date.fromisoformat(current)
    if days <= 5:
        # Date is explicit to make the window reproducible across midnight UTC.
        start = current - timedelta(days=days - 1)
        windows = [(days, start)]
    else:
        windows = [(2, current - timedelta(days=6)), (5, current - timedelta(days=4))]
    chunks = []
    for window_days, start in windows:
        url = build_firms_url_dated(map_key, sensor, window_days, start)
        try:
            response = requests.get(
                url, timeout=(12, 90),
                headers={"User-Agent": "IndonesiaFireWatch/2.0 (Streamlit research dashboard)"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            # URL contains MAP_KEY, so NEVER include response URL/exception in UI/logs.
            raise DataSourceError(
                f"Gagal mengambil data FIRMS {sensor}; periksa API key dan status NASA."
            ) from exc
        chunks.append(parse_firms_csv(response.text, source=sensor))
    if not chunks:
        return pd.DataFrame()
    out = pd.concat(chunks, ignore_index=True).drop_duplicates()
    start_date = current - timedelta(days=days - 1)
    return out.loc[
        (out["acq_datetime_utc"].dt.date >= start_date)
        & (out["acq_datetime_utc"].dt.date <= current)
    ].reset_index(drop=True)
