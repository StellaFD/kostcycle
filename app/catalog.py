import os
import secrets
import requests
from flask import jsonify, request, session, send_from_directory, g
from sqlalchemy import select, update, delete, func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from .models import User, Item, Reservation
from .common import create_base, CATEGORIES, CONDITIONS
from .service_auth import sign_identity

def create_app(config=None):
    app, Session, error, auth, body, string, serialize_item = create_base('catalog', config)
    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.get('/api/auth/me')
    def me():
        session.setdefault('csrf', secrets.token_hex(24))
        with Session() as db:
            user = db.get(User, session.get('uid')) if session.get('uid') else None
            return jsonify(user=dict(id=user.id, name=user.name, email=user.email) if user else None,
                           csrf_token=session['csrf'], demo=os.getenv('SEED_DEMO', '1') == '1')

    @app.post('/api/auth/login')
    def login():
        data = body()
        email = string(data, 'email', 3, 120).lower()
        password = string(data, 'password', 1, 200)
        with Session() as db:
            user = db.scalar(select(User).where(User.email == email))
            if not user or not check_password_hash(user.password_hash, password):
                return error('Email atau kata sandi tidak cocok.', 401)
            session.clear()
            session.update(uid=user.id, csrf=secrets.token_hex(24))
            return jsonify(user=dict(id=user.id, name=user.name, email=user.email), csrf_token=session['csrf'])

    @app.post('/api/auth/register')
    def register():
        data = body()
        name, email, password = string(data, 'name', 2, 80), string(data, 'email', 5, 120).lower(), string(data, 'password', 10, 200)
        if '@' not in email or '.' not in email.rsplit('@', 1)[-1]:
            return error('Alamat email tidak valid.')
        try:
            with Session.begin() as db:
                user = User(name=name, email=email, password_hash=generate_password_hash(password))
                db.add(user)
                db.flush()
                result = dict(id=user.id, name=name, email=email)
        except IntegrityError:
            return error('Email sudah terdaftar.', 409)
        session.clear()
        session.update(uid=result['id'], csrf=secrets.token_hex(24))
        return jsonify(user=result, csrf_token=session['csrf']), 201

    @app.post('/api/auth/logout')
    @auth
    def logout():
        session.clear()
        return jsonify(message='Berhasil keluar.')

    @app.get('/api/barang')
    def list_items():
        with Session() as db:
            stmt = select(Item)
            q = request.args.get('q', '').strip()[:100]
            if q:
                stmt = stmt.where(Item.name.icontains(q, autoescape=True) | Item.description.icontains(q, autoescape=True))
            for param, column in [('category', Item.category), ('offer_type', Item.offer_type), ('status', Item.status)]:
                if request.args.get(param):
                    stmt = stmt.where(column == request.args[param])
            if request.args.get('mine') == '1':
                if not session.get('uid'):
                    return error('Silakan masuk terlebih dahulu.', 401)
                stmt = stmt.where(Item.owner_id == session['uid'])
            sort = request.args.get('sort', 'latest')
            stmt = stmt.order_by(Item.price.asc(), Item.id.desc()) if sort == 'price' else stmt.order_by(Item.id.desc())
            return jsonify(items=[serialize_item(i, db) for i in db.scalars(stmt.limit(200))])

    @app.get('/api/stats')
    def stats():
        with Session() as db:
            return jsonify(available=db.scalar(select(func.count()).select_from(Item).where(Item.status == 'available')),
                           free=db.scalar(select(func.count()).select_from(Item).where(Item.status == 'available', Item.offer_type == 'free')),
                           completed=db.scalar(select(func.count()).select_from(Reservation).where(Reservation.status == 'completed')))

    @app.get('/api/barang/<int:item_id>')
    def get_item(item_id):
        with Session() as db:
            item = db.get(Item, item_id)
            return jsonify(item=serialize_item(item, db)) if item else error('Barang tidak ditemukan.', 404)

    def item_data(data):
        result = {key: string(data, key, 1, limit) for key, limit in [('name', 100), ('description', 1500), ('location', 100), ('category', 30), ('condition', 30), ('offer_type', 10)]}
        if result['category'] not in CATEGORIES or result['condition'] not in CONDITIONS or result['offer_type'] not in ['free', 'sale']:
            raise ValueError('Kategori, kondisi, atau jenis penawaran tidak valid.')
        price = data.get('price', 0)
        if isinstance(price, bool) or not isinstance(price, int) or price < 0 or price > 100000000:
            raise ValueError('Harga harus bilangan bulat antara 0 dan 100.000.000.')
        if result['offer_type'] == 'sale' and price == 0:
            raise ValueError('Barang dijual harus memiliki harga lebih dari nol.')
        if result['offer_type'] == 'free' and price != 0:
            raise ValueError('Barang gratis harus memiliki harga nol.')
        result['price'] = price
        return result

    @app.post('/api/barang')
    @auth
    def create_item():
        data = item_data(body())
        with Session.begin() as db:
            item = Item(owner_id=session['uid'], **data)
            db.add(item)
            db.flush()
            result = serialize_item(item, db)
        return jsonify(item=result), 201

    @app.put('/api/barang/<int:item_id>')
    @auth
    def edit_item(item_id):
        data = item_data(body())
        with Session.begin() as db:
            result = db.execute(update(Item).where(Item.id == item_id, Item.owner_id == session['uid'], Item.status == 'available').values(**data))
            if not result.rowcount:
                item = db.get(Item, item_id)
                return error('Barang tidak ditemukan.', 404) if not item else error('Hanya pemilik dapat mengubah barang yang masih tersedia.', 409 if item.owner_id == session['uid'] else 403)
            item = db.get(Item, item_id)
            response = serialize_item(item, db)
        return jsonify(item=response)

    @app.delete('/api/barang/<int:item_id>')
    @auth
    def remove_item(item_id):
        try:
            with Session.begin() as db:
                result = db.execute(delete(Item).where(Item.id == item_id, Item.owner_id == session['uid'], Item.status == 'available'))
                if not result.rowcount:
                    item = db.get(Item, item_id)
                    return error('Barang tidak ditemukan.', 404) if not item else error('Barang tidak dapat dihapus: bukan milikmu atau sedang/telah direservasi.', 409 if item.owner_id == session['uid'] else 403)
        except IntegrityError:
            return error('Barang memiliki riwayat reservasi sehingga tidak dapat dihapus.', 409)
        return jsonify(message='Barang berhasil dihapus.')

    @app.route('/api/reservasi', defaults={'path': ''}, methods=['GET', 'POST'])
    @app.route('/api/reservasi/<path:path>', methods=['POST'])
    @auth
    def reservation_proxy(path):
        base = os.getenv('RESERVATION_URL', 'http://127.0.0.1:8002').rstrip('/')
        try:
            target_path = '/api/reservasi' + ('/' + path if path else '')
            payload = request.get_json(silent=True) if request.method != 'GET' else None
            response = requests.request(request.method, f'{base}{target_path}', json=payload,
                headers={'X-Service-Identity': sign_identity(session['uid'], request.method, target_path, payload),
                         'X-Request-ID': g.request_id}, timeout=(2, 5), allow_redirects=False)
            return app.response_class(response.content, status=response.status_code, mimetype='application/json')
        except requests.RequestException:
            return error('Layanan reservasi belum tersedia. Coba lagi sebentar.', 503)

    return app
