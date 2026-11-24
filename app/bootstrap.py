"""Initialize once before Gunicorn forks its workers."""
import os
from .models import Base, connect
from .seed import seed

engine, Session = connect()
Base.metadata.create_all(engine)
if os.getenv('SEED_DEMO', '1') == '1':
    seed(Session)
engine.dispose()
