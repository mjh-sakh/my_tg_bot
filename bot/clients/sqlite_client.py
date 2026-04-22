import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[2] / 'data' / 'bot.sqlite'


class SQLiteClient:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                '''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS history (
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    canonical_message_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    reply_chat_id INTEGER,
                    reply_message_id INTEGER,
                    role TEXT NOT NULL,
                    is_llm_chain INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (chat_id, message_id)
                );

                CREATE TABLE IF NOT EXISTS user_features (
                    user_id INTEGER NOT NULL,
                    feature TEXT NOT NULL,
                    PRIMARY KEY (user_id, feature)
                );
                '''
            )
            self._migrate_history_table(connection)
            connection.execute(
                '''
                CREATE INDEX IF NOT EXISTS idx_history_chat_canonical_message_id
                ON history (chat_id, canonical_message_id)
                '''
            )

    def upsert_user(self, user_id: int, role: str) -> None:
        with self._connect() as connection:
            connection.execute(
                '''
                INSERT INTO users (user_id, role)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET role = excluded.role
                ''',
                (user_id, role),
            )

    def get_user_role(self, user_id: int) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT role FROM users WHERE user_id = ?',
                (user_id,),
            ).fetchone()
        return row['role'] if row else None

    def enable_feature(self, user_id: int, feature: str) -> None:
        with self._connect() as connection:
            connection.execute(
                '''
                INSERT OR IGNORE INTO user_features (user_id, feature)
                VALUES (?, ?)
                ''',
                (user_id, feature),
            )

    def disable_feature(self, user_id: int, feature: str) -> None:
        with self._connect() as connection:
            connection.execute(
                'DELETE FROM user_features WHERE user_id = ? AND feature = ?',
                (user_id, feature),
            )

    def has_feature(self, user_id: int, feature: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT 1 FROM user_features WHERE user_id = ? AND feature = ?',
                (user_id, feature),
            ).fetchone()
        return row is not None

    def list_features(self, user_id: int) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                '''
                SELECT feature
                FROM user_features
                WHERE user_id = ?
                ORDER BY feature
                ''',
                (user_id,),
            ).fetchall()
        return [row['feature'] for row in rows]

    def insert_history_record(self, **record: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                '''
                INSERT OR REPLACE INTO history (
                    chat_id,
                    message_id,
                    canonical_message_id,
                    text,
                    reply_chat_id,
                    reply_message_id,
                    role,
                    is_llm_chain,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    record['chat_id'],
                    record['message_id'],
                    record.get('canonical_message_id') or record['message_id'],
                    record['text'],
                    record.get('reply_chat_id'),
                    record.get('reply_message_id'),
                    getattr(record['role'], 'value', record['role']),
                    int(record.get('is_llm_chain', False)),
                    record.get('schema_version', 1),
                ),
            )

    def get_history_record(self, chat_id: int, message_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                '''
                SELECT
                    chat_id,
                    message_id,
                    canonical_message_id,
                    text,
                    reply_chat_id,
                    reply_message_id,
                    role,
                    is_llm_chain,
                    schema_version
                FROM history
                WHERE chat_id = ? AND message_id = ?
                ''',
                (chat_id, message_id),
            ).fetchone()
        return dict(row) if row else None

    def get_canonical_history_record(self, chat_id: int, message_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            canonical_row = connection.execute(
                '''
                SELECT canonical_message_id
                FROM history
                WHERE chat_id = ? AND message_id = ?
                ''',
                (chat_id, message_id),
            ).fetchone()
            if canonical_row is None:
                return None
            row = connection.execute(
                '''
                SELECT
                    chat_id,
                    message_id,
                    canonical_message_id,
                    text,
                    reply_chat_id,
                    reply_message_id,
                    role,
                    is_llm_chain,
                    schema_version
                FROM history
                WHERE chat_id = ? AND message_id = ?
                ''',
                (chat_id, canonical_row['canonical_message_id']),
            ).fetchone()
        return dict(row) if row else None

    def _migrate_history_table(self, connection: sqlite3.Connection) -> None:
        columns = {
            row['name']
            for row in connection.execute('PRAGMA table_info(history)').fetchall()
        }
        if 'canonical_message_id' not in columns:
            connection.execute(
                'ALTER TABLE history ADD COLUMN canonical_message_id INTEGER'
            )
        connection.execute(
            '''
            UPDATE history
            SET canonical_message_id = message_id
            WHERE canonical_message_id IS NULL
            '''
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection
