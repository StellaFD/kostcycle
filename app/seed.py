from sqlalchemy import select
from werkzeug.security import generate_password_hash
from .models import User, Item

def seed(Session):
    with Session.begin() as db:
        if db.scalar(select(User.id).limit(1)):
            return
        users = [User(name='Alya Putri', email='alya@demo.kostcycle', password_hash=generate_password_hash('KostCycleDemo!')),
                 User(name='Bima Pratama', email='bima@demo.kostcycle', password_hash=generate_password_hash('KostCycleDemo!'))]
        db.add_all(users)
        db.flush()
        rows = [
            ('Meja belajar, siap menemani skripsimu', 'Meja kayu kokoh, ukuran 100 × 50 cm. Ada sedikit bekas pemakaian, semua kaki masih stabil. Ambil langsung, ya.', 'Furnitur', 'Baik', 'sale', 175000, 'Pogung, Sleman'),
            ('Rak buku untuk sudut kamar', 'Rak tiga tingkat, ringan dan mudah dibawa. Aku pindahan, semoga bisa dipakai lagi!', 'Furnitur', 'Baik', 'free', 0, 'Karangmalang, Sleman'),
            ('Lampu meja dengan cahaya hangat', 'Masih berfungsi normal, cocok untuk belajar malam. Bohlam sudah termasuk.', 'Elektronik', 'Seperti baru', 'sale', 65000, 'Seturan, Sleman'),
            ('Buku-buku teman semester awal', 'Paket buku catatan dan referensi umum. Gratis untuk yang membutuhkan.', 'Buku', 'Layak pakai', 'free', 0, 'Pogung, Sleman'),
            ('Rice cooker mini, teman anak kos', 'Kapasitas 0,6 liter, fungsi masak dan penghangat normal. Sudah dibersihkan.', 'Dapur', 'Baik', 'sale', 95000, 'Condongcatur, Sleman'),
            ('Monstera kecil mencari rumah baru', 'Tanaman sehat dengan potnya. Cukup cahaya tidak langsung dan siram secukupnya.', 'Lainnya', 'Baik', 'free', 0, 'Gejayan, Sleman'),
        ]
        for n, row in enumerate(rows):
            name, description, category, condition, offer, price, location = row
            db.add(Item(owner_id=users[n % 2].id, name=name, description=description, category=category,
                        condition=condition, offer_type=offer, price=price, location=location))
