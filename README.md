# Indonesia Fire Watch - National Streamlit Prototype

This is a **new, standalone implementation**, not a line-by-line modification of the linked `kalimantan-fire-watch` repository. The original source URL was not readable during preparation.

## Scope

- Indonesia-wide FIRMS VIIRS NOAA-20 and NOAA-21 near-real-time observations
- Country-polygon clipping using full-resolution geoBoundaries ADM0 (the bounding box alone is not sufficient)
- Province attribution using geoBoundaries ADM1
- Filters for data source, 1-5 recent days, province and VIIRS confidence class
- National map, daily time series, province ranking, CSV and GeoJSON exports
- Uploaded standard NASA FIRMS CSV can be analyzed without API access
- Data provenance and warnings about hotspot interpretation

**This prototype does not confirm fires, map burn scars, predict fire risk, or calculate independent fire events.** Multiple satellite observations may represent the same fire.

## Deployment on Streamlit Community Cloud

1. Create a *new* GitHub repository (recommended, to keep your original Kalimantan app unchanged).
2. Copy `streamlit_app.py`, `firewatch_core.py`, `requirements.txt`, `.streamlit/config.toml`, and `.gitignore` to the repository.
3. Obtain a free NASA FIRMS MAP_KEY at https://firms.modaps.eosdis.nasa.gov/api/map_key/ .
4. In Streamlit Community Cloud, choose `streamlit_app.py` as the entrypoint and add this to **Secrets**, not to GitHub:

   ```toml
   FIRMS_MAP_KEY = "YOUR_REAL_MAP_KEY"
   ```

5. Deploy. Choose active-fire sensor(s), recent day range (1-5), and a province.
6. Optionally select **Upload FIRMS CSV** to analyze your archived data without API requests.

### Local execution

```bash
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

For local API use, create `.streamlit/secrets.toml` with the key. Do **not** commit that file.

## Scientific and technical limitations

1. API `/api/area/csv` limits one request to **1-5 days**. This prototype offers most recent 1-5 days only. Historic multi-month time series need date-specific paginated requests, rate limits and archival strategy.
2. Coordinates initially use bbox `94,-12,142,7`, which also includes foreign lands. An exact polygon intersection with Indonesia (ADM0) is mandatory before counts are shown.
3. geoBoundaries ADM1 may be historical/outdated relative to current Indonesian provincial boundaries; the app displays its provenance. For publishable administrative counts, substitute a vetted, time-aligned Indonesian authoritative boundary file.
4. `confidence` from VIIRS and number of detections should not be treated as a probability of fire occurrence or as unique fire incidents. FRP is not burned area.
5. Default map draws up to 12,000 deterministic sample points when datasets are large. Statistics and CSV downloads use all filtered records.
6. Current prototype depends on availability of NASA FIRMS, geoBoundaries, and Carto tiles. Streamlit cache helps limit repeated calls.
7. For national operational production: add persistence, backoff/retry, APIs status monitoring, audit logs, cloud hosting scale-up, and administrator-controlled shapefile versioning.

## Files

- `streamlit_app.py`: Streamlit UI
- `firewatch_core.py`: ingest, validation, polygon clipping, province assignment
- `requirements.txt`: Python dependencies
- `.streamlit/config.toml`: theme
- `.gitignore`: secrets protection
- `tests/test_firewatch_core.py`: offline tests (synthetic polygons)

## Data sources

- NASA FIRMS: https://firms.modaps.eosdis.nasa.gov/api/area/
- geoBoundaries gbOpen: https://www.geoboundaries.org/ (license and original source require proper credit)

This is an initial engineering prototype; the original repository's features could only be preserved after its complete files are made available.
