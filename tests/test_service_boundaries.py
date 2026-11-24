import json
import logging
from unittest.mock import patch

import pytest
import requests
from sqlalchemy.exc import OperationalError

from test_workflows import apps, login, payload, headers
from app.service_auth import sign_identity


def test_reservation_has_no_catalog_routes_or_assets(apps):
    service = apps[1]
    paths = {rule.rule for rule in service.url_map.iter_rules()}
    assert '/api/barang' not in paths
    assert '/api/auth/login' not in paths
    assert '/' not in paths
    assert not any('static' in path for path in paths)


def test_browser_cookie_cannot_authenticate_internal_service(apps):
    client, _ = login(apps[0])
    internal = apps[1].test_client()
    internal.set_cookie('session', client.get_cookie('session').value)
    assert internal.get('/api/reservasi').status_code == 403


def test_internal_signature_rejects_body_path_method_and_identity_changes(apps):
    client = apps[1].test_client()
    token = sign_identity(1, 'POST', '/api/reservasi', {'item_id': 2})
    h = {'X-Service-Identity': token}
    assert client.post('/api/reservasi', json={'item_id': 3}, headers=h).status_code == 403
    assert client.get('/api/reservasi', headers=h).status_code == 403
    assert client.post('/api/reservasi/1/cancel', json={'item_id': 2}, headers=h).status_code == 403
    with patch('app.service_auth.signer') as factory:
        factory.return_value.loads.return_value = {'uid': True, 'method': 'GET', 'path': '/api/reservasi', 'body': 'wrong'}
        assert client.get('/api/reservasi', headers=h).status_code == 403
    assert client.get('/api/reservasi', headers={'X-Service-Identity': token+'tampered'}).status_code == 403


def test_expired_internal_identity_is_rejected(apps):
    from itsdangerous import TimestampSigner
    with patch.object(TimestampSigner, 'get_timestamp', return_value=100):
        token = sign_identity(1, 'GET', '/api/reservasi', None)
    with patch.object(TimestampSigner, 'get_timestamp', return_value=131):
        response = apps[1].test_client().get('/api/reservasi', headers={'X-Service-Identity': token})
    assert response.status_code == 403


def test_proxy_forwards_signed_identity_without_browser_credentials(apps, monkeypatch, caplog):
    catalog, reservation = apps
    client, csrf = login(catalog, 'bima')
    internal = reservation.test_client()
    observed = {}

    def transport(method, url, **kwargs):
        observed.update(kwargs)
        result = internal.open('/api/reservasi', method=method, json=kwargs['json'], headers=kwargs['headers'])
        observed['downstream_id'] = result.headers['X-Request-ID']
        return type('Response', (), {'content': result.data, 'status_code': result.status_code})()

    monkeypatch.setattr('app.catalog.requests.request', transport)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        response = client.get('/api/reservasi', headers={'X-Request-ID': 'demo-trace-123'})
    assert response.status_code == 200
    assert 'Cookie' not in observed['headers']
    assert 'X-CSRF-Token' not in observed['headers']
    assert observed['downstream_id'] == response.headers['X-Request-ID'] == 'demo-trace-123'
    assert observed['timeout'] == (2, 5)
    assert observed['allow_redirects'] is False
    logs = [json.loads(r.message) for r in caplog.records if r.message.startswith('{')]
    assert {r['service'] for r in logs} == {'catalog', 'reservation'}
    assert all(r['request_id'] == 'demo-trace-123' for r in logs)
    assert 'demo.kostcycle' not in caplog.text
    assert observed['headers']['X-Service-Identity'] not in caplog.text


def test_reservation_outage_keeps_catalog_crud_available(apps, monkeypatch):
    client, csrf = login(apps[0])
    def unavailable(*args, **kwargs):
        raise requests.ConnectTimeout('simulated reservation outage')
    monkeypatch.setattr('app.catalog.requests.request', unavailable)
    assert client.get('/api/reservasi').status_code == 503
    assert client.get('/api/barang').status_code == 200
    assert client.post('/api/barang', json=payload(), headers=headers(csrf)).status_code == 201
    assert client.get('/health').status_code == 200


def test_liveness_and_readiness_distinguish_database_outage(apps, monkeypatch):
    for service in apps:
        def unavailable():
            raise OperationalError('SELECT 1', {}, Exception('database unavailable'))
        monkeypatch.setattr(service.extensions['db_engine'], 'connect', unavailable)
        client = service.test_client()
        assert client.get('/live').status_code == 200
        assert client.get('/health').status_code == 503


def test_request_id_is_bounded_and_error_responses_are_traced(apps):
    client = apps[0].test_client()
    response = client.post('/api/barang', headers={'X-Request-ID': 'a'*1000})
    assert response.status_code == 401
    assert len(response.headers['X-Request-ID']) == 32


def test_mutation_proxy_checks_csrf_before_calling_internal_service(apps, monkeypatch):
    client, _ = login(apps[0])
    with patch('app.catalog.requests.request') as transport:
        response = client.post('/api/reservasi', json={'item_id': 2})
    assert response.status_code == 403
    transport.assert_not_called()
