# Indonesia Fire Watch v2.1: NAMOBJ otomatis (tanpa audit ulang)

**Dataset tersedia:** Cell 5 selesai, 83.489 geometri dalam 28 berkas GeoParquet; 29 geometri yang tidak valid tidak disertakan. Kolom `namobj` berasal langsung dari `NAMOBJ` Shapefile. Tidak perlu memakai atau mengaudit `KDEPUM` untuk menampilkan nama desa.

## 1. Pembaruan kode Streamlit

- Buka repository `butarbutarernie/Indonesia-fire-watch1`, branch **`v2.0-testing`**.
- Unggah isi paket kode v2.1 (bukan ZIP-nya) dengan **Add file > Upload files**, lalu **Commit changes** ke branch itu.
- Pastikan file baru `national_namobj.py` ada di root bersama `streamlit_app.py`.
- `main` untuk aplikasi v1 tidak berubah. `streamlit_app.py` v2.1 akan tetap menampilkan hotspot meskipun sumber nasional belum dipasangkan.

## 2. Siapkan aset GeoParquet yang sudah ada

- Jalankan kode `CELL_6_IFW_NAMOBJ_RELEASE_READY.py` di Google Colab, pada runtime dengan Google Drive mounted.
- Kode itu **hanya menyalin** 28 shard GeoParquet dan `GEOPARQUET_MANIFEST.json` menjadi **29 file datar**, tanpa audit dan tanpa mengubah geometri.
- Buka folder Google Drive `Indonesia_Fire_Watch/03_NAMOBJ_RELEASE_ASSETS/namobj-national-v1`, download semua file ke laptop.

## 3. Tempatkan aset di GitHub Releases (jika hak distribusinya mengizinkan)

- Repository GitHub publik membuat Release dan asetnya bisa diakses publik. **Jangan unggah data administrasi ke Release publik apabila lisensi/hak distribusi sumber belum mengizinkan.** Dalam kasus itu gunakan penyimpanan data privat dan integrasi backend autentikasi sebagai pengganti.
- Jika diizinkan, buka `https://github.com/butarbutarernie/Indonesia-fire-watch1/releases/new`.
- Target branch: `v2.0-testing`, tag: `namobj-national-v1`, release title: `NAMOBJ Village Boundaries - IFW v2.1`.
- Unggah **29 file**: 28 `desa_part_*.parquet` dan `GEOPARQUET_MANIFEST.json`. Jangan unggah ZIP atau Shapefile asli. Semua berada pada **satu Release**.
- Klik **Publish release**.

## 4. Set Streamlit Secrets untuk aplikasi pengujian

Buka Streamlit Community Cloud, pilih aplikasi v2 yang menggunakan branch `v2.0-testing`, lalu `Settings > Secrets`. **Pertahankan** `FIRMS_MAP_KEY` yang sudah ada. Tambahkan:

```toml
IFW_NAMOBJ_RELEASE_URL = "https://github.com/butarbutarernie/Indonesia-fire-watch1/releases/download/namobj-national-v1"
```

Klik Save dan rerun aplikasi. Nama desa pada popup diambil langsung dari `NAMOBJ` jika titik FIRMS jatuh dalam tepat satu poligon. Untuk titik di luar cakupan 83.489 poligon atau yang berada pada tumpang tindih beberapa poligon, aplikasi menampilkan status belum teridentifikasi / ambigu, bukan mengarang nama.

**KDEPUM tidak dipakai** untuk penamaan, pemilihan, ataupun pencocokan spasial. Label provinsi, kabupaten, dan kecamatan opsional dibaca dari WADMPR, WADMKK, WADMKC pada GeoParquet jika tersedia.

## 5. Batasan teknis

- Unduhan pertama dari GitHub Release akan menggunakan koneksi dan disk sementara Streamlit; file kandidat di-cache lokal sampai runtime di-restart.
- Program saat ini menyaring shard kandidat menggunakan bounding box di manifest sebelum memuat poligon, tetapi manifest shard dibuat berdasarkan urutan sumber (bukan grid provinsi). Pada banyak hotspot yang tersebar nasional, sebagian besar shard masih dapat perlu diunduh. Jika waktu muat terlalu tinggi, langkah teknis berikutnya adalah membuat partisi spasial/tile; **tidak diperlukan audit atribut tambahan**.
- Aplikasi belum diuji dengan 28 file nasional pada Streamlit Cloud; pengujian logika offline berhasil menggunakan data sintetis.
