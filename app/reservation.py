from flask import jsonify, request, g
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from .models import User, Item, Reservation
from .common import create_base
from .service_auth import verify_identity

def create_app(config=None):
    app, Session, error, auth, body, string, serialize_item = create_base('reservation', config)
    @app.before_request
    def internal_only():
        if request.path in ('/health', '/live'):
            return None
        g.user_id = verify_identity(request.headers.get('X-Service-Identity', ''),
            request.method, request.path, request.get_json(silent=True))
        if not g.user_id:
            return error('Akses layanan internal ditolak.', 403)

    @app.get('/api/reservasi')
    @auth
    def reservations():
        with Session() as db:
            rows = db.execute(select(Reservation, Item, User).join(Item, Reservation.item_id == Item.id).join(User, Reservation.user_id == User.id)
                              .where((Reservation.user_id == g.user_id) | (Item.owner_id == g.user_id)).order_by(Reservation.id.desc())).all()
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
                changed = db.execute(update(Item).where(Item.id == item_id, Item.status == 'available', Item.owner_id != g.user_id).values(status='reserved'))
                if not changed.rowcount:
                    item = db.get(Item, item_id)
                    if not item:
                        return error('Barang tidak ditemukan.', 404)
                    return error('Kamu tidak dapat mereservasi barang sendiri.' if item.owner_id == g.user_id else 'Barang sudah tidak tersedia.', 409)
                reservation = Reservation(item_id=item_id, active_item_id=item_id, user_id=g.user_id, note=note.strip())
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
            if g.user_id not in [r.user_id, item.owner_id] or (action == 'complete' and g.user_id != item.owner_id):
                return error('Kamu tidak berhak melakukan aksi ini.', 403)
            # Every transition takes the item lock first, in the same order as reserve().
            changed = db.execute(update(Item).where(Item.id == item.id, Item.status == 'reserved').values(status='available' if action == 'cancel' else 'completed'))
            if not changed.rowcount:
                return error('Reservasi sudah diproses.', 409)
            changed = db.execute(update(Reservation).where(Reservation.id == r.id, Reservation.status == 'active').values(status='cancelled' if action == 'cancel' else 'completed', active_item_id=None))
            if not changed.rowcount:
                raise ValueError('Reservasi sudah diproses.')
        return jsonify(message='Reservasi dibatalkan.' if action == 'cancel' else 'Serah terima dikonfirmasi.')
    return app
