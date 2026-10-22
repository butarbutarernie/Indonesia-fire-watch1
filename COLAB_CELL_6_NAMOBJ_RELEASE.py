# ================================================================
# INDONESIA FIRE WATCH v2.1 - CELL 6
# Existing NAMOBJ GeoParquet -> flat GitHub Release assets
# NO new shapefile audit, NO geometry transformation, NO KDEPUM checks.
# Does NOT upload anything to a public website automatically.
# ================================================================

from pathlib import Path
import shutil
import json

STAGE_DIR = Path(
    '/content/drive/MyDrive/Indonesia_Fire_Watch/01_QC_NAMOBJ/'
    '20261022T022914Z/02_GEOPARQUET_STAGING_V212'
)

RELEASE_TAG = 'namobj-national-v1'
ASSETS_DIR = Path(
    '/content/drive/MyDrive/Indonesia_Fire_Watch/'
    '03_NAMOBJ_RELEASE_ASSETS/namobj-national-v1'
)

# The 28 GeoParquet shards are already created and read back by CELL 5.
manifest_path = STAGE_DIR / 'GEOPARQUET_MANIFEST.json'
if not manifest_path.is_file():
    raise FileNotFoundError(f'Manifest CELL 5 tidak ditemukan: {manifest_path}')
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
entries = manifest['shards']
print('Cell 5 NAMOBJ shards:', len(entries))
print('Existing village polygons:', manifest['model_ready_count'])

ASSETS_DIR.mkdir(parents=True, exist_ok=True)
for i, entry in enumerate(entries, 1):
    src = STAGE_DIR / entry['file']
    dst = ASSETS_DIR / Path(entry['file']).name
    if not src.is_file():
        raise FileNotFoundError(f'File hasil CELL 5 hilang: {src}')
    if dst.is_file() and dst.stat().st_size == src.stat().st_size:
        print(f'SKIP {i:02d}/{len(entries):02d} | {dst.name} (sudah tersalin)')
        continue
    shutil.copy2(src, dst)
    print(f'COPY {i:02d}/{len(entries):02d} | {dst.name}')

shutil.copy2(manifest_path, ASSETS_DIR / 'GEOPARQUET_MANIFEST.json')

print('\n' + '=' * 70)
print('IFW v2.1 - NAMOBJ RELEASE ASSETS READY')
print('Folder:', ASSETS_DIR)
print('Tag GitHub Release:', RELEASE_TAG)
print('Assets to upload:', len(entries) + 1)
print('NAMOBJ is the ONLY village-name field; KDEPUM not required.')
print('No source geometry or staged GeoParquet was changed.')
print('NEXT: download this folder to laptop, then attach all 29 files')
print('to a GitHub Release after checking you are permitted to distribute')
print('these administrative boundaries publicly.')
print('=' * 70)
