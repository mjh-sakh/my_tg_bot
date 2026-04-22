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
    assert 'user_features' in tables


def test_init_db_adds_canonical_history_index(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()

    with sqlite3.connect(client.db_path) as connection:
        indexes = {
            row[1]
            for row in connection.execute('PRAGMA index_list(history)').fetchall()
        }

    assert 'idx_history_chat_canonical_message_id' in indexes


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


def test_enable_and_has_feature_round_trip(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()

    client.enable_feature(123, 'voice')

    assert client.has_feature(123, 'voice') is True
    assert client.has_feature(123, 'chat') is False


def test_disable_feature_removes_enabled_feature(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    client.enable_feature(123, 'voice')

    client.disable_feature(123, 'voice')

    assert client.has_feature(123, 'voice') is False


def test_list_features_returns_sorted_features(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    client.enable_feature(123, 'voice')
    client.enable_feature(123, 'chat')

    assert client.list_features(123) == ['chat', 'voice']


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
        'canonical_message_id': 89,
        'text': 'hello',
        'reply_chat_id': 55,
        'reply_message_id': 88,
        'role': 'user',
        'is_llm_chain': 1,
        'schema_version': 1,
    }


def test_insert_and_get_alias_history_record_round_trip(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()

    client.insert_history_record(
        chat_id=55,
        message_id=90,
        canonical_message_id=89,
        text='transcript alias',
        reply_chat_id=55,
        reply_message_id=89,
        role='user',
        is_llm_chain=False,
        schema_version=1,
    )

    record = client.get_history_record(55, 90)

    assert record == {
        'chat_id': 55,
        'message_id': 90,
        'canonical_message_id': 89,
        'text': 'transcript alias',
        'reply_chat_id': 55,
        'reply_message_id': 89,
        'role': 'user',
        'is_llm_chain': 0,
        'schema_version': 1,
    }


def test_get_canonical_history_record_resolves_alias_to_canonical_row(tmp_path):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    client.insert_history_record(
        chat_id=55,
        message_id=89,
        text='canonical voice transcript',
        role='user',
        is_llm_chain=True,
    )
    client.insert_history_record(
        chat_id=55,
        message_id=90,
        canonical_message_id=89,
        text='visible transcript alias',
        role='user',
        is_llm_chain=False,
    )

    record = client.get_canonical_history_record(55, 90)

    assert record == {
        'chat_id': 55,
        'message_id': 89,
        'canonical_message_id': 89,
        'text': 'canonical voice transcript',
        'reply_chat_id': None,
        'reply_message_id': None,
        'role': 'user',
        'is_llm_chain': 1,
        'schema_version': 1,
    }


def test_init_db_migrates_existing_history_table_and_backfills_canonical_message_id(tmp_path):
    db_path = tmp_path / 'bot.sqlite'
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            '''
            CREATE TABLE history (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                reply_chat_id INTEGER,
                reply_message_id INTEGER,
                role TEXT NOT NULL,
                is_llm_chain INTEGER NOT NULL DEFAULT 0,
                schema_version INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (chat_id, message_id)
            );

            INSERT INTO history (
                chat_id,
                message_id,
                text,
                reply_chat_id,
                reply_message_id,
                role,
                is_llm_chain,
                schema_version
            ) VALUES (55, 89, 'old row', NULL, NULL, 'user', 1, 1);
            '''
        )

    client = SQLiteClient(db_path)
    client.init_db()

    record = client.get_history_record(55, 89)
    assert record is not None
    assert record['canonical_message_id'] == 89

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute('PRAGMA table_info(history)').fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute('PRAGMA index_list(history)').fetchall()
        }

    assert 'canonical_message_id' in columns
    assert 'idx_history_chat_canonical_message_id' in indexes
