import os
import secrets
import json
import re
import time
import uuid
from functools import wraps
from flask import Flask, jsonify, request, session, g
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .models import Base, User, connect
from .seed import seed

CATEGORIES = ['Furnitur', 'Elektronik', 'Dapur', 'Buku', 'Fashion', 'Lainnya']
CONDITIONS = ['Seperti baru', 'Baik', 'Layak pakai']

def create_base(service, config=None):
    app = Flask(__name__, static_folder='static' if service == 'catalog' else None)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY') or secrets.token_hex(32),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE') == '1', MAX_CONTENT_LENGTH=16384)
    if config:
        app.config.update(config)
    app.logger.setLevel('INFO')
    if len(os.getenv('INTERNAL_TOKEN', '')) < 32 and not app.config.get('TESTING'):
        raise RuntimeError('INTERNAL_TOKEN must contain at least 32 characters')
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
            if service == 'reservation':
                if not getattr(g, 'user_id', None):
                    return error('Identitas layanan tidak valid.', 401)
                return fn(*args, **kwargs)
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

    @app.before_request
    def start_request():
        incoming = request.headers.get('X-Request-ID', '')
        g.request_id = incoming if re.fullmatch(r'[A-Za-z0-9-]{1,64}', incoming) else uuid.uuid4().hex
        g.started_at = time.monotonic()

    @app.get('/live')
    def live():
        return jsonify(status='ok', service=service)

    @app.after_request
    def headers(response):
        response.headers['X-Request-ID'] = g.request_id
        app.logger.info(json.dumps(dict(service=service, request_id=g.request_id,
            method=request.method, path=request.path, status=response.status_code,
            duration_ms=round((time.monotonic()-g.started_at)*1000, 2))))
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

    return app, Session, error, auth, body, string, serialize_item
