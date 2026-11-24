import os
import secrets
from functools import wraps
import requests
from flask import Flask, jsonify, request, session, send_from_directory
from sqlalchemy import select, update, delete, text, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash
from .models import Base, User, Item, Reservation, connect
from .seed import seed

CATEGORIES = ['Furnitur', 'Elektronik', 'Dapur', 'Buku', 'Fashion', 'Lainnya']
CONDITIONS = ['Seperti baru', 'Baik', 'Layak pakai']

def create_app(config=None):
    app = Flask(__name__, static_folder='static')
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY') or secrets.token_hex(32),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE') == '1', MAX_CONTENT_LENGTH=16384)
    if config:
        app.config.update(config)
    service = app.config.get('SERVICE', os.getenv('SERVICE', 'catalog'))
    engine, Session = connect()
    if os.getenv('SKIP_DB_INIT') != '1':
        Base.metadata.create_all(engine)
        if os.getenv('SEED_DEMO', '1') == '1':
            seed(Session)
    app.extensions.update(db_engine=engine, db_session=Session)

    def error(message, status=400):
        return jsonify(error=message), status

    def auth(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get('uid'):
                return error('Silakan masuk terlebih dahulu.', 401)
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                token = request.headers.get('X-CSRF-Token', '')
                if not token or not secrets.compare_digest(token, session.get('csrf', '')):
                    return error('Sesi tidak valid. Muat ulang halaman.', 403)
            return fn(*args, **kwargs)
        return wrapper

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('Kirim data JSON yang valid.')
        return data

    def string(data, key, minimum=1, maximum=100):
        value = data.get(key)
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise ValueError(f'{key}: isi {minimum}–{maximum} karakter.')
        return value.strip()

    def serialize_item(item, db):
        owner = db.get(User, item.owner_id)
        return dict(id=item.id, name=item.name, description=item.description, category=item.category,
                    condition=item.condition, offer_type=item.offer_type, price=item.price, location=item.location,
                    status=item.status, owner_id=item.owner_id, owner=owner.name, created_at=item.created_at.isoformat())

    @app.errorhandler(ValueError)
    def invalid(exc):
        return error(str(exc))

    @app.errorhandler(413)
    def too_large(_):
        return error('Data terlalu besar.', 413)

    @app.errorhandler(SQLAlchemyError)
    def db_error(exc):
        app.logger.error('Database operation failed: %s', type(exc).__name__)
        return error('Database belum tersedia. Coba lagi sebentar.', 503)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/health')
    def health():
        with engine.connect() as db:
            db.execute(text('SELECT 1'))
        return jsonify(status='ok', service=service, database=engine.dialect.name)

    if service == 'catalog':
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
                response = requests.request(request.method, f'{base}/api/reservasi' + ('/' + path if path else ''),
                    json=request.get_json(silent=True) if request.method != 'GET' else None,
                    headers={'Cookie': request.headers.get('Cookie', ''), 'X-CSRF-Token': request.headers.get('X-CSRF-Token', ''),
                             'X-Internal-Token': os.getenv('INTERNAL_TOKEN', '')}, timeout=10)
                return app.response_class(response.content, status=response.status_code, mimetype='application/json')
            except requests.RequestException:
                return error('Layanan reservasi belum tersedia. Coba lagi sebentar.', 503)

    elif service == 'reservation':
        @app.before_request
        def internal_only():
            if request.path == '/health':
                return None
            expected = os.getenv('INTERNAL_TOKEN', '')
            if not expected or not secrets.compare_digest(request.headers.get('X-Internal-Token', ''), expected):
                return error('Akses layanan internal ditolak.', 403)

        @app.get('/api/reservasi')
        @auth
        def reservations():
            with Session() as db:
                rows = db.execute(select(Reservation, Item, User).join(Item, Reservation.item_id == Item.id).join(User, Reservation.user_id == User.id)
                                  .where((Reservation.user_id == session['uid']) | (Item.owner_id == session['uid'])).order_by(Reservation.id.desc())).all()
                return jsonify(reservations=[dict(id=r.id, item=serialize_item(i, db), user_id=r.user_id,
                    buyer=u.name, status=r.status, note=r.note, created_at=r.created_at.isoformat()) for r, i, u in rows])

        @app.post('/api/reservasi')
        @auth
        def reserve():
            data = body()
            item_id, note = data.get('item_id'), data.get('note', '')
            if isinstance(item_id, bool) or not isinstance(item_id, int) or not isinstance(note, str) or len(note) > 300:
                return error('Barang atau catatan reservasi tidak valid.')
            try:
                with Session.begin() as db:
                    # Conditional UPDATE locks the row on MySQL; only one transaction can claim it.
                    changed = db.execute(update(Item).where(Item.id == item_id, Item.status == 'available', Item.owner_id != session['uid']).values(status='reserved'))
                    if not changed.rowcount:
                        item = db.get(Item, item_id)
                        if not item:
                            return error('Barang tidak ditemukan.', 404)
                        return error('Kamu tidak dapat mereservasi barang sendiri.' if item.owner_id == session['uid'] else 'Barang sudah tidak tersedia.', 409)
                    reservation = Reservation(item_id=item_id, active_item_id=item_id, user_id=session['uid'], note=note.strip())
                    db.add(reservation)
                    db.flush()
                    result = dict(id=reservation.id, status='active')
            except IntegrityError:
                return error('Barang sudah direservasi pengguna lain.', 409)
            return jsonify(reservation=result), 201

        @app.post('/api/reservasi/<int:reservation_id>/<action>')
        @auth
        def transition(reservation_id, action):
            if action not in ['cancel', 'complete']:
                return error('Aksi tidak ditemukan.', 404)
            with Session.begin() as db:
                row = db.execute(select(Reservation, Item).join(Item, Reservation.item_id == Item.id).where(Reservation.id == reservation_id)).first()
                if not row:
                    return error('Reservasi tidak ditemukan.', 404)
                r, item = row
                if session['uid'] not in [r.user_id, item.owner_id] or (action == 'complete' and session['uid'] != item.owner_id):
                    return error('Kamu tidak berhak melakukan aksi ini.', 403)
                # Every transition takes the item lock first, in the same order as reserve().
                changed = db.execute(update(Item).where(Item.id == item.id, Item.status == 'reserved').values(status='available' if action == 'cancel' else 'completed'))
                if not changed.rowcount:
                    return error('Reservasi sudah diproses.', 409)
                changed = db.execute(update(Reservation).where(Reservation.id == r.id, Reservation.status == 'active').values(status='cancelled' if action == 'cancel' else 'completed', active_item_id=None))
                if not changed.rowcount:
                    raise ValueError('Reservasi sudah diproses.')
            return jsonify(message='Reservasi dibatalkan.' if action == 'cancel' else 'Serah terima dikonfirmasi.')
    else:
        raise RuntimeError('Unknown SERVICE')
    return app

app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '8001')), debug=False)
