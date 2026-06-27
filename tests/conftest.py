import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.clients import SQLiteClient


@pytest.fixture
def locker_sqlite_client(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    return client
