"""Exercise two real HTTP servers locally, including a reservation outage."""
import os
import subprocess
import sys
import threading

import requests
from werkzeug.serving import make_server

from test_workflows import apps


def test_two_http_services_and_failure_isolation(apps, monkeypatch):
    catalog, reservation = apps
    servers = [make_server('127.0.0.1', 0, service, threaded=True) for service in (reservation, catalog)]
    monkeypatch.setenv('RESERVATION_URL', f'http://127.0.0.1:{servers[0].server_port}')
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    base = f'http://127.0.0.1:{servers[1].server_port}'
    try:
        # Reuse the deployment checks; this run is explicitly SQLite, not AWS evidence.
        env = {**os.environ, 'KOSTCYCLE_URL': base, 'EXPECTED_DATABASE': 'sqlite'}
        result = subprocess.run([sys.executable, 'tests/smoke_http.py'], env=env,
                                capture_output=True, text=True, timeout=40)
        assert result.returncode == 0, result.stdout + result.stderr
        assert '"passed": 17' in result.stdout
        servers[0].shutdown()
        servers[0].server_close()
        client = requests.Session()
        response = client.post(base+'/api/auth/login', json={
            'email': 'bima@demo.kostcycle', 'password': 'KostCycleDemo!'}, timeout=5)
        assert response.status_code == 200
        assert client.get(base+'/api/reservasi', timeout=8).status_code == 503
        assert client.get(base+'/api/barang', timeout=5).status_code == 200
    finally:
        for server, thread in zip(servers, threads):
            if thread.is_alive():
                server.shutdown()
            server.server_close()
            thread.join(timeout=5)
