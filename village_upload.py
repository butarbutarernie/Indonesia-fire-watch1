"""Optional user-provided village polygons with NAMOBJ label, never nearest-place lookup.

Supports WGS84 GeoJSON or ZIP shapefile with a declared .prj. All coordinate
matching is spatial; points on shared village boundaries are explicitly ambiguous.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path, PurePosixPath
import json
import tempfile
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

MAX_FILE_BYTES = 60 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 220 * 1024 * 1024
MAX_FEATURES = 12000
MAX_ZIP_FILES = 40
ZIP_SUFFIXES = {".shp", ".shx", ".dbf", ".prj", ".cpg"}
SOURCE_CODE_COLUMNS = (
    "KDEPUM", "KDE_PUM", "KODE_DESA", "KODE_WILAYAH", "VILLAGE_ID", "ID_DESA",
)


class VillageUploadError(ValueError):
    """Uploaded village boundary is incomplete, too large or untrustworthy."""


def _zip_shape_to_gdf(content: bytes) -> gpd.GeoDataFrame:
    try:
        zf = zipfile.ZipFile(BytesIO(content))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise VillageUploadError("ZIP tidak dapat dibaca.") from exc
    with zf:
        files = [i for i in zf.infolist() if not i.is_dir()]
        if len(files) > MAX_ZIP_FILES:
            raise VillageUploadError("ZIP berisi terlalu banyak file; unggah satu shapefile desa.")
        if sum(i.file_size for i in files) > MAX_UNCOMPRESSED_BYTES:
            raise VillageUploadError("Ukuran hasil ekstraksi ZIP terlalu besar.")
        if any(".." in PurePosixPath(i.filename.replace('\\', '/')).parts for i in files):
            raise VillageUploadError("ZIP memiliki jalur file yang tidak aman.")
        if any(PurePosixPath(i.filename).suffix.lower() not in ZIP_SUFFIXES for i in files):
            raise VillageUploadError("ZIP harus hanya berisi komponen shapefile (.shp/.shx/.dbf/.prj/.cpg).")
        shapes = [i for i in files if Path(i.filename).suffix.lower() == ".shp"]
        if len(shapes) != 1:
            raise VillageUploadError("ZIP harus berisi tepat satu file .shp, bukan beberapa layer.")
        stem = Path(shapes[0].filename).stem
        required = {".shp", ".shx", ".dbf", ".prj"}
        related = {Path(i.filename).suffix.lower(): i for i in files if Path(i.filename).stem.lower() == stem.lower()}
        if not required.issubset(related):
            raise VillageUploadError("Komponen shapefile harus mencakup .shp, .shx, .dbf, dan .prj (CRS).")
        with tempfile.TemporaryDirectory(prefix="ifw_namobj_") as td:
            folder = Path(td)
            for ext, item in related.items():
                target = folder / ("village" + ext)
                with zf.open(item, "r") as src, target.open("wb") as dest:
                    while True:
                        block = src.read(1024 * 1024)
                        if not block:
                            break
                        dest.write(block)
            try:
                return gpd.read_file(folder / "village.shp")
            except Exception as exc:
                raise VillageUploadError("Shapefile gagal dibaca; periksa atribut, format, dan file proyeksi.") from exc


def load_named_villages(content: bytes, filename: str) -> tuple[gpd.GeoDataFrame, dict]:
    """Read NAMOBJ polygons safely and convert geodata to EPSG:4326.

    A .shp alone is insufficient; the ZIP must include DBF/SHX/PRJ components.
    GeoJSON is WGS84 per RFC 7946. Missing CRS in shapefiles is rejected.
    """
    if not isinstance(content, bytes) or not content:
        raise VillageUploadError("File poligon desa masih kosong.")
    if len(content) > MAX_FILE_BYTES:
        raise VillageUploadError("File melebihi batas 60 MB; unggah satu wilayah lebih kecil.")
    filename = Path(str(filename)).name
    suffix = Path(filename).suffix.lower()
    if suffix == ".zip":
        raw = _zip_shape_to_gdf(content)
    elif suffix in {".geojson", ".json"}:
        try:
            data = json.loads(content.decode("utf-8-sig"))
            if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
                raise ValueError("Invalid GeoJSON FeatureCollection")
            if len(data["features"]) > MAX_FEATURES:
                raise VillageUploadError("Terlalu banyak fitur; unggah hanya satu kabupaten/provinsi.")
            with tempfile.TemporaryDirectory(prefix="ifw_namobj_") as td:
                file_path = Path(td) / "villages.geojson"
                file_path.write_bytes(content)
                raw = gpd.read_file(file_path)
        except VillageUploadError:
            raise
        except Exception as exc:
            raise VillageUploadError("GeoJSON bukan FeatureCollection yang dapat dibaca.") from exc
    else:
        raise VillageUploadError("Unggah shapefile dalam .zip atau satu file .geojson.")

    if raw.empty or len(raw) > MAX_FEATURES:
        raise VillageUploadError("Layer desa kosong atau terlalu banyak fitur (>12.000).")
    if raw.crs is None:
        raise VillageUploadError("CRS tidak ditemukan. Sertakan .prj untuk Shapefile atau gunakan GeoJSON WGS84.")
    fields = {str(k).casefold(): k for k in raw.columns}
    name_col = fields.get("namobj")
    if name_col is None:
        raise VillageUploadError("Kolom NAMOBJ tidak ditemukan di tabel atribut. Periksa nama field yang sebenarnya.")
    code_col = next((fields[v.casefold()] for v in SOURCE_CODE_COLUMNS if v.casefold() in fields), None)
    try:
        projected = raw.to_crs("EPSG:4326")
        geoms = projected.geometry.copy()
        geoms = geoms.make_valid()
    except Exception as exc:
        raise VillageUploadError("Gagal mengonversi geometri ke EPSG:4326; periksa file .prj.") from exc
    layer = gpd.GeoDataFrame({
        "namobj": raw[name_col].fillna("").astype(str).str.strip().values,
        "kode_sumber": (raw[code_col].fillna("").astype(str).str.strip().values
                        if code_col is not None else [""] * len(raw)),
        "feature_id": np.arange(len(raw), dtype=np.int32),
    }, geometry=geoms.values, crs="EPSG:4326")
    layer = layer.loc[layer.geometry.notna() & ~layer.geometry.is_empty].copy()
    layer = layer.loc[layer.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    layer = layer.loc[layer.intersects(box(92, -13, 143, 8))].copy()
    if layer.empty:
        raise VillageUploadError("Tidak ada poligon desa dalam jangkauan geografis Indonesia.")
    if not layer.namobj.ne("").any():
        raise VillageUploadError("Semua nilai NAMOBJ kosong; tidak ada nama desa yang dapat ditampilkan.")
    layer = layer.reset_index(drop=True)
    metadata = {
        "filename": filename,
        "name_field": str(name_col),
        "code_field": str(code_col) if code_col else "tidak tersedia",
        "features": len(layer),
        "blank_names": int(layer.namobj.eq("").sum()),
        "source_crs": str(raw.crs),
    }
    return layer, metadata


def annotate_named_villages(
    detections: pd.DataFrame, layer: gpd.GeoDataFrame
) -> tuple[pd.DataFrame, dict]:
    """Vectorized one-to-one match using spatial join, never nearest-neighbor.

    Boundary points matching >=2 polygons are flagged ambiguous.
    """
    df = detections.copy().reset_index(drop=True)
    df["desa"] = "Belum teridentifikasi"
    df["kode_desa"] = ""
    df["desa_status"] = "Di luar cakupan batas desa unggahan"
    stats = {"matched": 0, "unmatched": len(df), "ambiguous": 0, "unnamed": 0}
    if df.empty or layer.empty:
        return df, stats
    xy = gpd.points_from_xy(df.longitude.astype(float), df.latitude.astype(float), crs="EPSG:4326")
    pts = gpd.GeoDataFrame({"_point_id": np.arange(len(df), dtype=np.int32)}, geometry=xy, crs="EPSG:4326")
    joined = gpd.sjoin(pts, layer[["namobj", "kode_sumber", "geometry"]], how="left", predicate="intersects")
    good = joined.loc[joined["index_right"].notna()].copy()
    if good.empty:
        return df, stats
    counts = good.groupby("_point_id").size()
    ambiguous = counts[counts > 1].index.to_numpy(dtype=int)
    df.loc[ambiguous, "desa"] = "Ambigu (poligon tumpang tindih)"
    df.loc[ambiguous, "desa_status"] = "Ambigu (poligon tumpang tindih)"
    only = counts[counts == 1].index
    candidates = good.loc[good._point_id.isin(only)].set_index("_point_id")
    named = candidates.loc[candidates.namobj.astype(str).str.strip().ne("")]
    missing_names = candidates.loc[candidates.namobj.astype(str).str.strip().eq("")]
    if len(named):
        idx = named.index.to_numpy(dtype=int)
        df.loc[idx, "desa"] = named.namobj.astype(str).values
        df.loc[idx, "kode_desa"] = named.kode_sumber.fillna("").astype(str).values
        df.loc[idx, "desa_status"] = "Cocok dengan poligon desa (NAMOBJ)"
    if len(missing_names):
        idx = missing_names.index.to_numpy(dtype=int)
        df.loc[idx, "desa_status"] = "Poligon cocok, tetapi NAMOBJ kosong"
    stats = {
        "matched": len(named),
        "unmatched": len(df) - len(named) - len(ambiguous),
        "ambiguous": len(ambiguous),
        "unnamed": len(missing_names),
    }
    return df, stats
