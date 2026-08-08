from __future__ import annotations

from app.postgres_compat import PostgresConnection, translate_sql


class _Cursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[object, ...]]]] = []
        self.rowcount = 0

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def executemany(self, sql: str, rows: list[tuple[object, ...]]) -> None:
        self.calls.append((sql, rows))
        self.rowcount = len(rows)


class _Connection:
    def __init__(self) -> None:
        self.cursor_instance = _Cursor()
        self.cursor_calls = 0

    def cursor(self) -> _Cursor:
        self.cursor_calls += 1
        return self.cursor_instance


def test_postgres_executemany_uses_cursor_and_translates_placeholders() -> None:
    wrapper = PostgresConnection(pool=None)
    connection = _Connection()
    wrapper.connection = connection

    rowcount = wrapper.executemany(
        "INSERT INTO prices(symbol, close) VALUES (?, ?)",
        (("000063.SZ", 35.0), ("NVDA", 173.6)),
    )

    assert rowcount == 2
    assert connection.cursor_calls == 1
    assert connection.cursor_instance.calls == [
        (
            "INSERT INTO prices(symbol, close) VALUES (%s, %s)",
            [("000063.SZ", 35.0), ("NVDA", 173.6)],
        )
    ]


def test_postgres_executemany_skips_empty_batch_without_opening_cursor() -> None:
    wrapper = PostgresConnection(pool=None)
    connection = _Connection()
    wrapper.connection = connection

    assert wrapper.executemany("INSERT INTO prices VALUES (?)", []) is None
    assert connection.cursor_calls == 0


def test_postgres_translation_preserves_explicit_conflict_semantics() -> None:
    translated = translate_sql(
        """
        INSERT INTO news_items(id, symbol, source, url) VALUES (?, ?, ?, ?)
        ON CONFLICT DO UPDATE SET source = excluded.source
        """
    )

    assert "ON CONFLICT DO UPDATE" in translated
    assert "ON CONFLICT(id)" not in translated


def test_sqlite_real_schema_is_promoted_to_postgres_double_precision() -> None:
    translated = translate_sql(
        "CREATE TABLE prices (id INTEGER PRIMARY KEY, price REAL, ratio REAL)"
    )

    assert "id BIGINT PRIMARY KEY" in translated
    assert "price DOUBLE PRECISION" in translated
    assert "ratio DOUBLE PRECISION" in translated
    assert " REAL" not in translated
