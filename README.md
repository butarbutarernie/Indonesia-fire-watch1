# Indonesia Fire Watch v2.2 — NAMOBJ otomatis via NPZ nasional

## Yang berubah

Modul `national_village_lookup.py` menggunakan format NPZ yang **sama** dengan
`village_lookup.py` dari aplikasi Kalimantan Fire Watch:
`geometry_bytes`, `geometry_offsets`, `desa`, `kecamatan`, `kabupaten`, `provinsi`, `kode_pum`.
Manifest nasional juga menyimpan `source_rows` dan bbox per-arsip untuk menghindari
kesalahan padanan nama provinsi English–Bahasa.

Peta, FIRMS NOAA-20/21, statistik dan filter tetap memakai kode sebelumnya.
`village_upload.py` masih bisa digunakan untuk unggahan poligon kecil secara opsional.
Reader GeoParquet lama dipertahankan sebagai fallback jika URL Release sebelumnya sudah tersedia.

## Perlu data tambahan

**Kode saja tidak membuat nama desa langsung muncul.** Anda perlu meletakkan
85 NPZ + `national_village_manifest.json` yang sudah dihasilkan CELL 7
ke folder lokal `data/` dalam app runtime.

Lokasi di Drive Colab:
`MyDrive/Indonesia_Fire_Watch/04_NPZ_NATIONAL_LOOKUP/20261022T035845Z/data/`

File terbesar pada output CELL 7 adalah 7,97 MiB; total ukuran semua NPZ belum dilaporkan.

## Uji lokal tertutup, tidak memublikasikan data

1. Di laptop buat folder aplikasi hasil ekstrak paket ini.
2. Letakkan 85 NPZ + satu manifest pada folder `data/`.
3. Instal: `pip install -r requirements.txt`.
4. Jalankan: `streamlit run streamlit_app.py`.
5. Isi `FIRMS_MAP_KEY` lewat `.streamlit/secrets.toml` (jangan commit) atau
   pilih unggah CSV FIRMS.
6. Sidebar semestinya menampilkan `NAMOBJ nasional siap: 83.489 poligon dalam 85 arsip NPZ lokal`.
7. Saat deteksi tepat beririsan dengan satu poligon: popup Desa diambil dari `NAMOBJ`.
   Jika tidak cocok / lebih dari satu polygon: status dinyatakan, bukan ditebak.

**Publikasi:** jangan mengunggah NPZ ke GitHub *publik* atau Release publik
sebelum syarat dan hak redistribusi dari pemegang data BIG diketahui.
Jika tidak memungkinkan, gunakan penyimpanan privat dengan otentikasi;
reader file privat perlu adapter distribusi aset tambahan.

## Deploy ke repository pengujian

Upload kode utama (tanpa aset geospasial besar) ke branch `v2.0-testing`:
`streamlit_app.py`, `national_village_lookup.py`, `national_namobj.py`,
`admin_core.py`, `firewatch_core.py`, `village_upload.py`, `requirements.txt`.
Jangan ubah branch `main` sebelum nama desa otomatis terverifikasi.

Jika NPZ belum ada di runtime Streamlit Cloud, aplikasi akan tetap menampilkan
FIRMS tetapi menyatakan bahwa NAMOBJ lokal belum terpasang. Ini benar, bukan bug.

## Status dan keterbatasan

- Dari output CELL 7: 83.489 polygons, 85 NPZ, 39 kelompok (38 provinsi + 1 tanpa atribut provinsi).
- 29 geometri invalid tidak masuk NPZ; di wilayahnya deteksi dapat tidak bernama.
- 31 pengujian modul dasar lulus secara offline; belum menjalankan aplikasi end-to-end dengan NPZ nyata dari Drive pada Streamlit Cloud.
- Setiap hotspot adalah rekaman anomali termal, bukan satu kejadian kebakaran terkonfirmasi.
