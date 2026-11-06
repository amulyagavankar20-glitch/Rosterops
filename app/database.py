"""Database configuration for SQLite (local) or PostgreSQL (deployment)."""
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    db_path = Path(os.getenv('ROSTER_DB_PATH', str(BASE_DIR / 'data' / 'roster_management.db')))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{db_path.as_posix()}"

connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800, connect_args=connect_args)
if DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def _enable_sqlite_fk(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Safe additive compatibility migration for databases created by the original ZIP.
    # New tables are created above; this adds the one newly introduced employee column.
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "employees" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("employees")}
        if "daily_capacity" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE employees ADD COLUMN daily_capacity INTEGER DEFAULT 3"))
