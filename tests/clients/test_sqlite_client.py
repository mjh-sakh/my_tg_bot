import sqlite3

from bot.clients.sqlite_client import SQLiteClient


def test_init_db_creates_parent_directory_and_tables(tmp_path):
    db_path = tmp_path / 'nested' / 'bot.sqlite'

    client = SQLiteClient(db_path)
    client.init_db()

    assert db_path.exists()

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert 'users' in tables
    assert 'history' in tables


def test_get_user_role_returns_none_for_unknown_user(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()

    assert client.get_user_role(123) is None


def test_upsert_user_inserts_new_user_role(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()

    client.upsert_user(123, 'user')

    assert client.get_user_role(123) == 'user'


def test_upsert_user_updates_existing_user_role(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()

    client.upsert_user(123, 'user')
    client.upsert_user(123, 'admin')

    assert client.get_user_role(123) == 'admin'


def test_get_user_role_returns_stored_role(tmp_path):
    db_path = tmp_path / 'bot.sqlite'
    client = SQLiteClient(db_path)
    client.init_db()

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            'INSERT INTO users (user_id, role) VALUES (?, ?)',
            (123, 'user'),
        )
        connection.commit()

    assert client.get_user_role(123) == 'user'


def test_insert_and_get_history_record_round_trip(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()

    client.insert_history_record(
        chat_id=55,
        message_id=89,
        text='hello',
        reply_chat_id=55,
        reply_message_id=88,
        role='user',
        is_llm_chain=True,
        schema_version=1,
    )

    record = client.get_history_record(55, 89)

    assert record == {
        'chat_id': 55,
        'message_id': 89,
        'text': 'hello',
        'reply_chat_id': 55,
        'reply_message_id': 88,
        'role': 'user',
        'is_llm_chain': 1,
        'schema_version': 1,
    }
