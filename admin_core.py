"""On-demand Indonesian administration, from province to desa/kelurahan.

Emsifa v2 paths contain [latitude, longitude] rings. Convert to WGS84
(longitude, latitude) polygons for spatial *intersection*, never nearest town.
Geometries are simplified, non-authoritative and must be treated as provisional.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd
import requests
from shapely import covers, points, unary_union
from shapely.geometry import Polygon, mapping


API_BASE = "https://www.emsifa.com/api-wilayah-indonesia/v2"
CODE_PATTERN = re.compile(r"^\d{2}(?:\.\d{2}){0,2}(?:\.\d{4})?$")
REGION_LEVELS = {"provinces": 0, "regencies": 1, "districts": 2, "villages": 3}


class AdminDataError(RuntimeError):
    """Administrative data cannot be retrieved or safely interpreted."""


def validate_code(code: str, level: str | None = None) -> str:
    code = str(code)
    if not CODE_PATTERN.fullmatch(code):
        raise ValueError("Kode wilayah tidak valid.")
    if level is not None:
        expected = {"province": 0, "regency": 1, "district": 2, "village": 3}[level]
        if code.count(".") != expected:
            raise ValueError("Jenjang kode wilayah tidak sesuai.")
    return code


def fetch_admin_list(level: str, parent: str | None = None) -> tuple[list[dict], str]:
    """Fetch a single hierarchy list; never download all 80k village paths."""
    if level not in REGION_LEVELS:
        raise ValueError("Jenjang administrasi tidak dikenal.")
    if level == "provinces":
        if parent:
            raise ValueError("Daftar provinsi tidak memiliki parent.")
        path = "provinces.json"
    else:
        if not parent:
            raise ValueError("Kode parent wajib diisi.")
        level_parents = {"regencies": "province", "districts": "regency", "villages": "district"}
        path = f"{level}/{validate_code(parent, level_parents[level])}.json"
    try:
        res = requests.get(f"{API_BASE}/{path}", timeout=(8, 26))
        res.raise_for_status()
        payload = res.json()
        rows = payload["data"]
        if not isinstance(rows, list):
            raise TypeError("Invalid list payload")
        out = [
            {"id": validate_code(x["id"]), "name": str(x["name"]).strip(),
             "has_path": bool(x.get("has_path", False))}
            for x in rows
            if isinstance(x, dict) and "id" in x and "name" in x
        ]
        # Only accept expected child codes (prevents mixing territorial levels).
        expected_depth = REGION_LEVELS[level]
        out = [r for r in out if r["id"].count(".") == expected_depth]
        if not out:
            raise ValueError("Empty or incompatible administrative list")
        return sorted(out, key=lambda row: row["name"].casefold()), str(
            payload.get("meta", {}).get("updated_at", payload.get("meta", {}).get("generated_at", ""))
        )
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as exc:
        raise AdminDataError(f"Daftar {level} gagal dimuat. Coba lagi nanti.") from exc


def extract_latlon_rings(value: Any) -> list[list[tuple[float, float]]]:
    """Extract nested Emsifa rings; output Shapely-ordered (lon,lat) coordinates."""
    rings = []

    def walk(node):
        if not isinstance(node, list) or not node:
            return
        if (len(node) >= 3 and all(
            isinstance(p, (list, tuple)) and len(p) == 2 and
            all(isinstance(z, (int, float)) and not isinstance(z, bool) for z in p)
            for p in node
        )):
            ring = [(float(lng), float(lat)) for lat, lng in node
                    if -90 <= lat <= 90 and -180 <= lng <= 180]
            if len(ring) >= 3:
                rings.append(ring)
        else:
            for child in node:
                walk(child)

    walk(value)
    return rings


def polygon_from_path(path: Any):
    """Combine valid island rings; paths lack a guaranteed topology for holes.

    This uses geometric union, not nearest-centroid inference. Source path is
    simplified; results near coast and borders need verification with BIG.
    """
    rings = extract_latlon_rings(path)
    polys = []
    for ring in rings:
        geom = Polygon(ring)
        if not geom.is_valid:
            geom = geom.buffer(0)
        if not geom.is_empty and geom.area > 0:
            polys.append(geom)
    if not polys:
        raise AdminDataError("Tidak ada poligon batas wilayah yang valid.")
    geom = unary_union(polys)
    if geom.is_empty:
        raise AdminDataError("Poligon batas wilayah kosong.")
    return geom


def fetch_admin_polygon(code: str):
    """Fetch exactly one region's polygon and provenance timestamp."""
    code = validate_code(code)
    try:
        res = requests.get(f"{API_BASE}/paths/{code}.json", timeout=(8, 35))
        res.raise_for_status()
        payload = res.json()
        inner = payload["data"]
        if str(inner.get("id")) != code:
            raise ValueError("Polygon returned for wrong area")
        geom = polygon_from_path(inner["path"])
        stamp = str(payload.get("meta", {}).get("updated_at", ""))
        return geom, stamp
    except (requests.RequestException, ValueError, KeyError, TypeError, AdminDataError) as exc:
        raise AdminDataError(
            f"Batas poligon kode {code} tidak tersedia. Filter tidak diterapkan agar statistik tidak menyesatkan."
        ) from exc


def filter_points_in_polygon(df: pd.DataFrame, geometry) -> pd.DataFrame:
    """Strict spatial filter, including exact boundary intersections."""
    if df.empty:
        return df.copy()
    if geometry is None or geometry.is_empty:
        raise AdminDataError("Poligon pemilihan wilayah kosong.")
    xy = points(df["longitude"].to_numpy(dtype=float), df["latitude"].to_numpy(dtype=float))
    inside = covers(geometry, xy)
    return df.loc[np.asarray(inside, dtype=bool)].copy()


def geojson_region(geometry, name: str, code: str) -> dict:
    return {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"name": name, "code": code},
            "geometry": mapping(geometry),
        }],
    }


def annotate_village_polygons(
    df: pd.DataFrame, available: list[dict]
) -> tuple[pd.DataFrame, dict]:
    """Match all hotspots in ONE selected kecamatan to available desa polygons.

    Does not assign ambiguous overlaps; missing polygons remain unidentified.
    available: {id, name, geometry}; invalid features excluded by caller.
    """
    out = df.copy()
    out["desa"] = "Belum teridentifikasi"
    out["kode_desa"] = ""
    out["desa_status"] = "Tidak cocok pada poligon desa tersedia"
    if out.empty:
        return out, {"matched": 0, "ambiguous": 0, "unmatched": 0}
    xy = points(out.longitude.to_numpy(dtype=float), out.latitude.to_numpy(dtype=float))
    matches = np.zeros(len(out), dtype=np.int32)
    matched_name = np.full(len(out), "", dtype=object)
    matched_code = np.full(len(out), "", dtype=object)
    for item in available:
        geom = item.get("geometry")
        if geom is None or geom.is_empty:
            continue
        in_poly = np.asarray(covers(geom, xy), dtype=bool)
        matches += in_poly.astype(np.int32)
        matched_name[in_poly] = str(item["name"])
        matched_code[in_poly] = str(item["id"])
    single = matches == 1
    ambiguous = matches > 1
    out.loc[single, "desa"] = matched_name[single]
    out.loc[single, "kode_desa"] = matched_code[single]
    out.loc[single, "desa_status"] = "Cocok dengan poligon desa"
    out.loc[ambiguous, "desa"] = "Ambigu (poligon tumpang tindih)"
    out.loc[ambiguous, "desa_status"] = "Ambigu (poligon tumpang tindih)"
    return out, {
        "matched": int(single.sum()), "ambiguous": int(ambiguous.sum()),
        "unmatched": int((matches == 0).sum()),
    }
