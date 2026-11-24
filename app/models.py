import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Integer, ForeignKey, Text, DateTime, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase):
    pass

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))

class Item(Base):
    __tablename__ = 'items'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    condition: Mapped[str] = mapped_column(String(30))
    offer_type: Mapped[str] = mapped_column(String(10))
    price: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default='available')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Reservation(Base):
    __tablename__ = 'reservations'
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey('items.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    # NULL for cancelled/completed rows; a unique non-NULL key blocks double booking.
    active_item_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='active')
    note: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

def connect():
    url = os.getenv('DATABASE_URL')
    if not url and os.getenv('DB_HOST'):
        url = URL.create('mysql+pymysql', username=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
                         host=os.environ['DB_HOST'], port=int(os.getenv('DB_PORT', '3306')),
                         database=os.getenv('DB_NAME', 'kostcycle'), query={'charset': 'utf8mb4'})
    url = url or 'sqlite:///kostcycle.db'
    engine = create_engine(url, pool_pre_ping=True, connect_args={'timeout': 15} if str(url).startswith('sqlite') else {})
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def sqlite_setup(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA journal_mode=WAL')
    return engine, sessionmaker(engine, expire_on_commit=False)
