import os
import tempfile
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models  # garante que todos os modelos sejam registrados no Base.metadata


@pytest.fixture()
def db_session():
    """Banco SQLite isolado por teste, num arquivo temporário (não usa o
    atlas.db real) - criado do zero e descartado ao final de cada teste."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{caminho}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        os.remove(caminho)
