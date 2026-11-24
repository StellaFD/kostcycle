"""Run against a deployed demo, creating only clearly labelled test records."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
import requests

BASE = os.getenv('KOSTCYCLE_URL', 'http://127.0.0.1:8080')
checks = []

def expect(response, status, name):
    assert response.status_code == status, (name, response.status_code, response.text[:250])
    checks.append({'check': name, 'status': status, 'passed': True})
    return response.json()

def login(who):
    client = requests.Session()
    data = expect(client.post(BASE+'/api/auth/login', json={'email':who+'@demo.kostcycle','password':'KostCycleDemo!'}, timeout=10), 200, 'login_'+who)
    client.headers['X-CSRF-Token'] = data['csrf_token']
    return client

health = expect(requests.get(BASE+'/health', timeout=10), 200, 'catalog_health')
assert health['database'] == 'mysql', health
seller, buyer = login('alya'), login('bima')
data = {'name':'[UJI] Rak KostCycle','description':'Data pengujian koneksi AWS. Bukan penawaran nyata.',
        'category':'Furnitur','condition':'Baik','offer_type':'free','price':0,'location':'Area demo'}
created = expect(seller.post(BASE+'/api/barang', json=data, timeout=10), 201, 'create_item')
item_id = created['item']['id']
expect(buyer.put(BASE+f'/api/barang/{item_id}', json=data, timeout=10), 403, 'reject_other_owner_edit')
data['name'] = '[UJI] Rak diperbarui'
expect(seller.put(BASE+f'/api/barang/{item_id}', json=data, timeout=10), 200, 'update_item')
expect(seller.get(BASE+f'/api/barang/{item_id}', timeout=10), 200, 'read_item')
expect(seller.delete(BASE+f'/api/barang/{item_id}', timeout=10), 200, 'delete_unreserved_item')
expect(seller.get(BASE+f'/api/barang/{item_id}', timeout=10), 404, 'deleted_item_missing')
# Keep a completed, labelled reservation as demonstration evidence.
item_id = expect(seller.post(BASE+'/api/barang', json=data, timeout=10), 201, 'create_reservation_test_item')['item']['id']
def reserve(_):
    return buyer.post(BASE+'/api/reservasi', json={'item_id':item_id,'note':'Pengujian transaksi MySQL di AWS.'}, timeout=20)
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(reserve, [1,2]))
assert sorted(r.status_code for r in results) == [201,409], [(r.status_code,r.text) for r in results]
checks.append({'check':'concurrent_reservation_one_winner_mysql','passed':True})
rid = next(r.json()['reservation']['id'] for r in results if r.status_code == 201)
expect(buyer.post(BASE+f'/api/reservasi/{rid}/complete', json={}, timeout=10), 403, 'buyer_cannot_complete')
expect(buyer.post(BASE+f'/api/reservasi/{rid}/cancel', json={}, timeout=10), 200, 'cancel_reservation')
rid = expect(buyer.post(BASE+'/api/reservasi', json={'item_id':item_id}, timeout=10), 201, 'reserve_again')['reservation']['id']
expect(seller.post(BASE+f'/api/reservasi/{rid}/complete', json={}, timeout=10), 200, 'owner_completes_handover')
result = expect(seller.get(BASE+f'/api/barang/{item_id}', timeout=10), 200, 'read_completed_item')
assert result['item']['status'] == 'completed'
expect(buyer.post(BASE+'/api/reservasi', json={'item_id':item_id}, timeout=10), 409, 'completed_item_cannot_be_reserved')
print(json.dumps({'base_url':BASE,'database':health['database'],'passed':len(checks),'checks':checks},indent=2))
