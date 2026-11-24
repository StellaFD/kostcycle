"""Initialize a dedicated KostCycle RDS once, using a temporary admin container.

Mount a private state directory at /state (db-admin-password required), and
optionally a KostCycle-only mysqldump at /run/backup.sql. Never run on the cafe DB.
"""
import json
import os
import secrets
from pathlib import Path

import pymysql
from pymysql.constants import CLIENT
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from app.models import Base
from app.seed import seed
from sqlalchemy.orm import sessionmaker

state = Path('/state')
host = os.environ['DB_HOST']
if not host.startswith('kostcycle-db.'):
    raise SystemExit('Expected a dedicated kostcycle-db RDS endpoint.')
if (state/'initialized').exists():
    raise SystemExit('Already initialized. Use the running database; do not import again.')
admin = (state/'db-admin-password').read_text().strip()
connection = pymysql.connect(host=host, user='kostcycleadmin', password=admin,
                             database='kostcycle', autocommit=True,
                             client_flag=CLIENT.MULTI_STATEMENTS)
with connection.cursor() as cursor:
    cursor.execute('SHOW TABLES')
    if cursor.fetchall():
        raise SystemExit('Target already has tables; inspect before importing data.')
    backup = Path('/run/backup.sql')
    if backup.exists():
        cursor.execute(backup.read_text())
        while cursor.nextset():
            pass
engine = create_engine(URL.create('mysql+pymysql', username='kostcycleadmin', password=admin,
                                  host=host, database='kostcycle'))
Base.metadata.create_all(engine)
if not backup.exists():
    seed(sessionmaker(engine, expire_on_commit=False))
engine.dispose()
app_password = secrets.token_hex(16)
with connection.cursor() as cursor:
    cursor.execute("CREATE USER 'kostcycle_app'@'%%' IDENTIFIED BY %s", (app_password,))
    cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON kostcycle.* TO 'kostcycle_app'@'%'")
    counts = {}
    for table in ('users', 'items', 'reservations'):
        cursor.execute(f'SELECT COUNT(*) FROM {table}')
        counts[table] = cursor.fetchone()[0]
connection.close()
environment = dict(DB_HOST=host, DB_USER='kostcycle_app', DB_PASSWORD=app_password,
    DB_PORT='3306', DB_NAME='kostcycle', SECRET_KEY=secrets.token_hex(32),
    INTERNAL_TOKEN=secrets.token_hex(32), SEED_DEMO='1', COOKIE_SECURE='0')
env_file = state/'app.env'
env_file.write_text(''.join(f'{key}={value}\n' for key,value in environment.items()))
env_file.chmod(0o600)
(state/'initialized').write_text(json.dumps(counts))
print(json.dumps({'initialized': True, 'row_counts': counts, 'runtime_ddl_permission': False}))
