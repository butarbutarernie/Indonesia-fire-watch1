"""Indonesia Fire Watch - all-Indonesia VIIRS active-fire monitoring.

Deploy this file as the Streamlit entrypoint. FIRMS MAP_KEY is a secret.
"""
from __future__ import annotations

import io
import json
import os

import geopandas as gpd
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

from firewatch_core import (
    DataSourceError,
    SENSORS,
    assign_country_and_province,
    fetch_boundary,
    fetch_firms_csv,
    geojson_to_gdf,
    parse_firms_csv,
)


st.set_page_config(
    page_title="Indonesia Fire Watch",
    page_icon="\U0001F6F0",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.1rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {background: #f3f6fa; border-radius: 12px; padding: 13px;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_firms_data(key: str, sensor: str, days: int) -> pd.DataFrame:
    return fetch_firms_csv(key, sensor, days)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def cached_boundary(level: str):
    return fetch_boundary(level)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def map_province_boundaries(geojson: dict) -> dict:
    gdf = geojson_to_gdf(geojson)
    # Simplification is ONLY for faster map drawing; full polygons are used in QC.
    simplified = gdf[["geometry"]].copy()
    simplified["geometry"] = simplified.geometry.simplify(
        tolerance=0.015, preserve_topology=True
    )
    return json.loads(simplified.to_json())


def get_map_key() -> str:
    key = os.environ.get("FIRMS_MAP_KEY", "")
    if key:
        return key.strip()
    try:
        return str(st.secrets.get("FIRMS_MAP_KEY", "")).strip()
    except (FileNotFoundError, KeyError, RuntimeError):
        return ""


def show_map(df: pd.DataFrame, boundary_for_display: dict, point_limit: int):
    map_df = df.copy()
    sampled = len(map_df) > point_limit
    if sampled:
        # Deterministic rendering sample, independent of analytic statistics.
        map_df = map_df.sample(n=point_limit, random_state=2026)
    colors = {
        "High": [224, 53, 45, 215],
        "Nominal": [253, 131, 44, 195],
        "Low": [250, 204, 58, 190],
        "Unknown": [100, 134, 170, 170],
    }
    map_df = map_df[[
        "latitude", "longitude", "acq_date", "acq_time", "province",
        "confidence_class", "frp", "source",
    ]].copy()
    map_df["color"] = map_df["confidence_class"].map(
        lambda c: colors.get(c, colors["Unknown"])
    )
    map_df["frp"] = map_df["frp"].round(1)

    layers = [
        pdk.Layer(
            "GeoJsonLayer", data=boundary_for_display, stroked=True, filled=False,
            get_line_color=[61, 91, 122, 150], line_width_min_pixels=0.6,
            pickable=False,
        ),
        pdk.Layer(
            "ScatterplotLayer", data=map_df, get_position="[longitude, latitude]",
            get_fill_color="color", get_radius=650, radius_min_pixels=2,
            radius_max_pixels=7, opacity=0.82, pickable=True,
        ),
    ]
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=-2.5, longitude=118.0, zoom=4),
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={
            "html": "<b>{province}</b><br/>Date UTC: {acq_date} {acq_time}"
                    "<br/>Confidence: {confidence_class}<br/>FRP: {frp} MW"
                    "<br/>Sensor: {source}",
            "style": {"color": "white", "backgroundColor": "#182534"},
        },
    )
    st.pydeck_chart(deck, use_container_width=True)
    if sampled:
        st.caption(
            f"Map displays a reproducible sample of {point_limit:,} out of "
            f"{len(df):,} detections. All statistics and exports use the full filtered dataset."
        )


def geojson_download(df: pd.DataFrame) -> str:
    export_cols = [
        "acq_date", "acq_time", "province", "source", "confidence_class", "frp",
    ]
    all_features = []
    for row in df[["latitude", "longitude"] + export_cols].itertuples(index=False, name=None):
        latitude, longitude, *vals = row
        properties = {}
        for k, value in zip(export_cols, vals):
            if pd.isna(value):
                properties[k] = None
            elif isinstance(value, (int, float, str, bool)):
                properties[k] = value
            else:
                properties[k] = str(value)
        all_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(longitude), float(latitude)]},
            "properties": properties,
        })
    return json.dumps({"type": "FeatureCollection", "features": all_features}, ensure_ascii=False)


# ----- Page header -----
st.title("Indonesia Fire Watch")
st.caption("Satellite-based active-fire detection | NASA FIRMS VIIRS | All Indonesian islands")
st.info(
    "A hotspot is a satellite-observed thermal anomaly, **not** a confirmed fire "
    "incident or a measurement of burned area. Multiple sensors/overpasses may "
    "detect the same fire more than once.", icon="\u2139\ufe0f"
)

# ----- Sidebar -----
with st.sidebar:
    st.header("Data and monitoring settings")
    mode = st.radio("Source", ("NASA FIRMS (online)", "Upload FIRMS CSV"))
    days = 3
    sensors = []
    api_key = ""
    files = None
    if mode == "NASA FIRMS (online)":
        api_key = get_map_key()
        if not api_key:
            api_key = st.text_input("NASA FIRMS MAP_KEY", type="password", help="Not stored in source code.")
        sensors = st.multiselect(
            "VIIRS sources", options=list(SENSORS.keys()),
            default=list(SENSORS.keys()),
        )
        days = st.slider("Most recent days (max. 5 per request)", 1, 5, 3)
        st.caption("Use the NASA Area API. Times in data are UTC.")
    else:
        files = st.file_uploader(
            "FIRMS CSV files", type=["csv"], accept_multiple_files=True,
            help="A file requires latitude, longitude, acq_date, and acq_time columns.",
        )
    keep_confidence = st.multiselect(
        "Confidence classes",
        options=["High", "Nominal", "Low", "Unknown"],
        default=["High", "Nominal"],
        help="Class names are from NASA VIIRS product classifications.",
    )
    point_limit = st.slider("Max. displayed points on map", 3000, 30000, 12000, 1000)
    if st.button("Reload online data / boundaries", use_container_width=True):
        cached_firms_data.clear()
        cached_boundary.clear()
        map_province_boundaries.clear()
        st.rerun()
    st.divider()
    st.caption("Country bbox: 94,-12,142,7; statistics are polygon-clipped to Indonesia.")

if mode == "NASA FIRMS (online)" and not api_key:
    st.warning("Add a NASA FIRMS MAP_KEY in Streamlit Secrets, or enter it in the sidebar.")
    st.code('FIRMS_MAP_KEY = "YOUR_MAP_KEY"', language="toml")
    st.markdown("Free key: https://firms.modaps.eosdis.nasa.gov/api/map_key/")
    st.stop()
if mode == "NASA FIRMS (online)" and not sensors:
    st.warning("Select at least one VIIRS source.")
    st.stop()
if mode == "Upload FIRMS CSV" and not files:
    st.info("Upload one or more standard NASA FIRMS CSV files to proceed.")
    st.stop()
if not keep_confidence:
    st.warning("Select at least one confidence class.")
    st.stop()

# ----- Data loading -----
try:
    with st.spinner("Loading FIRMS detections and Indonesian boundaries..."):
        parts = []
        if mode == "NASA FIRMS (online)":
            for sensor_name in sensors:
                parts.append(cached_firms_data(api_key, SENSORS[sensor_name], days))
        else:
            for uploaded in files:
                try:
                    raw = uploaded.getvalue().decode("utf-8-sig")
                except UnicodeDecodeError:
                    raw = uploaded.getvalue().decode("latin-1")
                parts.append(parse_firms_csv(raw, source=uploaded.name))
        raw_data = pd.concat(parts, ignore_index=True).drop_duplicates()
        country_geojson, country_meta = cached_boundary("ADM0")
        province_geojson, province_meta = cached_boundary("ADM1")
        national = assign_country_and_province(raw_data, country_geojson, province_geojson)
except (DataSourceError, ValueError, OSError) as exc:
    st.error(str(exc))
    st.caption("No observations or national statistics are shown when data validation fails.")
    st.stop()

if national.empty:
    st.warning("No valid detections lie inside the Indonesian boundary for the selected data.")
    st.stop()

# ----- Filters -----
all_provinces = sorted(national["province"].dropna().unique().tolist())
with st.sidebar:
    province_choice = st.selectbox("Province", ["All Indonesia"] + all_provinces)

selected = national[national["confidence_class"].isin(keep_confidence)].copy()
if province_choice != "All Indonesia":
    selected = selected[selected["province"] == province_choice].copy()

st.caption(
    f"Source detections: {len(raw_data):,} | Inside national boundary: {len(national):,} | "
    f"After current filters: {len(selected):,}"
)
if selected.empty:
    st.warning("No detections match the selected province/confidence filters.")
    st.stop()

# ----- Metrics -----
col1, col2, col3, col4 = st.columns(4)
col1.metric("Detections (filtered)", f"{len(selected):,}")
col2.metric("High confidence", f"{(selected['confidence_class'] == 'High').sum():,}")
col3.metric(
    "Provinces with detections",
    f"{selected.loc[selected['province'] != 'Province not identified', 'province'].nunique():,}",
)
col4.metric("Observation dates (UTC)", f"{selected['acq_date'].nunique():,}")

try:
    map_boundaries = map_province_boundaries(province_geojson)
    st.subheader("Map of satellite-detected thermal anomalies")
    show_map(selected, map_boundaries, point_limit)
except (ValueError, RuntimeError) as exc:
    st.warning(f"Map could not be drawn: {exc}")

left, right = st.columns([1.1, 1])
with left:
    st.subheader("Daily detections (UTC)")
    counts = (
        selected.groupby("acq_date", as_index=False)
        .size().rename(columns={"size": "detections"})
        .sort_values("acq_date")
    )
    fig = px.bar(counts, x="acq_date", y="detections",
                 labels={"acq_date": "UTC date", "detections": "Number of detections"})
    fig.update_layout(margin=dict(l=8, r=8, t=12, b=8))
    st.plotly_chart(fig, use_container_width=True)
with right:
    st.subheader("Provinces with most detections")
    by_province = (
        selected.groupby("province", as_index=False)
        .size().rename(columns={"size": "detections"})
        .sort_values("detections", ascending=False).head(12)
    )
    fig = px.bar(
        by_province.sort_values("detections"), x="detections", y="province",
        orientation="h", labels={"province": "Province", "detections": "Detections"},
    )
    fig.update_layout(margin=dict(l=8, r=8, t=12, b=8))
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Data table and reproducible exports")
cols = [
    "acq_date", "acq_time", "latitude", "longitude", "province",
    "confidence_class", "frp", "source", "satellite",
]
st.dataframe(selected[cols].reset_index(drop=True), use_container_width=True, hide_index=True)
export = selected.drop(columns=["acq_datetime_utc"], errors="ignore")
csv_data = export.to_csv(index=False).encode("utf-8-sig")
x, y = st.columns(2)
with x:
    st.download_button(
        "Download all filtered detections (CSV)", data=csv_data,
        file_name="indonesia_fire_watch_detections.csv", mime="text/csv",
        use_container_width=True,
    )
with y:
    if len(selected) <= 60000:
        st.download_button(
            "Download all filtered detections (GeoJSON)",
            data=geojson_download(selected),
            file_name="indonesia_fire_watch_detections.geojson",
            mime="application/geo+json", use_container_width=True,
        )
    else:
        st.caption("GeoJSON export is disabled for >60,000 points; use full CSV instead.")

with st.expander("Scientific notes, quality checks, and provenance"):
    st.write(
        "**National clipping:** detections are intersected with the full-resolution "
        "ADM0 polygon from geoBoundaries. ADM1 is used to assign province labels."
    )
    st.write(
        "**Spatial uncertainty:** coastal and administrative boundaries can be "
        "outdated or inaccurate. Review the boundary source/year before research publication."
    )
    st.write(
        "**Interpretation:** number of detections is not the number of independent "
        "fires, FRP is an instantaneous radiative power observation, and hotspots "
        "do not directly measure burned-area extent."
    )
    st.json({
        "country_boundary": country_meta,
        "province_boundary": province_meta,
        "source_rows": int(len(raw_data)),
        "inside_indonesia": int(len(national)),
        "outside_indonesia_bbox_or_boundary": int(len(raw_data) - len(national)),
        "after_selected_filters": int(len(selected)),
        "data_source": mode,
        "sources_selected": [SENSORS[s] for s in sensors] if sensors else [f.name for f in files],
    })
    st.markdown(
        "Sources: [NASA FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) "
        "| [geoBoundaries](https://www.geoboundaries.org/) (attribution required)."
    )

st.caption("Indonesia Fire Watch | Prototype v1.0 | Observation-based, not an official fire alert service")
