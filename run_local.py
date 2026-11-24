"""Start both local services with a shared SQLite file; no AWS resources required."""
import os
import secrets
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
os.chdir(root)
env = os.environ.copy()
env.setdefault('SECRET_KEY', secrets.token_hex(32))
env.setdefault('INTERNAL_TOKEN', secrets.token_hex(32))
env.setdefault('DATABASE_URL', 'sqlite:///' + str(root / 'kostcycle.db'))
env.setdefault('SEED_DEMO', '1')
os.environ.update(env)
# Initialize once before the two processes start, avoiding startup seed races.
from app.main import create_app
app = create_app()
app.extensions['db_engine'].dispose()
env['SKIP_DB_INIT'] = '1'

children = []
try:
    for service, port in [('reservation', '8002'), ('catalog', '8001')]:
        child_env = {**env, 'SERVICE': service, 'PORT': port}
        children.append(subprocess.Popen([sys.executable, '-m', 'app.main'], env=child_env))
    print('KostCycle: http://127.0.0.1:8001', flush=True)
    print('Two services running. Press Ctrl+C to stop both.', flush=True)
    for child in children:
        child.wait()
except KeyboardInterrupt:
    pass
finally:
    for child in children:
        child.terminate()
    for child in children:
        child.wait()
