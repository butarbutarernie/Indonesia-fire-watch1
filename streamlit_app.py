"""Indonesia Fire Watch 2.1 | automatic NAMOBJ village identification.

Only selected administrative polygons are loaded. Village boundaries are not
inferred from nearest places; unknowns stay explicitly unidentified.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import escape
import json
import math
import os
import hashlib

import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

from admin_core import (
    AdminDataError, annotate_village_polygons, fetch_admin_list,
    fetch_admin_polygon, filter_points_in_polygon, geojson_region,
)
from village_upload import (
    VillageUploadError, load_named_villages, annotate_named_villages,
)
from national_namobj import (
    NationalNamobjError, MATCH_STATUS, annotate_namobj_points, NamobjGeoParquetStore,
)
from firewatch_core import (
    DataSourceError, SENSORS, assign_country_and_province, fetch_boundary,
    fetch_recent_firms, geojson_to_gdf, parse_firms_csv,
)

st.set_page_config(
    page_title="Indonesia Fire Watch v2.1 | National NAMOBJ",
    page_icon="🔥", layout="wide", initial_sidebar_state="expanded",
)

# Presentation only: no alerts or risk declarations based on unverified detections.
st.markdown('''
<style>
  .block-container{max-width:1600px;padding-top:1.35rem;padding-bottom:3rem}
  [data-testid="stSidebar"]{background:#f1f6f7;border-right:1px solid #dfe9ea}
  [data-testid="stSidebar"] .stMarkdown p{font-size:.89rem}
  h1,h2,h3{letter-spacing:-.02em}
  .ifw-banner{background:linear-gradient(117deg,#102c3f 0%,#164456 54%,#0d716e 100%);
      border-radius:18px;padding:27px 32px 25px;box-shadow:0 14px 28px rgba(9,47,62,.13);
      color:white;margin-bottom:14px}
  .ifw-banner .tag{color:#a0e1cf;letter-spacing:.17em;font-size:.72rem;font-weight:750}
  .ifw-banner .heading{color:white;font-size:clamp(1.62rem,3.2vw,2.5rem);
      font-weight:820;margin:8px 0 8px;line-height:1.18}
  .ifw-banner .desc{color:#dcecf0;font-size:.92rem;max-width:1050px;line-height:1.65}
  .ifw-stat{background:linear-gradient(160deg,#fff,#f5f8f9);border:1px solid #e2e9ec;
      border-radius:14px;padding:17px 20px;min-height:113px;box-shadow:0 2px 4px rgba(13,48,62,.03)}
  .ifw-stat .label{font-size:.76rem;color:#577481;font-weight:700;letter-spacing:.03em}
  .ifw-stat .num{font-size:clamp(1.45rem,2.6vw,2.05rem);font-weight:820;
      line-height:1.2;color:#14384e;padding-top:11px}
  .ifw-stat .note{font-size:.7rem;color:#77919e;padding-top:7px}
  .ifw-caption{font-size:.79rem;color:#557080;line-height:1.6}
  .ifw-rule{background:#f0f6f7;border-left:4px solid #2f928b;padding:12px 16px;
      border-radius:10px;font-size:.84rem;line-height:1.6;color:#264d5d;margin:10px 0}
  .ifw-kpi{display:flex;gap:9px;align-items:center;color:#476d7a;font-size:.79rem;
      padding:8px 0 3px;flex-wrap:wrap}
  .ifw-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#56c4a9}
  [data-testid="stTabs"] button[role="tab"]{font-weight:700}
  @media(max-width:700px){.ifw-banner{padding:19px}.ifw-stat{min-height:96px;padding:13px}}
</style>
''', unsafe_allow_html=True)


@st.cache_data(ttl=600, show_spinner=False)
def cached_firms(map_key: str, sensor: str, days: int, utc_day: str):
    return fetch_recent_firms(map_key, sensor, days, today_utc=utc_day)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def cached_boundaries(level: str):
    return fetch_boundary(level)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def cached_admin_list(level: str, code: str = ""):
    return fetch_admin_list(level, code or None)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def cached_admin_polygon(code: str):
    return fetch_admin_polygon(code)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def cached_village_layer(district_code: str):
    """Optional bounded per-kecamatan fetch, cached for reuse."""
    villages, stamp = fetch_admin_list("villages", district_code)
    if len(villages) > 50:
        return [], 0, len(villages), stamp, "limit"
    result = []
    failed = 0
    requested = [x for x in villages if x["has_path"]]
    failed = len(villages) - len(requested)

    def worker(row):
        geom, _ = fetch_admin_polygon(row["id"])
        return {**row, "geometry": geom}

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(worker, row): row for row in requested}
        for future in as_completed(futures):
            try:
                result.append(future.result())
            except AdminDataError:
                failed += 1
    return result, failed, len(villages), stamp, "ok"


@st.cache_data(ttl=15 * 60, max_entries=3, show_spinner=False)
def cached_national_namobj(detections: pd.DataFrame, release_url: str):
    store = NamobjGeoParquetStore(release_url=release_url)
    return annotate_namobj_points(detections, store)


def get_national_release_url() -> str:
    try:
        value = str(st.secrets.get("IFW_NAMOBJ_RELEASE_URL", "")).strip()
    except Exception:
        value = ""
    return value or os.environ.get("IFW_NAMOBJ_RELEASE_URL", "").strip()


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def simplified_admin1(geojson: dict):
    gdf = geojson_to_gdf(geojson)
    drawing = gdf[["geometry"]].copy()
    # This simplification applies ONLY to the displayed lines, never clipping.
    drawing["geometry"] = drawing.geometry.simplify(0.02, preserve_topology=True)
    return json.loads(drawing.to_json())


def get_firms_key() -> str:
    try:
        key = str(st.secrets.get("FIRMS_MAP_KEY", "")).strip()
    except Exception:
        key = ""
    return key or os.environ.get("FIRMS_MAP_KEY", "").strip()


def region_select(label: str, rows: list[dict], empty_label: str, key: str) -> dict | None:
    ref = {r["id"]: r for r in rows}
    picked = st.selectbox(
        label, [""] + [r["id"] for r in rows],
        format_func=lambda item: ref[item]["name"] if item else empty_label,
        key=key,
    )
    return ref.get(picked)


def view_state_for_polygon(geometry):
    if geometry is None:
        return pdk.ViewState(latitude=-2.6, longitude=118.1, zoom=3.7, pitch=0)
    x1, y1, x2, y2 = geometry.bounds
    center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
    span = max(x2 - x1, (y2 - y1) * 1.8, 0.015)
    zoom = max(3.7, min(13.1, math.log2(200 / span)))
    return pdk.ViewState(latitude=center_y, longitude=center_x, zoom=zoom, pitch=0)


def display_map(df: pd.DataFrame, adm1: dict, geometry, name: str,
                code: str, point_limit: int, kind: str):
    """Full statistics; map may display deterministic sample for responsiveness."""
    layer_data = df.copy()
    was_sampled = len(layer_data) > point_limit
    if was_sampled:
        layer_data = layer_data.sample(n=point_limit, random_state=2026)
    colors = {
        "High": [220, 50, 46, 225], "Nominal": [252, 129, 44, 208],
        "Low": [248, 198, 58, 210], "Unknown": [105, 132, 161, 190],
    }
    layer_data = layer_data[[
        "latitude", "longitude", "acq_date", "acq_time", "province",
        "kabupaten_kota", "kecamatan", "desa", "confidence_class", "frp", "source",
    ]].copy()
    # Popup HTML must not interpret text from an uploaded attribute table as markup.
    for column in ["province", "kabupaten_kota", "kecamatan", "desa", "source"]:
        layer_data[column] = layer_data[column].fillna("").astype(str).map(escape)
    layer_data["rgba"] = layer_data["confidence_class"].map(
        lambda v: colors.get(v, colors["Unknown"])
    )
    layer_data["frp_label"] = layer_data["frp"].apply(
        lambda x: f"{x:.1f} MW" if pd.notna(x) else "Tidak tersedia"
    )
    layers = [
        pdk.Layer("GeoJsonLayer", data=adm1, stroked=True, filled=False,
                  get_line_color=[42, 91, 118, 100], line_width_min_pixels=0.6,
                  pickable=False),
    ]
    if geometry is not None:
        selection = geojson_region(geometry, name, code)
        layers.append(pdk.Layer(
            "GeoJsonLayer", data=selection, stroked=True, filled=True,
            get_fill_color=[29, 145, 143, 19], get_line_color=[8, 118, 127, 230],
            line_width_min_pixels=2, pickable=False,
        ))
    if kind == "Kepadatan (heatmap)":
        layers.append(pdk.Layer(
            "HeatmapLayer", data=layer_data,
            get_position="[longitude, latitude]", get_weight=1,
            radius_pixels=34, intensity=1, threshold=0.08,
        ))
    else:
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=layer_data,
            get_position="[longitude, latitude]", get_fill_color="rgba",
            get_radius=500, radius_min_pixels=2.3, radius_max_pixels=7,
            pickable=True, opacity=0.92,
        ))
    deck = pdk.Deck(
        layers=layers, initial_view_state=view_state_for_polygon(geometry),
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={
            "html": "<b>{province}</b><br/>Kab/Kota: {kabupaten_kota}"
                    "<br/>Kecamatan: {kecamatan}<br/>Desa: {desa}"
                    "<br/>UTC: {acq_date} {acq_time}"
                    "<br/>Confidence: {confidence_class}"
                    "<br/>FRP: {frp_label}<br/>Sensor: {source}",
            "style": {"color": "white", "backgroundColor": "#183448", "fontSize": "12px"},
        },
    )
    st.pydeck_chart(deck, use_container_width=True, height=595)
    if was_sampled:
        st.caption(
            f"Peta menampilkan sampel acak yang dapat direproduksi: **{point_limit:,}** "
            f"dari **{len(df):,}** rekaman. Statistik dan ekspor mencakup seluruh hasil filter."
        )
    else:
        st.caption(f"Peta menampilkan semua **{len(df):,}** rekaman hasil filter.")


def geojson_download(df: pd.DataFrame) -> str:
    keep_cols = ["acq_date", "acq_time", "province", "kabupaten_kota", "kecamatan",
                 "desa", "kode_desa", "desa_status", "source", "confidence_class", "frp"]
    features = []
    for row in df[["latitude", "longitude"] + keep_cols].itertuples(index=False, name=None):
        lat, lon, *rest = row
        props = {}
        for col, value in zip(keep_cols, rest):
            if pd.isna(value):
                props[col] = None
            elif isinstance(value, (int, float, str, bool)):
                props[col] = value
            else:
                props[col] = str(value)
        features.append({"type": "Feature", "geometry": {
            "type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": props})
    return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False)


def metric(label, value, note=""):
    st.markdown(
        f'<div class="ifw-stat"><div class="label">{label}</div>'
        f'<div class="num">{value}</div><div class="note">{note}</div></div>',
        unsafe_allow_html=True,
    )


st.markdown('''
<div class="ifw-banner">
 <div class="tag">REMOTE SENSING · MONITORING NASIONAL · V2.1</div>
 <div class="heading">🔥 Indonesia Fire Watch</div>
 <div class="desc">Pemantauan anomali termal satelit NASA FIRMS di seluruh Indonesia. Jelajahi
  tingkat provinsi, kabupaten/kota, kecamatan, hingga desa dengan analisis berbasis batas wilayah.
  Untuk riset dan kewaspadaan situasional, bukan verifikasi kejadian kebakaran.</div>
</div>
''', unsafe_allow_html=True)

utc_day = datetime.now(timezone.utc).date().isoformat()
mode = "NASA FIRMS (online)"
with st.sidebar:
    st.markdown("### 🔭 Monitoring satelit")
    mode = st.radio("Sumber data", ["NASA FIRMS (online)", "Unggah CSV FIRMS"], horizontal=False)
    key = get_firms_key() if mode == "NASA FIRMS (online)" else ""
    sources = []
    window = 3
    uploads = None
    if mode == "NASA FIRMS (online)":
        if not key:
            key = st.text_input("FIRMS MAP_KEY", type="password", help="Kunci tidak ditulis dalam kode.")
        sources = st.multiselect("Satelit VIIRS", list(SENSORS), default=list(SENSORS))
        window = st.select_slider("Periode pengamatan (tanggal UTC)", options=[1, 2, 3, 5, 7], value=3)
        st.caption("Periode 7 hari memakai dua permintaan API per sensor (5+2 hari).")
    else:
        uploads = st.file_uploader("Unggah CSV FIRMS", type="csv", accept_multiple_files=True)
    confidence = st.multiselect("Kelas confidence", ["High", "Nominal", "Low", "Unknown"],
                                default=["High", "Nominal"])
    point_limit = st.slider("Maksimum titik di peta", 3000, 30000, 12000, 1000)
    if st.button("↻ Perbarui data & batas", use_container_width=True):
        cached_firms.clear()
        cached_boundaries.clear()
        cached_admin_list.clear()
        cached_admin_polygon.clear()
        cached_village_layer.clear()
        simplified_admin1.clear()
        st.rerun()
    st.divider()
    st.markdown("### 📍 Penelusuran wilayah")
    st.caption("Pilih wilayah bertahap. Hanya poligon pilihan yang diunduh.")

    regions = {}
    admin_stamps = []
    province_rows = []
    try:
        province_rows, stamp = cached_admin_list("provinces")
        admin_stamps.append(stamp)
    except AdminDataError:
        st.warning("Layanan administrasi desa sedang tidak tersedia. Peta nasional tetap dapat digunakan.")
    regions["province"] = region_select("Provinsi", province_rows, "Seluruh Indonesia", "ifw_prov") if province_rows else None
    regions["regency"] = None
    regions["district"] = None
    regions["village"] = None
    if regions["province"]:
        try:
            rows, stamp = cached_admin_list("regencies", regions["province"]["id"])
            admin_stamps.append(stamp)
            regions["regency"] = region_select("Kabupaten/Kota", rows, "Semua kabupaten/kota", f"ifw_reg_{regions['province']['id']}")
        except AdminDataError:
            st.warning("Daftar kabupaten/kota gagal dimuat. Pilihan provinsi tetap aktif.")
    if regions["regency"]:
        try:
            rows, stamp = cached_admin_list("districts", regions["regency"]["id"])
            admin_stamps.append(stamp)
            regions["district"] = region_select("Kecamatan", rows, "Semua kecamatan", f"ifw_dist_{regions['regency']['id']}")
        except AdminDataError:
            st.warning("Daftar kecamatan gagal dimuat; wilayah kabupaten/kota tetap aktif.")
    if regions["district"]:
        try:
            rows, stamp = cached_admin_list("villages", regions["district"]["id"])
            admin_stamps.append(stamp)
            regions["village"] = region_select("Desa / Kelurahan", rows, "Semua desa/kelurahan", f"ifw_vill_{regions['district']['id']}")
        except AdminDataError:
            st.warning("Daftar desa gagal dimuat; wilayah kecamatan tetap aktif.")
    do_village_inventory = False
    if regions["district"] and not regions["village"]:
        do_village_inventory = st.checkbox(
            "Identifikasi seluruh desa pada kecamatan", value=False,
            help="Mengunduh poligon desa pada kecamatan terpilih (maksimum 50 desa)."
        )
    st.divider()
    national_url = get_national_release_url()
    if national_url:
        st.success("Sumber NAMOBJ nasional otomatis telah dikonfigurasi.")
    else:
        st.info("NAMOBJ nasional otomatis belum dihubungkan. Data FIRMS tetap berjalan; tambahkan IFW_NAMOBJ_RELEASE_URL di Secrets setelah aset siap.")
    st.markdown("### 🗂️ Batas desa dari shapefile Anda")
    village_file = st.file_uploader(
        "Unggah ZIP Shapefile atau GeoJSON desa (NAMOBJ)",
        type=["zip", "geojson", "json"],
        help="ZIP memuat satu set .shp, .shx, .dbf, .prj (dan .cpg bila ada); nama desa di NAMOBJ.",
        key="ifw_uploaded_namobj_file",
    )
    st.caption("Opsional; hanya data yang Anda unggah akan dicocokkan. Nama desa diambil "
               "dari NAMOBJ menggunakan titik-di-dalam-poligon, bukan tebakan lokasi terdekat. "
               "Sebaiknya unggah satu kabupaten/kecamatan agar ringan.")
    st.divider()
    st.caption("Batas geoBoundaries (ADM0–ADM1) dan Emsifa v2 (detail administratif). "
               "Poligon Emsifa disederhanakan, bukan referensi batas definitif BIG.")

# Uploaded polygons are cached in the visitor session only, not shared between users.
village_layer = None
village_meta = None
if village_file is not None:
    try:
        file_bytes = village_file.getvalue()
        digest = hashlib.sha256(file_bytes).hexdigest()
        existing = st.session_state.get("_ifw_namobj_upload")
        if not existing or existing["hash"] != digest or existing["filename"] != village_file.name:
            with st.spinner("Membaca shapefile/GeoJSON dan memeriksa NAMOBJ serta proyeksi ..."):
                layer_loaded, meta_loaded = load_named_villages(file_bytes, village_file.name)
            existing = {"hash": digest, "filename": village_file.name,
                        "layer": layer_loaded, "meta": meta_loaded}
            st.session_state["_ifw_namobj_upload"] = existing
        village_layer = existing["layer"]
        village_meta = existing["meta"]
        with st.sidebar:
            st.success(f"Batas NAMOBJ terbaca: {village_meta['features']:,} poligon. "
                       f"CRS sumber: {village_meta['source_crs']}.")
    except VillageUploadError as exc:
        st.warning(f"Layer desa unggahan tidak digunakan: {exc}")
        st.session_state.pop("_ifw_namobj_upload", None)
else:
    st.session_state.pop("_ifw_namobj_upload", None)

if mode == "NASA FIRMS (online)" and not key:
    st.warning("Tambahkan `FIRMS_MAP_KEY` pada Streamlit Cloud → App settings → Secrets.")
    st.stop()
if mode == "NASA FIRMS (online)" and not sources:
    st.warning("Pilih setidaknya satu sensor.")
    st.stop()
if mode != "NASA FIRMS (online)" and not uploads:
    st.info("Unggah setidaknya satu file CSV NASA FIRMS untuk melanjutkan.")
    st.stop()
if not confidence:
    st.warning("Pilih sedikitnya satu kelas confidence.")
    st.stop()

parts = []
failed_sensors = []
with st.spinner("Memuat observasi FIRMS dan menguji batas negara Indonesia ..."):
    if mode == "NASA FIRMS (online)":
        for label in sources:
            try:
                parts.append(cached_firms(key, SENSORS[label], window, utc_day))
            except (DataSourceError, ValueError):
                failed_sensors.append(label)
    else:
        for uploaded in uploads:
            try:
                try:
                    raw = uploaded.getvalue().decode("utf-8-sig")
                except UnicodeDecodeError:
                    raw = uploaded.getvalue().decode("latin-1")
                parts.append(parse_firms_csv(raw, uploaded.name))
            except (DataSourceError, ValueError) as exc:
                st.error(f"Berkas '{uploaded.name}' tidak dapat dibaca: {exc}")
    if not parts:
        st.error("Tidak ada sumber FIRMS yang berhasil dimuat. Periksa API key atau format CSV.")
        st.stop()
    raw_data = pd.concat(parts, ignore_index=True).drop_duplicates().reset_index(drop=True)
    try:
        country_geojson, country_meta = cached_boundaries("ADM0")
        province_geojson, province_meta = cached_boundaries("ADM1")
        national = assign_country_and_province(raw_data, country_geojson, province_geojson)
    except (DataSourceError, ValueError, OSError) as exc:
        st.error(f"Gagal memuat batas negara/provinsi. Perhitungan dibatalkan: {exc}")
        st.stop()

if failed_sensors:
    st.warning("Sebagian sensor gagal dimuat: " + ", ".join(failed_sensors)
               + ". Statistik hanya berdasarkan sensor yang berhasil diambil.")

selected = national.loc[national.confidence_class.isin(confidence)].copy()
selected["kabupaten_kota"] = "Belum dipilih"
selected["kecamatan"] = "Belum dipilih"
selected["desa"] = "Belum diidentifikasi"
selected["kode_desa"] = ""
selected["desa_status"] = "Belum dianalisis"
geometry = None
area_name = "Seluruh Indonesia"
area_code = "IDN"
selected_record = None
for level in ("province", "regency", "district", "village"):
    record = regions[level]
    if not record:
        continue
    selected_record = record
    if not record.get("has_path", False):
        st.error(f"Poligon {record['name']} tidak tersedia. Pilih wilayah lain; "
                 "statistik nasional tidak disajikan sebagai statistik wilayah tersebut.")
        st.stop()
    try:
        geometry, _ = cached_admin_polygon(record["id"])
    except AdminDataError as exc:
        st.error(str(exc))
        st.stop()
    selected = filter_points_in_polygon(selected, geometry)
    area_name = record["name"]
    area_code = record["id"]
    if level == "regency":
        selected["kabupaten_kota"] = area_name
    elif level == "district":
        selected["kecamatan"] = area_name
    elif level == "village":
        selected["desa"] = area_name
        selected["kode_desa"] = area_code
        selected["desa_status"] = "Cocok dengan poligon desa pilihan"

village_result = None
if do_village_inventory and village_layer is None and regions["district"] and not regions["village"]:
    with st.spinner("Mencocokkan poligon desa pada kecamatan pilihan ..."):
        try:
            villages, not_available, total_villages, _, status = cached_village_layer(
                regions["district"]["id"]
            )
            if status == "limit":
                st.warning(f"Kecamatan ini memiliki {total_villages} desa. Untuk membatasi "
                           "akses API, pilih satu desa dari dropdown; analisis massal dinonaktifkan (>50).")
            elif villages:
                selected, village_result = annotate_village_polygons(selected, villages)
                village_result.update({"failed_polygons": not_available,
                                       "total_villages": total_villages})
            else:
                st.warning("Belum ada poligon desa yang dapat diperiksa untuk kecamatan ini.")
        except AdminDataError:
            st.warning("Referensi batas desa sedang gagal dimuat. Nama desa dibiarkan tidak teridentifikasi.")

# National dataset uses the existing 28 Cell-5 GeoParquet shards and only NAMOBJ
# for village labels. Uploads, if provided, remain an optional override.
national_result = None
if national_url and not selected.empty:
    try:
        with st.spinner("Mengidentifikasi desa otomatis dari NAMOBJ nasional ..."):
            selected, national_result = cached_national_namobj(selected, national_url)
        with st.sidebar:
            st.caption(
                f"NAMOBJ nasional: {national_result['matched']:,} titik cocok, "
                f"{national_result['ambiguous']:,} ambigu, "
                f"{national_result['unmatched']:,} belum teridentifikasi."
            )
    except (NationalNamobjError, OSError, ValueError, KeyError) as exc:
        st.warning(
            "Basis NAMOBJ nasional belum dapat dibaca. Peta NASA tetap berjalan; "
            f"periksa Release assets dan IFW_NAMOBJ_RELEASE_URL. Detail: {exc}"
        )

# User-supplied NAMOBJ polygon lookup takes precedence over the optional online
# village inventory. The selection is polygon-specific even if NAMOBJ repeats.
# NOTE: Loading a partial layer does not label hotspots outside that layer.
upload_result = None
uploaded_village_choice = None
if village_layer is not None:
    if geometry is not None:
        candidates = village_layer.loc[village_layer.intersects(geometry)].copy()
    else:
        candidates = village_layer.copy()
    if not candidates.empty:
        with st.sidebar:
            st.markdown("#### Desa/kelurahan dari NAMOBJ")
            query = st.text_input("Cari nama desa pada file", placeholder="Contoh: Sukamaju",
                                  key="ifw_search_namobj").strip()
            names = candidates
            if query:
                names = names.loc[names.namobj.str.contains(query, case=False, regex=False, na=False)]
            if len(names) > 400:
                st.caption(f"{len(names):,} poligon cocok. Ketik nama desa agar daftar lebih ringkas. "
                           "Daftar ditampilkan maksimum 400 opsi.")
            preview = names.head(400)
            option_rows = {int(row.feature_id): row for row in preview.itertuples(index=False)}
            chosen_id = st.selectbox(
                "Filter berdasarkan poligon NAMOBJ (opsional)",
                [None] + list(option_rows),
                format_func=lambda x: "Semua desa pada file" if x is None else (
                    f"{option_rows[x].namobj or '[NAMOBJ kosong]'}"
                    + (f" · {option_rows[x].kode_sumber}" if option_rows[x].kode_sumber else "")
                    + f" · feature {x}"
                ), key="ifw_pick_namobj_feature",
            )
        if chosen_id is not None:
            row = option_rows[chosen_id]
            uploaded_village_choice = row.namobj
            uploaded_geometry = candidates.loc[candidates.feature_id.eq(chosen_id), "geometry"].iloc[0]
            selected = filter_points_in_polygon(selected, uploaded_geometry)
            geometry = uploaded_geometry
            area_name = row.namobj or "Nama desa kosong"
            area_code = str(row.kode_sumber) if row.kode_sumber else f"FILE-FEATURE-{chosen_id}"
        selected, upload_result = annotate_named_villages(selected, candidates)
        # Upload has explicit preference over Emsifa because the user supplied NAMOBJ.
        village_result = None
    else:
        st.warning("Tidak ada poligon batas desa unggahan yang beririsan "
                   "dengan wilayah administrasi pilihan. Nama desa tidak dipaksakan.")

latest = selected.acq_datetime_utc.max() if not selected.empty else pd.NaT
latest_label = latest.strftime("%d %b %Y, %H:%M UTC") if pd.notna(latest) else "Tidak ada deteksi"

st.markdown(
    f'<div class="ifw-kpi"><span class="ifw-dot"></span> Data: {escape(mode)}'
    f' &nbsp;·&nbsp; Wilayah: <b>{escape(area_name)}</b>'
    f' &nbsp;·&nbsp; Akuisisi terakhir: <b>{latest_label}</b></div>',
    unsafe_allow_html=True,
)
st.caption(
    f"Sumber: **{len(raw_data):,}** deteksi · Dalam batas Indonesia: **{len(national):,}** · "
    f"Setelah confidence dan filter wilayah: **{len(selected):,}**. "
    "Jumlah adalah rekaman pengamatan, bukan kejadian kebakaran unik."
)

metric_cols = st.columns(4)
with metric_cols[0]:
    metric("Deteksi terfilter", f"{len(selected):,}", "Gabungan sensor & kelas terpilih")
with metric_cols[1]:
    metric("High confidence", f"{int(selected.confidence_class.eq('High').sum()):,}",
           "Bukan probabilitas kebakaran")
with metric_cols[2]:
    metric("Provinsi terdeteksi", f"{selected.province.loc[selected.province != 'Province not identified'].nunique():,}",
           "Dalam wilayah/filter aktif")
with metric_cols[3]:
    metric("Tanggal UTC", f"{selected.acq_date.nunique():,}", "Hari kalender dengan deteksi")

st.write("")
tab_map, tab_stats, tab_data, tab_notes = st.tabs([
    "🗺️ Peta pemantauan", "📊 Analisis wilayah", "📋 Data & unduh", "🔬 Metode & kualitas",
])
with tab_map:
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader(f"Sebaran anomali termal · {area_name}")
    with c2:
        view_type = st.selectbox("Visualisasi", ["Titik per confidence", "Kepadatan (heatmap)"],
                                 label_visibility="collapsed")
    try:
        display_map(selected, simplified_admin1(province_geojson), geometry,
                    area_name, area_code, point_limit, view_type)
    except Exception:
        st.error("Peta gagal dirender. Periksa log Streamlit atau coba kurangi titik tampilan.")
    st.markdown('''<div class="ifw-rule"><b>Legenda:</b>
       🔴 High &nbsp; 🟠 Nominal &nbsp; 🟡 Low &nbsp; 🔵 Unknown.
       Setiap titik merepresentasikan deteksi pada piksel sensor. Koordinat bukan batas area terbakar,
       dan satu kebakaran dapat teramati berkali-kali.</div>''', unsafe_allow_html=True)
    if uploaded_village_choice is not None:
        st.info(f"Filter desa dari NAMOBJ aktif: **{uploaded_village_choice}**. "
                "Nama diperoleh dari poligon shapefile/GeoJSON yang diunggah.")
    elif village_layer is not None:
        st.caption("Layer desa NAMOBJ telah digunakan untuk mencocokkan lokasi hotspot. "
                   "Nama di luar cakupan poligon ditandai belum teridentifikasi.")
    elif national_result is not None:
        st.caption("Nama desa diisi otomatis dari atribut NAMOBJ pada poligon desa nasional. "
                   "Hotspot tanpa kecocokan atau dengan kecocokan ganda diberi status eksplisit.")
    elif regions["village"]:
        st.info(f"Filter desa aktif: **{regions['village']['name']}** (kode {area_code}). "
                "Titik dicocokkan ke batas poligon desa yang tersedia, bukan lokasi pusat desa.")
    elif regions["district"]:
        st.caption("Pilih desa pada sidebar agar hasil hanya mencakup satu desa. "
                   "Centang 'Identifikasi seluruh desa' untuk rincian desa dalam kecamatan (maks. 50 desa).")

with tab_stats:
    a, b = st.columns([1.2, 1])
    if not selected.empty:
        daily = (selected.groupby("acq_date").size().reset_index(name="Deteksi")
                 .sort_values("acq_date"))
        by_conf = selected.groupby("confidence_class").size().reset_index(name="Deteksi")
        with a:
            st.markdown("#### Deteksi per tanggal pengamatan (UTC)")
            fig = px.bar(daily, x="acq_date", y="Deteksi", color_discrete_sequence=["#dd7849"])
            fig.update_layout(margin=dict(l=0, r=5, t=4, b=5),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              xaxis_title="Tanggal UTC", yaxis_title="Rekaman deteksi")
            st.plotly_chart(fig, use_container_width=True)
        with b:
            st.markdown("#### Kelas confidence")
            fig = px.pie(by_conf, names="confidence_class", values="Deteksi", hole=.61,
                         color="confidence_class", color_discrete_map={
                             "High":"#db4640", "Nominal":"#ef934e", "Low":"#f5c454", "Unknown":"#7a98af"})
            fig.update_layout(margin=dict(l=5, r=5, t=0, b=5), showlegend=True,
                              paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
        if ((village_result and village_result["matched"])
                or (upload_result and upload_result["matched"])
                or (national_result and national_result["matched"])):
            st.markdown("#### Desa dengan deteksi (berdasarkan poligon)")
            matched_desa = selected.desa_status.isin([
                "Cocok dengan poligon desa", "Cocok dengan poligon desa (NAMOBJ)",
                MATCH_STATUS,
            ])
            rank_source = selected.loc[matched_desa].copy()
            # Same NAMOBJ can exist in distinct districts. Keep its context
            # when aggregating, without relying on KDEPUM as an identifier.
            rank_source["desa_label"] = (
                rank_source["desa"].astype(str) + " | "
                + rank_source["kecamatan"].astype(str) + " | "
                + rank_source["kabupaten_kota"].astype(str)
            )
            rank = (rank_source.groupby("desa_label").size()
                    .reset_index(name="Deteksi")
                    .sort_values("Deteksi", ascending=False).head(15))
            title_label = "desa_label"
        else:
            st.markdown("#### Provinsi dengan deteksi terbanyak")
            rank = (selected.groupby("province").size().reset_index(name="Deteksi")
                    .sort_values("Deteksi", ascending=False).head(15))
            title_label = "province"
        fig = px.bar(rank.sort_values("Deteksi"), x="Deteksi", y=title_label,
                     orientation="h", color_discrete_sequence=["#187c86"])
        fig.update_layout(margin=dict(l=0, r=10, t=4, b=8), height=440,
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          yaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)
        if upload_result:
            st.info(
                f"NAMOBJ: **{upload_result['matched']:,}** hotspot cocok dengan satu "
                f"poligon bernama; **{upload_result['unmatched']:,}** tanpa nama/cakupan; "
                f"**{upload_result['ambiguous']:,}** ambigu akibat poligon bertumpang tindih; "
                f"**{upload_result['unnamed']:,}** poligon dengan NAMOBJ kosong."
            )
        elif village_result:
            st.info(
                f"Pencocokan desa: **{village_result['matched']:,}** titik valid; "
                f"**{village_result['unmatched']:,}** tidak teridentifikasi; "
                f"**{village_result['ambiguous']:,}** ambigu; "
                f"**{village_result['failed_polygons']}** dari "
                f"{village_result['total_villages']} poligon desa gagal/tidak tersedia."
            )
        elif national_result:
            st.info(
                f"NAMOBJ nasional: **{national_result['matched']:,}** hotspot cocok; "
                f"**{national_result['unmatched']:,}** tidak teridentifikasi; "
                f"**{national_result['ambiguous']:,}** ambigu; "
                f"**{national_result['used_shards']:,}** shard GeoParquet dimuat."
            )
    else:
        st.info("Tidak ada deteksi pada filter yang dipilih. Ini bukan bukti bahwa wilayah bebas kebakaran.")
    st.caption("Perbandingan lintas sensor dan hari dipengaruhi lintasan satelit, awan, "
               "sudut pengamatan, dan keterlambatan pemrosesan. FRP bukan luas terbakar.")

with tab_data:
    st.subheader("Tabel deteksi dan ekspor")
    columns = ["acq_date", "acq_time", "latitude", "longitude", "province",
               "kabupaten_kota", "kecamatan", "desa", "kode_desa", "desa_status",
               "confidence_class", "frp", "source", "satellite"]
    st.dataframe(selected[columns], use_container_width=True, hide_index=True, height=385)
    left, right = st.columns(2)
    with left:
        st.download_button("⬇ Unduh seluruh data terfilter (CSV)",
                           data=selected[columns].to_csv(index=False).encode("utf-8-sig"),
                           file_name="IFW2_hotspot_terfilter.csv", mime="text/csv",
                           use_container_width=True)
    with right:
        if len(selected) <= 60000:
            st.download_button("⬇ Unduh seluruh data terfilter (GeoJSON)",
                               data=geojson_download(selected),
                               file_name="IFW2_hotspot_terfilter.geojson",
                               mime="application/geo+json", use_container_width=True)
        else:
            st.caption("Ekspor GeoJSON dinonaktifkan untuk >60.000 titik; gunakan CSV lengkap.")
    st.caption("Nama desa diambil dari NAMOBJ nasional, layer NAMOBJ unggahan, "
               "atau poligon pilihan saat tersedia. Titik tanpa kecocokan tidak ditebak.")

with tab_notes:
    st.markdown("#### Rantai data dan interpretasi")
    st.markdown('''
1. **Akuisisi:** NASA FIRMS Area API, VIIRS NOAA-20/NOAA-21 NRT; jendela 7 hari
   dipecah menjadi 2 + 5 tanggal UTC karena API membatasi satu permintaan maksimum 5 hari.
2. **Validasi spasial nasional:** titik wajib berada di poligon Indonesia dari
   **geoBoundaries ADM0**, bukan hanya kotak koordinat. **ADM1** untuk label provinsi.
3. **Filter administrasi rinci:** pilihan provinsi/kabupaten/kota/kecamatan/desa
   diambil secara bertahap dari **Emsifa Wilayah Indonesia v2**. Setiap pilihan
   dipotong dengan geometri poligon aktual dari API, bukan centroid atau radius.
   **NAMOBJ nasional:** bila URL GitHub Release dikonfigurasi, aplikasi membaca
   GeoParquet 83.489 poligon hasil Cell 5 secara lazy dan mengambil nama desa
   hanya dari `namobj` (asal `NAMOBJ`). KDEPUM tidak digunakan. Unggahan file
   kecil opsional sebagai override.
   Lookup pada data unggahan menggunakan spatial join; titik di batas/tumpang
   tindih dua poligon ditandai ambigu, nama kosong tidak ditebak.
4. **Keterbatasan administratif:** batas detail Emsifa sudah disederhanakan,
   mungkin tidak lengkap, bersifat indikatif, dan tidak diposisikan sebagai batas desa definitif BIG.
   Perbedaan versi dengan geoBoundaries bisa mengakibatkan selisih dekat batas.
5. **Perbandingan rekaman:** titik yang berdekatan lintas sensor/tanggal tetap
   dihitung sebagai rekaman terpisah; tidak ada rekayasa deduplikasi kejadian.
6. **Visualisasi:** sampel peta, bila diperlukan, dipilih dengan random seed tetap;
   total statistik dan ekspor menggunakan semua titik hasil filter.
''')
    st.markdown("#### Provenance sumber")
    st.write({
        "NASA FIRMS": "https://firms.modaps.eosdis.nasa.gov/api/area/",
        "geoBoundaries": "https://www.geoboundaries.org/",
        "Sumber batas nasional (ADM0)": country_meta,
        "Sumber provinsi (ADM1)": province_meta,
        "Emsifa v2": "https://www.emsifa.com/api-wilayah-indonesia/v2",
        "NAMOBJ nasional otomatis": national_url or "Belum dikonfigurasi",
        "Poligon desa unggahan (jika ada)": village_meta or "Tidak diunggah",
        "Timestamp administrasi (jika tersedia)": [x for x in admin_stamps if x],
        "UTC request date": utc_day,
    })
    st.warning("Titik termal bukan kejadian kebakaran terkonfirmasi. "
               "Confidence VIIRS adalah label kualitas deteksi, bukan peluang statistik "
               "bahwa sebuah desa mengalami kebakaran. Konfirmasi memerlukan sumber tambahan.")

st.caption("© Indonesia Fire Watch v2.1 · NASA FIRMS · geoBoundaries (gbOpen) · "
           "Emsifa Wilayah Indonesia v2 | Prototype penelitian — bukan sistem peringatan resmi.")
