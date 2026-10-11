import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR / "db"))


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    """seed.py 로 테스트 전용 샘플 DB를 만들어 연결한다. (db/members.db 는 건드리지 않음)"""
    import seed
    from chain import init_database

    path = tmp_path_factory.mktemp("db") / "members.db"
    seed.build_db(path, count=200, seed=42)
    return init_database(f"sqlite:///{path}")
