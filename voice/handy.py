import sqlite3
from pathlib import Path

from config import HANDY_DB_PATH


class Handy:
    def __init__(self, db_path: str | Path | None = None, timeout: float = 1.5):
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            self.db_path = HANDY_DB_PATH

        self.timeout = timeout

        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Handy database not found:\n{self.db_path}"
            )

    def get_latest_transcription(self) -> dict | None:
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Handy database no longer exists at: {self.db_path}"
            )

        connection = None
        try:
            connection = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                timeout=self.timeout,
            )
            cursor = connection.cursor()
            cursor.execute("""
                SELECT id, transcription_text
                FROM transcription_history
                ORDER BY id DESC
                LIMIT 1
            """)
            result = cursor.fetchone()
        except sqlite3.Error as err:
            raise RuntimeError(
                f"SQLite error reading Handy database ({self.db_path}): {err}"
            ) from err
        finally:
            if connection is not None:
                connection.close()

        if result is None or len(result) < 2:
            return None

        raw_text = result[1] if isinstance(result[1], str) else str(result[1] or "")
        return {
            "id": result[0],
            "text": raw_text,
        }

    def get_transcriptions_since(self, last_id: int | None) -> list[dict]:
        """
        Return all transcriptions with id > last_id in ascending chronological order.
        If last_id is None, returns the single latest transcription (if any).
        """
        if last_id is None:
            latest = self.get_latest_transcription()
            return [latest] if latest is not None else []

        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Handy database no longer exists at: {self.db_path}"
            )

        connection = None
        try:
            connection = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                timeout=self.timeout,
            )
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT id, transcription_text
                FROM transcription_history
                WHERE id > ?
                ORDER BY id ASC
                """,
                (int(last_id),),
            )
            rows = cursor.fetchall()
        except sqlite3.Error as err:
            raise RuntimeError(
                f"SQLite error reading Handy database ({self.db_path}): {err}"
            ) from err
        finally:
            if connection is not None:
                connection.close()

        items: list[dict] = []
        for row in rows or []:
            if row is not None and len(row) >= 2:
                raw_text = row[1] if isinstance(row[1], str) else str(row[1] or "")
                items.append({"id": row[0], "text": raw_text})
        return items