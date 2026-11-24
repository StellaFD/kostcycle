# Bukti AWS KostCycle

Pemeriksaan dan pengambilan screenshot: 25 November 2026, sekitar 01.38-01.43 WIB. Semua resource berada di AWS Academy Learner Lab, region us-east-1. Pengambilan screenshot hanya membaca status dan hasil tes tersimpan.

| Berkas | Bukti |
|---|---|
| [01-ec2-kostcycle.jpg](01-ec2-kostcycle.jpg) | EC2 KostCycleIDE running, t3.small, LabVPC |
| [02-docker-health.jpg](02-docker-health.jpg) | Dua container sehat, image v4, published port catalog, reservation internal, health MySQL |
| [03-rds-network.jpg](03-rds-network.jpg) | RDS available, MySQL, tidak publik; inbound 3306 hanya dari SG proyek |
| [04-ecr-iam.jpg](04-ecr-iam.jpg) | Dua image ECR v4 dengan digest berbeda, EC2 tanpa instance profile, sesi voclabs |
| [05-test-results.jpg](05-test-results.jpg) | Ringkasan 17 pemeriksaan HTTP MySQL dan uji gangguan yang tersimpan |

[Lampiran PDF](../Bukti_AWS_KostCycle.pdf) memuat kelima screenshot beserta keterangannya. [Outputs](outputs/) memuat metadata dan hasil tes yang dapat dibaca langsung. Tag kepemilikan dihilangkan dari salinan JSON; status resource dan hasil tes dipertahankan. Timestamp terminal menggunakan UTC, tujuh jam lebih lambat dari WIB.

Alamat base_url pada smoke-v4.json adalah alamat loopback container tempat tes dijalankan; port host catalog adalah 8080. Hasil outage menunjukkan kondisi saat reservation sengaja dihentikan pada pengujian sebelumnya. Screenshot Docker terbaru menunjukkan kedua layanan telah kembali sehat.

Demo dibatasi sesi AWS melalui preview Cloud9. Tidak ada port 8080 yang dibuka ke internet. RDS demo belum memakai enkripsi penyimpanan, backup otomatis, atau kewajiban TLS; data yang digunakan hanya contoh. Kredensial dan dump SQL tidak termasuk bukti.
