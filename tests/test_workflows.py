import importlib
import sys
from concurrent.futures import ThreadPoolExecutor
import pytest

@pytest.fixture
def apps(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'test.db'))
    monkeypatch.setenv('SECRET_KEY', 'test-session-secret-with-thirty-two-characters')
    monkeypatch.setenv('INTERNAL_TOKEN', 'test-internal-token')
    monkeypatch.setenv('SEED_DEMO', '1')
    from app.main import create_app
    catalog = create_app({'TESTING': True, 'SERVICE': 'catalog'})
    reservation = create_app({'TESTING': True, 'SERVICE': 'reservation'})
    yield catalog, reservation
    catalog.extensions['db_engine'].dispose()
    reservation.extensions['db_engine'].dispose()

def login(app, who='alya'):
    client = app.test_client()
    response = client.post('/api/auth/login', json={'email': f'{who}@demo.kostcycle', 'password': 'KostCycleDemo!'})
    assert response.status_code == 200
    return client, response.json['csrf_token']

def reservation_client(app, catalog_client):
    client = app.test_client()
    # The public service authenticates the browser. The internal service receives
    # a short-lived identity, never the browser's cookie or session signing key.
    from app.service_auth import sign_identity
    from urllib.parse import urlsplit
    with catalog_client.session_transaction() as browser_session:
        uid = browser_session['uid']
    original_open = client.open
    def signed_open(path, *args, **kwargs):
        method = kwargs.get('method', 'GET')
        request_headers = dict(kwargs.pop('headers', {}))
        request_headers['X-Service-Identity'] = sign_identity(uid, method, urlsplit(path).path, kwargs.get('json'))
        return original_open(path, *args, headers=request_headers, **kwargs)
    client.open = signed_open
    return client

def headers(token):
    return {'X-CSRF-Token': token, 'X-Internal-Token': 'test-internal-token'}

def payload(**changes):
    return {'name':'Rak test','description':'Rak tiga tingkat, kondisi baik.','category':'Furnitur',
            'condition':'Baik','offer_type':'sale','price':75000,'location':'Pogung, Sleman', **changes}

def test_catalog_crud_and_ownership(apps):
    catalog, _ = apps
    owner, token = login(catalog)
    other, other_token = login(catalog, 'bima')
    created = owner.post('/api/barang', json=payload(), headers=headers(token))
    assert created.status_code == 201
    item_id = created.json['item']['id']
    assert owner.get(f'/api/barang/{item_id}').json['item']['price'] == 75000
    assert other.put(f'/api/barang/{item_id}', json=payload(name='Diambil alih'), headers=headers(other_token)).status_code == 403
    edited = owner.put(f'/api/barang/{item_id}', json=payload(name='Rak diperbarui'), headers=headers(token))
    assert edited.json['item']['name'] == 'Rak diperbarui'
    assert owner.delete(f'/api/barang/{item_id}', headers=headers(token)).status_code == 200
    assert owner.get(f'/api/barang/{item_id}').status_code == 404

@pytest.mark.parametrize('changes', [{'offer_type':'free','price':100}, {'price':0}, {'price':-1}, {'price':True}, {'category':'unknown'}, {'name':''}, {'price':10.2}])
def test_validation(apps, changes):
    client, token = login(apps[0])
    assert client.post('/api/barang', json=payload(**changes), headers=headers(token)).status_code == 400

def test_auth_csrf_and_internal_boundary(apps):
    catalog, reservation = apps
    assert catalog.test_client().post('/api/barang', json=payload()).status_code == 401
    client, token = login(catalog)
    assert client.post('/api/barang', json=payload()).status_code == 403
    assert client.post('/api/barang', json=payload(), headers=headers('wrong')).status_code == 403
    assert reservation.test_client().get('/api/reservasi').status_code == 403
    assert catalog.test_client().post('/api/auth/login', json={'email':'alya@demo.kostcycle','password':'wrong'}).status_code == 401
    assert catalog.test_client().post('/api/auth/login', json=[]).status_code == 400

def test_reserve_cancel_complete_and_history(apps):
    catalog, service = apps
    seller, st = login(catalog)
    buyer, bt = login(catalog, 'bima')
    item_id = seller.post('/api/barang', json=payload(), headers=headers(st)).json['item']['id']
    r_seller, r_buyer = reservation_client(service, seller), reservation_client(service, buyer)
    assert r_seller.post('/api/reservasi', json={'item_id':item_id}, headers=headers(st)).status_code == 409
    reserved = r_buyer.post('/api/reservasi', json={'item_id':item_id}, headers=headers(bt))
    assert reserved.status_code == 201
    rid = reserved.json['reservation']['id']
    assert seller.get(f'/api/barang/{item_id}').json['item']['status'] == 'reserved'
    assert r_buyer.post('/api/reservasi', json={'item_id':item_id}, headers=headers(bt)).status_code == 409
    assert seller.put(f'/api/barang/{item_id}', json=payload(), headers=headers(st)).status_code == 409
    assert seller.delete(f'/api/barang/{item_id}', headers=headers(st)).status_code == 409
    assert r_buyer.post(f'/api/reservasi/{rid}/complete', headers=headers(bt)).status_code == 403
    assert r_buyer.post(f'/api/reservasi/{rid}/cancel', headers=headers(bt)).status_code == 200
    assert r_buyer.post(f'/api/reservasi/{rid}/cancel', headers=headers(bt)).status_code == 409
    assert seller.get(f'/api/barang/{item_id}').json['item']['status'] == 'available'
    assert seller.delete(f'/api/barang/{item_id}', headers=headers(st)).status_code == 409
    second = r_buyer.post('/api/reservasi', json={'item_id':item_id}, headers=headers(bt)).json['reservation']['id']
    assert r_seller.post(f'/api/reservasi/{second}/complete', headers=headers(st)).status_code == 200
    assert seller.get(f'/api/barang/{item_id}').json['item']['status'] == 'completed'
    assert len(r_seller.get('/api/reservasi', headers=headers(st)).json['reservations']) == 2

def test_concurrent_reservation_has_exactly_one_winner(apps):
    catalog, service = apps
    seller, st = login(catalog)
    buyer, bt = login(catalog, 'bima')
    third = catalog.test_client()
    registered = third.post('/api/auth/register', json={'name':'Citra Demo', 'email':'citra@demo.kostcycle', 'password':'DemoCitra123!'})
    ct = registered.json['csrf_token']
    item_id = seller.post('/api/barang', json=payload(), headers=headers(st)).json['item']['id']
    def reserve(args):
        user, token = args
        client = reservation_client(service, user)
        return client.post('/api/reservasi', json={'item_id':item_id}, headers=headers(token)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [(buyer, bt), (third, ct)]))
    assert sorted(results) == [201, 409]

def test_search_filters_and_literal_wildcards(apps):
    app = apps[0]
    client = app.test_client()
    assert len(client.get('/api/barang?offer_type=free&status=available').json['items']) == 3
    assert client.get('/api/barang?q=%25').json['items'] == []
    assert client.get('/api/barang?q=rak').json['items'][0]['category'] == 'Furnitur'
    assert client.get('/api/barang?mine=1').status_code == 401

def test_register_duplicate_and_invisible_other_reservations(apps):
    catalog, service = apps
    client = catalog.test_client()
    data = {'name':'Citra Demo','email':'citra@demo.kostcycle','password':'DemoCitra123!'}
    created = client.post('/api/auth/register', json=data)
    assert created.status_code == 201
    assert client.post('/api/auth/register', json=data).status_code == 409
    assert reservation_client(service, client).get('/api/reservasi', headers=headers(created.json['csrf_token'])).json['reservations'] == []

def test_health_and_security_headers(apps):
    for app in apps:
        response = app.test_client().get('/health')
        assert response.json['database'] == 'sqlite'
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert 'frame-ancestors' in response.headers['Content-Security-Policy']
