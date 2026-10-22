# IFW v2.1 - Verification Report

- **27 offline unit tests PASS**, including five new national-NAMOBJ tests.
- Python syntax compilation PASS for app and national backend.
- Source Cell-5 national GeoParquet is **not mounted here**; real end-to-end loading from Colab/GitHub Releases has not been tested.
- Original 83,489 valid polygons / 28 parquet shards remain untouched; 29 excluded geometry rows stay outside name lookup.
- Matching uses only `namobj` for village names; uses geometry for spatial lookup. No KDEPUM validation or review gate.

To re-run: `pytest -q tests`.
