# KostCycle

Platform jual dan berbagi barang antarpenghuni kos. Barang lama, cerita baru.

**Pemilik proyek:** Stella Florencia Doulim · NIU 542739  
**Jalur:** Track B (EC2 + Docker + ECR), dengan RDS MySQL sebagai penyimpanan.

## Fitur

- Katalog barang gratis/dijual; pencarian, kategori, kondisi, urutan harga.
- Akun, autentikasi sesi, kata sandi di-hash, otorisasi pemilik dan proteksi CSRF.
- CRUD barang, dengan validasi harga gratis/dijual.
- Reservasi, pembatalan, dan konfirmasi pengambilan oleh pemilik.
- Pencegahan reservasi ganda memakai transaksi dan unique active_item_id.
- Halaman Barang Saya dan Reservasi; data contoh untuk demonstrasi.
- Tampilan responsif; ilustrasi SVG kategori (bukan foto barang asli).

## Dua layanan

| Layanan | Tanggung jawab | Akses |
|---|---|---|
| catalog | UI, akun, CRUD barang, proxy ke reservation | Port publik aplikasi |
| reservation | Reservasi dan transaksi status barang | Jaringan internal Docker, tanpa published port |

Kedua layanan dibangun dari source/image dasar yang sama, dipilih dengan `SERVICE`. Image dapat diberi tag dan disimpan pada dua repository ECR. Keduanya menggunakan satu database MySQL **bersama** untuk menjaga transaksi barang/reservasi atomik pada skala tugas. Ini merupakan tradeoff: layanan belum independen pada tingkat data, bukan pola database-per-service. Pemisahan database dan saga menjadi pengembangan berikutnya.

## Menjalankan lokal tanpa Docker

Python 3.12 diperlukan. Dari direktori proyek:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_local.py
```

Buka http://127.0.0.1:8001. Dua proses berjalan di port 8001 (catalog) dan 8002 (reservation). SQLite lokal digunakan hanya untuk pengembangan/pengujian. Tekan Ctrl+C untuk menghentikan keduanya.

Data contoh lokal dibuat jika `SEED_DEMO=1` (default mode lokal). Akun Alya dan Bima tersedia melalui tombol akun demo. Email: `alya@demo.kostcycle` / `bima@demo.kostcycle`, kata sandi contoh: `KostCycleDemo!`. Jangan gunakan kredensial contoh atau data pribadi untuk deployment produksi.

## Pengujian

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check app/static/app.js
```

Pengujian mencakup CRUD, otorisasi, CSRF, validasi, reservasi sendiri/ganda, pembatalan, penyelesaian, riwayat, dan persaingan dua pemesan. Pengujian SQLite tidak menggantikan verifikasi koneksi dan transaksi MySQL di AWS.

## Docker dan MySQL/RDS

1. Salin `.env.example` ke `.env` dan isi endpoint MySQL, akun database khusus aplikasi, serta dua secret acak.
2. Buat database `kostcycle` di RDS yang diizinkan lab; jangan mengubah database latihan `COFFEE`.
3. Jalankan `docker compose up -d --build`.
4. Periksa `docker compose ps` dan `/health`; hasil harus menyebut `mysql` pada AWS.

`compose.yaml` mempublikasikan catalog pada port 80. Jika server sudah memiliki aplikasi di port 80, gunakan override port atau perintah `docker run` pada port berbeda; jangan menghentikan aplikasi yang tidak dimiliki proyek.

Gunakan akun DB khusus dengan hak hanya pada `kostcycle.*`. `.env`, kunci SSH, token AWS, dan password tidak boleh masuk Git/ECR. Container berjalan sebagai user non-root. Untuk produksi, aktifkan HTTPS, `COOKIE_SECURE=1`, nonaktifkan seed demo, gunakan pengelolaan secret dan pembatasan percobaan login. Demo lab HTTP hanya untuk data contoh.

### Deployment lab dari ECR

Pada EC2 Linux dengan Docker, konfigurasi `.env` serta kredensial AWS **sementara** dari lab. Gunakan IAM role yang sesuai jika tersedia; jangan memasang role EMR untuk aplikasi ini. Pada sesi lab yang diperiksa, EC2 tidak memiliki instance profile dan `LabRole` tidak ditemukan, sehingga push/pull dilakukan operator melalui sesi `voclabs` sementara.

```bash
bash scripts/publish-images.sh v3  # Gunakan versi baru; tag ECR immutable.
bash scripts/deploy-ecr.sh v3
```

Script deployment menjalankan catalog di port **8080**, reservation hanya di jaringan Docker, dan menyimpan container sebelumnya dalam keadaan berhenti untuk rollback. Script membersihkan token login Docker setelah selesai. Perubahan security group untuk akses demo dilakukan terpisah; RDS tetap private. Mode Compose tetap tersedia untuk lingkungan yang memiliki Docker Compose.

## API

| Metode | Endpoint | Akses |
|---|---|---|
| GET | `/health` | Status layanan/database |
| GET | `/api/stats` | Statistik katalog |
| GET | `/api/barang` | Publik; filter q/category/offer_type/status/sort |
| GET | `/api/barang/{id}` | Publik |
| POST | `/api/barang` | Login + CSRF |
| PUT | `/api/barang/{id}` | Pemilik, status tersedia + CSRF |
| DELETE | `/api/barang/{id}` | Pemilik, tersedia, tanpa riwayat reservasi + CSRF |
| GET | `/api/auth/me` | Akun aktif dan CSRF token |
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/register` | Registrasi |
| POST | `/api/auth/logout` | Login + CSRF |
| GET | `/api/reservasi` | Reservasi milik pengguna/untuk barang pengguna |
| POST | `/api/reservasi` | Login + CSRF; item_id, note |
| POST | `/api/reservasi/{id}/cancel` | Pemesan/pemilik + CSRF |
| POST | `/api/reservasi/{id}/complete` | Pemilik + CSRF |

Reservasi diteruskan catalog ke layanan reservation melalui HTTP internal dan token internal. Browser tidak mengakses port reservation secara langsung.

Contoh body barang:

```json
{"name":"Rak buku tiga tingkat","description":"Kokoh, ada bekas pemakaian ringan.","category":"Furnitur","condition":"Baik","offer_type":"sale","price":75000,"location":"Pogung, Sleman"}
```

## Lingkup Week 12

Desain dua layanan, satu entitas CRUD utama (`barang`), Docker image, EC2, ECR, koneksi database, dan README. Fitur reservasi menjadi demonstrasi tambahan. Laporan akhir dibuat setelah implementasi AWS terverifikasi. Belum ada payment gateway, chat, unggah foto, pengiriman, atau transaksi uang nyata.

## Arsitektur implementasi

```mermaid
flowchart LR
  Laptop[Browser mahasiswa] -->|HTTP 8080, IP mahasiswa saja| Catalog
  Git[GitHub private] -->|source terkontrol| Build[Docker build di EC2]
  Build -->|push oleh sesi voclabs sementara| ECR[ECR private: dua repository]
  ECR -->|pull image| Catalog
  ECR -->|pull image| Reservation
  subgraph VPC[LabVPC us-east-1]
    subgraph EC2[EC2 yang sudah ada / public subnet]
      Catalog[catalog container]
      Reservation[reservation container]
      Catalog -->|HTTP internal + token internal| Reservation
    end
    Catalog -->|MySQL 3306| RDS[(RDS MySQL private / kostcycle)]
    Reservation -->|transaksi atomik| RDS
  end
```

Database `COFFEE` dan aplikasi latihan bawaan pada port 80 dipertahankan. KostCycle memakai database `kostcycle` dan port 8080. EC2 Cloud9 yang sudah berhenti tidak dijalankan untuk deployment ini. Link aplikasi menggunakan IP publik EC2; IP dan izin sumber perlu diperiksa lagi setelah sesi lab atau jaringan laptop berubah.

## Anggaran dan lab

Gunakan resource yang sudah ada jika cocok. Jangan membuat RDS/EC2 duplikat tanpa estimasi. Hindari ALB/NAT Gateway/ECS untuk deployment minimum ini. Budget terakhir yang diamati pada 24 November 2026: US$3,80 terpakai dari US$40; angka dapat terlambat diperbarui. Periksa kondisi aktual sebelum deployment dan akhiri sesi sesuai petunjuk lab setelah selesai. Penyimpanan tetap dapat menimbulkan biaya meskipun compute berhenti.

Referensi: [ECR push image](https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html), [ECR IAM](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html), [RDS biaya](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_OnDemandDBInstances.html).
