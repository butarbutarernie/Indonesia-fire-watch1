"""Indonesia Fire Watch: automatic village names from existing NAMOBJ GeoParquet.

No KDEPUM validation or new source QC is required. The only village label is
`namobj`, copied directly from source field NAMOBJ by Cell 5. Point-to-polygon
intersection determines the matching village; no name-based geocoding.

This module can use the local Cell-5 staging directory or flat public GitHub
Release assets. Keep the source shapefile and existing staging files unchanged.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
import json
import os
import tempfile

import geopandas as gpd
import numpy as np
import pandas as pd
import requests


class NationalNamobjError(RuntimeError):
    """A required NAMOBJ dataset/asset could not be used."""


MATCH_STATUS = "Cocok dengan poligon desa (NAMOBJ nasional)"
UNMATCHED_STATUS = "Di luar cakupan poligon NAMOBJ nasional"
AMBIGUOUS_STATUS = "Ambigu (beberapa poligon desa)"


def _is_public_release_url(url: str) -> bool:
    parts = urlparse(url.strip())
    return (
        parts.scheme == "https" and parts.hostname == "github.com"
        and "/releases/download/" in parts.path
        and not parts.username and not parts.password and not parts.query
    )


def _remote_download(url: str, destination: Path, expected_sha256: str | None = None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Filename embeds manifest digest, allowing immutable caching across versions.
    if destination.is_file():
        if expected_sha256 is None or _sha_file(destination) == expected_sha256:
            return destination
        destination.unlink()
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=destination.name + ".", suffix=".part", delete=False
    ) as tmp_f:
        tmp = Path(tmp_f.name)
    total = 0
    digest = sha256()
    try:
        with requests.get(url, stream=True, timeout=(15, 120), allow_redirects=True) as response:
            response.raise_for_status()
            # One shard should not unboundedly consume Streamlit's ephemeral disk.
            with tmp.open("wb") as f:
                for block in response.iter_content(chunk_size=1024 * 1024):
                    if not block:
                        continue
                    total += len(block)
                    if total > 300 * 1024 * 1024:
                        raise NationalNamobjError("File shard melebihi batas 300 MiB.")
                    digest.update(block)
                    f.write(block)
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise NationalNamobjError("Checksum shard berbeda dari manifest.")
        os.replace(tmp, destination)
    except (requests.RequestException, OSError) as exc:
        raise NationalNamobjError(f"Gagal mengunduh aset NAMOBJ: {url.rsplit('/', 1)[-1]}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return destination


def _sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class NamobjGeoParquetStore:
    """Lazy shard reader from Cell-5 GeoParquet, local or GitHub Release.

    Remote mode expects GEOPARQUET_MANIFEST.json and the flattened 28 shard
    filenames as Release assets. Do not upload the original shapefile.
    """

    def __init__(self, local_stage: str | Path | None = None,
                 release_url: str | None = None, cache_dir: str | Path | None = None):
        if bool(local_stage) == bool(release_url):
            raise NationalNamobjError("Pilih local_stage ATAU release_url, bukan keduanya.")
        self.local_stage = Path(local_stage) if local_stage else None
        self.release_url = str(release_url).strip().rstrip("/") if release_url else None
        if self.release_url and not _is_public_release_url(self.release_url):
            raise NationalNamobjError("URL harus HTTPS GitHub Releases publik (/releases/download/).")
        self.cache_dir = Path(cache_dir or (Path(tempfile.gettempdir()) / "ifw_namobj_cache"))
        if self.release_url:
            # Changing the Release tag must not reuse a stale manifest.
            self.cache_dir = self.cache_dir / sha256(self.release_url.encode("utf8")).hexdigest()[:16]
        self.manifest = self._get_manifest()
        self.shards = self.manifest.get("shards", [])
        if not isinstance(self.shards, list) or not self.shards:
            raise NationalNamobjError("Manifest tidak berisi daftar shard GeoParquet.")

    def _get_manifest(self) -> dict:
        if self.local_stage:
            manifest_file = self.local_stage / "GEOPARQUET_MANIFEST.json"
        else:
            manifest_file = self.cache_dir / "GEOPARQUET_MANIFEST.json"
            _remote_download(self.release_url + "/GEOPARQUET_MANIFEST.json", manifest_file)
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise NationalNamobjError("GEOPARQUET_MANIFEST.json tidak dapat dibaca.") from exc
        if manifest.get("name_attribute") != "namobj (copied from source NAMOBJ)":
            raise NationalNamobjError("Atribut manifest bukan NAMOBJ hasil Cell 5.")
        return manifest

    def load_shard(self, entry: dict) -> gpd.GeoDataFrame:
        rel = str(entry.get("file", ""))
        if not rel or not rel.endswith(".parquet"):
            raise NationalNamobjError("Nama shard GeoParquet tidak benar.")
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts:
            raise NationalNamobjError("Path shard tidak aman.")
        checksum = str(entry.get("sha256", ""))
        if self.local_stage:
            path = self.local_stage / rel
            if not path.is_file():
                raise NationalNamobjError(f"Shard tidak ditemukan: {rel}")
        else:
            # Files in a GitHub Release are flat; they cannot include slashes.
            flat_name = pure.name
            path = self.cache_dir / checksum[:12] / flat_name
            _remote_download(self.release_url + "/" + flat_name, path, expected_sha256=checksum)
        try:
            frame = gpd.read_parquet(path)
        except (OSError, ValueError, ImportError) as exc:
            raise NationalNamobjError(f"Shard GeoParquet tidak dapat dibaca: {pure.name}") from exc
        if "namobj" not in frame.columns or "geometry" not in frame.columns:
            raise NationalNamobjError(f"Shard tanpa NAMOBJ/geometri: {pure.name}")
        if frame.crs is None:
            raise NationalNamobjError(f"Shard tidak memiliki CRS: {pure.name}")
        if str(frame.crs).upper() != "EPSG:4326":
            frame = frame.to_crs("EPSG:4326")
        return frame


def annotate_namobj_points(detections: pd.DataFrame, store: NamobjGeoParquetStore):
    """Get NAMOBJ label by point-in-polygon from existing GeoParquet shards.

    Unique polygon intersection -> NAMOBJ. Multiple polygons -> ambiguous.
    No match -> unidentified. No KDEPUM or unique village-code dependency.
    """
    df = detections.copy().reset_index(drop=True)
    if "longitude" not in df.columns or "latitude" not in df.columns:
        raise NationalNamobjError("Data FIRMS harus memiliki latitude dan longitude.")
    for name, default in (
        ("desa", "Belum teridentifikasi"), ("kode_desa", ""),
        ("desa_status", UNMATCHED_STATUS), ("kabupaten_kota", "Belum dipilih"),
        ("kecamatan", "Belum dipilih"),
    ):
        if name not in df.columns:
            df[name] = default
    df["desa"] = "Belum teridentifikasi"
    df["kode_desa"] = ""  # KDEPUM intentionally NOT used.
    df["desa_status"] = UNMATCHED_STATUS

    if df.empty:
        return df, {"matched": 0, "ambiguous": 0, "unmatched": 0, "used_shards": 0}

    lon = pd.to_numeric(df.longitude, errors="coerce")
    lat = pd.to_numeric(df.latitude, errors="coerce")
    valid = lon.notna() & lat.notna() & lon.between(-180, 180) & lat.between(-90, 90)
    point_ids = np.flatnonzero(valid.to_numpy())
    if not len(point_ids):
        return df, {"matched": 0, "ambiguous": 0, "unmatched": len(df), "used_shards": 0}
    pts = gpd.GeoDataFrame(
        {"_point_id": point_ids},
        geometry=gpd.points_from_xy(lon.iloc[point_ids].to_numpy(), lat.iloc[point_ids].to_numpy()),
        crs="EPSG:4326",
    )
    matches = []
    used_shards = 0
    for entry in store.shards:
        x0, y0, x1, y1 = (float(v) for v in entry["bbox_wgs84"])
        eligible = lon.iloc[point_ids].between(x0, x1) & lat.iloc[point_ids].between(y0, y1)
        if not eligible.any():
            continue
        shard = store.load_shard(entry)
        used_shards += 1
        if shard.empty:
            continue
        optional = [v for v in ("province_source", "regency_source", "district_source") if v in shard.columns]
        subset = shard[["namobj", "source_row", *optional, "geometry"]].copy()
        hits = gpd.sjoin(pts.loc[eligible.to_numpy()], subset, predicate="intersects", how="inner")
        if not hits.empty:
            keep = ["_point_id", "source_row", "namobj", *optional]
            matches.append(hits[keep])
        del subset, shard

    if not matches:
        return df, {"matched": 0, "ambiguous": 0, "unmatched": len(df), "used_shards": used_shards}
    joined = pd.concat(matches, ignore_index=True)
    # This protects against accidentally exporting an identical source feature
    # to more than one shard, without conflating distinct villages named alike.
    joined = joined.drop_duplicates(subset=["_point_id", "source_row"])
    groups = joined.groupby("_point_id", sort=False).size()
    ambiguous_ids = groups.index[groups > 1].to_numpy(dtype=int)
    if len(ambiguous_ids):
        df.loc[ambiguous_ids, "desa"] = "Ambigu (lebih dari satu batas desa)"
        df.loc[ambiguous_ids, "desa_status"] = AMBIGUOUS_STATUS

    unique_ids = groups.index[groups == 1]
    unique = joined.set_index("_point_id").loc[unique_ids]
    names = unique["namobj"].fillna("").astype(str).str.strip()
    named = names.ne("")
    usable = unique.loc[named]
    if not usable.empty:
        idx = usable.index.to_numpy(dtype=int)
        df.loc[idx, "desa"] = usable["namobj"].astype(str).to_numpy()
        df.loc[idx, "desa_status"] = MATCH_STATUS
        for src, dest in (("regency_source", "kabupaten_kota"),
                          ("district_source", "kecamatan")):
            if src in usable:
                vals = usable[src].fillna("").astype(str).str.strip().to_numpy()
                old = df.loc[idx, dest].astype(str).to_numpy()
                df.loc[idx, dest] = np.where(vals != "", vals, old)
        if "province_source" in usable and "province" in df.columns:
            vals = usable["province_source"].fillna("").astype(str).str.strip().to_numpy()
            old = df.loc[idx, "province"].astype(str).to_numpy()
            df.loc[idx, "province"] = np.where(vals != "", vals, old)
    return df, {
        "matched": int(len(usable)),
        "ambiguous": int(len(ambiguous_ids)),
        "unmatched": int(len(df) - len(usable) - len(ambiguous_ids)),
        "used_shards": used_shards,
    }
