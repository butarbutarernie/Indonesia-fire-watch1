"""National adaptation of Kalimantan Fire Watch village_lookup.py.

Input: national_village_manifest.json + villages_lookup_*.npz from CELL 7.
The per-archive NPZ arrays match the exact Kalimantan data format.
Matching is spatial (STRtree point/polygon), not NAMOBJ-name lookup nor KDEPUM.

Important: Loading this module alone does not change any Streamlit app. Integrate
annotate_national_npz() after FIRMS coordinate filtering and before map rendering.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json
import logging

import numpy as np
import pandas as pd
import shapely
from shapely.strtree import STRtree

LOG = logging.getLogger(__name__)
MATCH_STATUS = "Ditemukan pada poligon desa (NAMOBJ nasional NPZ)"
AMBIGUOUS_STATUS = "Ambigu: beberapa poligon desa beririsan"
UNMATCHED_STATUS = "Tidak tercakup poligon desa nasional"
MISSING_STATUS = "Referensi poligon desa tidak lengkap"


def _within(bbox, xs, ys):
    left, bottom, right, top = [float(v) for v in bbox]
    return (xs >= left) & (xs <= right) & (ys >= bottom) & (ys <= top)


def inspect_national_npz_assets(data_dir: str | Path) -> dict:
    data_dir = Path(data_dir)
    path = data_dir / "national_village_manifest.json"
    if not path.is_file():
        return {"configured": False, "manifest": str(path), "found": 0,
                "missing": [], "expected": 0, "lookup_polygons": 0}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = manifest.get("files", [])
    if manifest.get("schema") != "IFW-NPZ-KFW-1" or not entries:
        raise ValueError("Unknown NPZ manifest schema")
    missing = []
    found = 0
    for item in entries:
        # Manifest paths are relative to release root (data/file.npz).
        rel = Path(str(item["file"]))
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Unsafe NPZ manifest path")
        file = (data_dir.parent / rel) if rel.parts[0] == "data" else (data_dir / rel)
        if file.is_file() and file.stat().st_size > 1024:
            found += 1
        else:
            missing.append(item["file"])
    return {"configured": True, "manifest": str(path), "found": found,
            "missing": missing, "expected": len(entries),
            "lookup_polygons": int(manifest["lookup_polygons"])}


@lru_cache(maxsize=2)
def _load_partition(path_str: str):
    """Identical core format to Kalimantan: WKB bytes/offsets + labels."""
    path = Path(path_str)
    with np.load(path, allow_pickle=False) as dat:
        data = dat["geometry_bytes"].tobytes()
        offsets = dat["geometry_offsets"].copy()
        labels = {k: dat[k].astype(str)
                  for k in ("desa", "kecamatan", "kabupaten", "provinsi", "kode_pum")}
        rows = dat["source_rows"].astype(np.int64)
    n = len(labels["desa"])
    if len(offsets) != n + 1 or len(rows) != n:
        raise ValueError("Village archive offsets/labels mismatch")
    if int(offsets[0]) != 0 or int(offsets[-1]) != len(data) or np.any(np.diff(offsets) <= 0):
        raise ValueError("Village archive has invalid WKB offsets")
    geoms = shapely.from_wkb([data[int(a):int(b)]
                              for a, b in zip(offsets[:-1], offsets[1:])])
    if np.any(~shapely.is_valid(geoms)) or np.any(shapely.is_empty(geoms)):
        raise ValueError("Invalid or empty village polygon")
    return STRtree(geoms), labels, rows


def annotate_national_npz(df: pd.DataFrame, data_dir: str | Path):
    """Fill village fields for all Indonesian points using manifest bbox + STRtree.

    Does not depend on a point's pre-existing province label (English vs Bahasa).
    Unknown, ambiguous, or incomplete data is not silently assigned a village.
    """
    data = df.copy().reset_index(drop=True)
    for col in ("desa", "kecamatan", "kabupaten_kota", "kode_desa", "desa_status",
                "provinsi_namobj"):
        if col not in data:
            data[col] = ""
    if data.empty:
        return data, {"matched": 0, "ambiguous": 0, "unmatched": 0,
                      "missing_assets": 0, "used_shards": 0}
    if not {"longitude", "latitude"}.issubset(data.columns):
        raise ValueError("Need longitude and latitude")

    directory = Path(data_dir)
    manifest_file = directory / "national_village_manifest.json"
    if not manifest_file.is_file():
        raise FileNotFoundError("national_village_manifest.json missing")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("schema") != "IFW-NPZ-KFW-1":
        raise ValueError("Incorrect national manifest schema")

    lon = pd.to_numeric(data["longitude"], errors="coerce").to_numpy(float)
    lat = pd.to_numeric(data["latitude"], errors="coerce").to_numpy(float)
    good = np.isfinite(lon) & np.isfinite(lat)
    data["desa_status"] = UNMATCHED_STATUS
    data.loc[~good, "desa_status"] = "Koordinat deteksi tidak valid"

    # Per-point unique SOURCE ROW identity eliminates false duplicates if files
    # are accidentally listed twice. Distinct overlapping village polygons
    # remain ambiguous, even if they share the same NAMOBJ.
    matches: dict[int, dict[int, tuple[str, str, str, str, str]]] = {}
    incomplete = np.zeros(len(data), dtype=bool)
    archive_problems = 0
    used_shards = 0
    for entry in manifest["files"]:
        if not all(k in entry for k in ("file", "bbox_wgs84", "n_features")):
            raise ValueError("Malformed NPZ manifest entry")
        within = good & _within(entry["bbox_wgs84"], lon, lat)
        if not np.any(within):
            continue
        rel = Path(str(entry["file"]))
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Unsafe NPZ archive path")
        path = (directory.parent / rel) if rel.parts[0] == "data" else (directory / rel)
        if not path.is_file():
            incomplete |= within
            archive_problems += 1
            continue
        try:
            tree, labels, source_rows = _load_partition(str(path.resolve()))
            used_shards += 1
            indexes = np.flatnonzero(within)
            points = shapely.points(lon[indexes], lat[indexes])
            pairs = tree.query(points, predicate="intersects")
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as e:
            LOG.warning("National village asset unreadable: %s (%s)", path.name,
                        type(e).__name__)
            incomplete |= within
            archive_problems += 1
            continue
        for sub_index, polygon_index in zip(pairs[0], pairs[1]):
            point_index = int(indexes[int(sub_index)])
            pi = int(polygon_index)
            rid = int(source_rows[pi])
            matches.setdefault(point_index, {})[rid] = tuple(
                str(labels[field][pi])
                for field in ("desa", "kecamatan", "kabupaten", "provinsi", "kode_pum")
            )

    matched = ambiguous = 0
    for idx, found in matches.items():
        # If an asset covering the point could not be loaded, we cannot be sure
        # whether another polygon would overlap this apparent unique match.
        if incomplete[idx]:
            data.at[idx, "desa_status"] = MISSING_STATUS
            continue
        if len(found) > 1:
            data.at[idx, "desa_status"] = AMBIGUOUS_STATUS
            ambiguous += 1
            continue
        village, district, regency, province, source_code = next(iter(found.values()))
        if not village.strip():
            data.at[idx, "desa_status"] = "NAMOBJ kosong pada poligon yang cocok"
            continue
        data.at[idx, "desa"] = village
        data.at[idx, "kecamatan"] = district
        data.at[idx, "kabupaten_kota"] = regency
        data.at[idx, "provinsi_namobj"] = province
        data.at[idx, "kode_desa"] = source_code
        data.at[idx, "desa_status"] = MATCH_STATUS
        matched += 1

    data.loc[incomplete, "desa_status"] = MISSING_STATUS
    data.loc[incomplete, "desa"] = ""
    unmatched = int(len(data) - matched - ambiguous)
    return data, {"matched": matched, "ambiguous": ambiguous,
                  "unmatched": unmatched, "missing_assets": archive_problems,
                  "used_shards": used_shards}
