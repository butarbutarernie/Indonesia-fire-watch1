# Indonesia Fire Watch v2.1 - NAMOBJ otomatis nasional

**Pembaruan terpenting:** 28 GeoParquet shards yang telah dibuat di Colab Cell 5 dapat menjadi sumber nama desa otomatis untuk setiap hotspot. Nama desa hanya diambil dari atribut `namobj` yang merupakan salinan asli kolom Shapefile `NAMOBJ`, menggunakan *point-in-polygon*. **Kode `KDEPUM` tidak digunakan dan audit atribut sebelumnya tidak perlu diulang.**

- **File baru** `national_namobj.py`: membaca manifest dan shard GeoParquet secara *lazy*, berdasarkan bounding box lokasi hotspot.
- **Aplikasi v2.1** `streamlit_app.py`: otomatis mengisi kolom `desa` dan popup saat Release assets sudah tersambung.
- **Aset data** 28 GeoParquet hasil Cell 5 **tidak termasuk di ZIP kode**. Siapkan 29 Release assets melalui `CELL_6_IFW_NAMOBJ_RELEASE_READY.py` (28 shard + 1 manifest) tanpa menyentuh shapefile asli.
- **Konfigurasi Streamlit:** `IFW_NAMOBJ_RELEASE_URL` di Secrets, lihat `PANDUAN_NAMOBJ_OTOMATIS.md`.
- **Penanganan batasan:** 29 fitur sumber yang sebelumnya invalid tidak tersedia di GeoParquet, dan lokasi di luar cakupan/tumpang tindih akan ditandai, bukan diberi nama secara spekulatif.
- **Tetap aman:** deploy hanya dari branch `v2.0-testing`, bukan `main`.

**Status:** seluruh 27 tes offline lulus. Integrasi nyata terhadap 28 shard di Streamlit Cloud belum dijalankan. Sebelum membuat GitHub Release publik, pastikan Anda memiliki izin mendistribusikan data batas desa tersebut.

---

## Dokumentasi aplikasi v2.0.1 sebelumnya (dasar pengembangan v2.1)

# 🔥 Indonesia Fire Watch v2.0.1 — Dukungan NAMOBJ

**Sistem pemantauan anomali termal satelit nasional berbasis NASA FIRMS, dari seluruh Indonesia hingga desa/kelurahan yang poligonnya tersedia.**

Versi ini merupakan pengembangan dari **Indonesia Fire Watch v1.0**, bukan pengganti kode **Kalimantan Fire Watch** yang terpisah. Versi v1 sudah berjalan pada GitHub `butarbutarernie/Indonesia-fire-watch1` sebelum pengembangan v2.

## Fitur nasional v2 dan pembaruan v2.0.1

- Dashboard Streamlit berbahasa Indonesia, header profesional, indikator, peta interaktif, dan tab ringkasan/peta/analisis/ekspor/metode.
- NASA FIRMS **VIIRS NOAA-20** dan **NOAA-21** NRT; periode **1, 2, 3, 5, 7 tanggal UTC**.
- **Batas Indonesia ADM0** untuk pembatasan nasional yang nyata (bukan hanya bounding box), **ADM1 geoBoundaries** untuk label provinsi.
- **Drill-down administrasi on demand:** Indonesia → provinsi → kabupaten/kota → kecamatan → desa/kelurahan; region dipotong menggunakan poligon wilayah yang dipilih melalui API Emsifa v2.
- Bila kecamatan dipilih, dapat mengaktifkan **Identifikasi seluruh desa pada kecamatan** (maksimum 50 desa) yang memproses setiap poligon desa tersedia. Titik ambigu/tidak teridentifikasi tetap ditandai dengan benar.
- Peta berwarna menurut confidence, pilihan **heatmap**, grafik deteksi menurut tanggal/kelas, peringkat provinsi atau desa, informasi sensor/FRP.
- Data FIRMS dapat diimpor lewat CSV; ekspor hasil terfilter ke CSV dan GeoJSON.
- Metadata kualitas ilmiah, batasan spasial, dan data provenance.
- **BARU v2.0.1:** pengguna dapat mengunggah **ZIP Shapefile** atau **GeoJSON** batas desa yang memiliki kolom `NAMOBJ`, lalu mencocokkan hotspot dengan desa/kelurahan memakai *spatial join* berdasarkan poligon nyata.
- **BARU v2.0.1:** pencarian/filter berdasarkan fitur NAMOBJ serta status eksplisit untuk lokasi di luar cakupan, nama kosong, atau batas desa yang tumpang tindih.

### Status ilmiah dan cakupan

Ini adalah **prototipe penelitian**, bukan sistem peringatan kebakaran resmi. Hotspot adalah anomali termal satelit, bukan kejadian kebakaran yang terkonfirmasi. Jumlah hotspot **bukan** luas area terbakar atau jumlah kejadian kebakaran independen. Satu sumber panas dapat terdeteksi dalam beberapa lintasan/sensor. Confidence VIIRS bukan probabilitas suatu desa terbakar.

Batas Emsifa bersumber dari data administratif pihak ketiga yang telah **disederhanakan untuk web**; **bukan batas desa definitif resmi BIG**. Beberapa wilayah tidak memiliki poligon. Titik pesisir/tepat di perbatasan, poligon tumpang tindih dan perbedaan versi antar-sumber menuntut verifikasi. Nama desa *tidak ditebak* dari centroid atau titik terdekat. Untuk publikasi atau kebutuhan hukum, lakukan perbandingan dengan geodatabase administrasi BIG/Kemendagri berizin dan versi bertanggal.

## Berkas di ZIP

```text
Indonesia_Fire_Watch_v2/
├── streamlit_app.py        # Dashboard dan seluruh widget aplikasi (GANTI v1)
├── firewatch_core.py       # Logika FIRMS/national clipping + periode 7 hari (GANTI v1)
├── admin_core.py           # Pencarian & pencocokan administrasi sampai desa
├── village_upload.py       # Baca ZIP Shapefile/GeoJSON + spatial join NAMOBJ (BARU)
├── requirements.txt        # Dependencies (GANTI v1)
├── README.md               # Dokumentasi (GANTI v1)
├── .gitignore              # Proteksi secrets
├── .streamlit/
│   └── config.toml         # Tema dashboard
└── tests/
    ├── test_firewatch_core.py
    ├── test_admin_core.py
    ├── test_firms_7day.py
    └── test_village_upload.py   # Pengujian field NAMOBJ, CRS, spasial, overlap dan ZIP
```

**`streamlit_app.py`, `firewatch_core.py`, `admin_core.py`, dan `village_upload.py` harus berada langsung di root repository yang sama.** Jangan unggah ZIP langsung, dan jangan membuat level subfolder `Indonesia_Fire_Watch_v2` di repository.

## Pembaruan GitHub yang aman (v1 tetap tersedia)

1. Buka: https://github.com/butarbutarernie/Indonesia-fire-watch1
2. **Branch `v2.0-testing` sudah dibuat oleh pengguna**. Jangan membuat branch lagi; pilih `v2.0-testing` sebelum mengunggah pembaruan. Branch `main` tetap mempertahankan v1.0.
3. Pastikan Anda sekarang berada di branch **`v2.0-testing`**.
4. Download ZIP dan lakukan **Extract All** di Windows.
5. Buka folder hasil ekstraksi, pilih **seluruh isi** (file dan folder di dalamnya), lalu di GitHub klik **Add file → Upload files**. *Upload file dengan nama sama dapat mengganti versi lama pada branch testing.*
6. Isi commit message **`Add NAMOBJ shapefile village lookup v2.0.1`**, lalu **Commit changes / Propose changes** pada branch `v2.0-testing`.
7. Pastikan file **`village_upload.py`** terlihat berdampingan dengan `admin_core.py`, `streamlit_app.py`, `firewatch_core.py`, dan `requirements.txt`.
8. Agar v1 tetap online, buat deployment Streamlit **kedua** (uji coba), pilih repository yang sama tetapi **branch `v2.0-testing`**, main file **`streamlit_app.py`** dan URL misalnya **`indonesia-fire-watch-v2-test`**. Nama URL bergantung ketersediaan.
9. Masukkan `FIRMS_MAP_KEY` ke **Secrets** pada deployment baru. **JANGAN** unggah key atau file `.streamlit/secrets.toml` ke GitHub.
10. Uji National → Provinsi → Kab/Kota → Kecamatan → Desa. Jika sudah stabil, gabungkan perubahan branch `v2.0-testing` ke `main` melalui Pull Request. Streamlit app utama akan mengambil versi baru pada branch `main`.

### Secrets pada Streamlit Cloud

Menu **Manage app → Settings → Secrets**:

```toml
FIRMS_MAP_KEY = "YOUR_REAL_PRIVATE_NASA_FIRMS_MAP_KEY"
```

Tidak perlu API key untuk daftar dan batas admin Emsifa. Untuk memeriksa API key NASA, buka https://firms.modaps.eosdis.nasa.gov/api/map_key/ .

## Menggunakan atribut `NAMOBJ` dari shapefile Anda (BARU v2.0.1)

**Harus ada file geospasial, bukan hanya nama kolom.** Kolom `NAMOBJ` hanyalah atribut nama; titik hotspot dapat diberi nama desa setelah tersedia geometri poligon yang sesuai. Hindari mengunggah data yang tidak boleh dibagikan ke repository publik.

**Siapkan berkas:**

- **Pilihan A:** ZIP yang memuat *satu* shapefile desa (`desa.shp`, `desa.shx`, `desa.dbf`, `desa.prj`; disarankan juga `desa.cpg` untuk nama non-ASCII). Penamaan dasar harus sama. `*.prj` wajib untuk memastikan CRS. Proyeksi seperti UTM dapat dikonversi otomatis ke WGS84 untuk spatial join.
- **Pilihan B:** GeoJSON FeatureCollection WGS84 (`*.geojson`) dengan properti `NAMOBJ`.
- Nama desa/kelurahan diambil dari `NAMOBJ` (tidak sensitif huruf besar/kecil); jika ada `KDEPUM`, digunakan sebagai kode sumber tanpa mengarang nilai yang hilang.
- Batasi unggahan maksimal **60 MB** dan **12.000 fitur**. Direkomendasikan satu kabupaten/kecamatan agar cepat.

**Langkah di Streamlit:**

1. Buka **aplikasi percobaan v2.0.1**, bukan v1.0. Tampilan awal berbahasa Indonesia dan memuat badge `V2.0.1` pada header.
2. Pilih provinsi/kabupaten/kecamatan jika ingin membatasi analisis agar lebih cepat.
3. Pada sidebar, cari **`Batas desa dari shapefile Anda`** lalu klik **Unggah ZIP Shapefile atau GeoJSON desa (NAMOBJ)**.
4. Setelah sukses akan muncul jumlah poligon dan CRS sumber. Gunakan **Cari nama desa pada file** dan **Filter berdasarkan poligon NAMOBJ** jika ingin menganalisis satu desa.
5. Klik titik hotspot. Popup berisi **Desa** jika titik berada tepat di satu poligon bernama; tabel unduhan berisi `desa`, `kode_desa`, dan `desa_status`.
6. Titik pada lebih dari satu poligon diberi status **Ambigu**, bukan diberi satu nama secara asal. Titik di luar cakupan tidak mendapat nama desa.

**Keterbatasan penting:** unggahan dilakukan **per sesi pengguna Streamlit**. Data ZIP atau GeoJSON yang diunggah *tidak otomatis tersimpan di GitHub* dan tidak otomatis tersedia bagi semua pengunjung. Untuk pemantauan nasional otomatis sampai desa tanpa unggah ulang perlu pipeline geodata nasional yang dilisensikan serta database spasial tersendiri. Sumber dan tanggal batas administrasi perlu diverifikasi bila akan digunakan untuk laporan penelitian.

## Langkah uji fungsional setelah deployment

1. **Nasional:** NOAA-20 + NOAA-21, High + Nominal, periode 3 hari. Cocokkan angka akuisisi dan interpretasi dengan v1, **tidak harus identik** karena waktu/jendela data berbeda.
2. **Provinsi:** pilih provinsi (misalnya Sumatera Selatan) dan perhatikan peta zoom dan jumlah setelah filter wilayah.
3. **Kabupaten/kota:** pilih kab/kota dalam provinsi tersebut.
4. **Kecamatan:** pilih satu kecamatan.
5. **Desa:** pilih salah satu desa berstatus `has_path=true`; hotspot berkurang sesuai poligon (nol pun valid sebagai hasil tidak terdeteksi pada data tersebut).
6. **Analisis seluruh desa pada kecamatan:** kosongkan filter desa; centang opsi penghitungan desa (kecamatan dengan <=50 desa). Periksa jumlah cocok, ambigu, gagal, dan tidak cocok.
7. **Peta:** ubah Titik → Kepadatan; catatan apabila jumlah titik dipetakan dibatasi sampling.
8. **Unduh:** cocokkan jumlah baris CSV dengan `Deteksi terfilter` dan periksa field `desa_status`.
9. **Periode 7 hari:** pastikan tidak ada error API. NASA dibagi 2 + 5 tanggal sehingga tidak pernah meminta 7 hari dalam satu request.
10. Jika admin Emsifa gagal, aplikasi **masih menampilkan nasional**. Jika batas nasional geoBoundaries gagal, aplikasi **tidak** menghasilkan angka nasional palsu.

## Arsitektur dan sumber data

| Sumber | Penggunaan | Catatan penting |
|---|---|---|
| NASA FIRMS Area API | Data VIIRS NOAA-20/21 NRT | 1–5 hari per request, dikelola 2+5 untuk 7 hari |
| geoBoundaries `gbOpen/IDN/ADM0`, `ADM1` | Pembatasan nasional dan nama provinsi | Tahun/metadata dari API ditampilkan |
| Emsifa Wilayah Indonesia API v2 | Daftar wilayah dan poligon level provinsi–desa | Polygon disederhanakan, on-demand dan tidak selalu lengkap |
| Carto basemap | Peta dasar | Sumber online eksternal |

- NASA FIRMS Area API: https://firms.modaps.eosdis.nasa.gov/api/area/
- geoBoundaries: https://www.geoboundaries.org/api.html
- Emsifa v2: https://github.com/emsifa/api-wilayah-indonesia
- Salah satu sumber geodatabase resmi untuk perbandingan ilmiah: https://geoportal.pertanian.go.id/arcgis/rest/services/Hosted/Batas_Administrasi_Desa/FeatureServer/layers

## Instalasi dan pengujian lokal (opsional)

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest -q tests
streamlit run streamlit_app.py
```

**Verifikasi pengembangan:** 22 pengujian offline sintetis lulus, termasuk parsing FIRMS, kode administrasi, koordinat lat/lon, spatial clipping, desa ambigu, dan pemecahan periode 7 hari. Integrasi live NASA/geoBoundaries/Emsifa dan Streamlit Cloud **harus diuji setelah deployment**; tidak ada klaim pengujian jaringan live dari lingkungan pembuat kode.

## Rencana tahap berikutnya

1. Mengganti poligon detail yang disederhanakan dengan data batas BIG sesuai versi/izin untuk penelitian terverifikasi.
2. Overlay ESA WorldCover / gambut dengan metode rendering tile agar tidak membebani browser nasional.
3. Pengujian sensor-time harmonisation, kualitas deteksi, monitoring performa, dan reporting otomatis.
