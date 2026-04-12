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
                    text TEXT NOT NULL,
                    reply_chat_id INTEGER,
                    reply_message_id INTEGER,
                    role TEXT NOT NULL,
                    is_llm_chain INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (chat_id, message_id)
                );
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

    def insert_history_record(self, **record: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                '''
                INSERT OR REPLACE INTO history (
                    chat_id,
                    message_id,
                    text,
                    reply_chat_id,
                    reply_message_id,
                    role,
                    is_llm_chain,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    record['chat_id'],
                    record['message_id'],
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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection
