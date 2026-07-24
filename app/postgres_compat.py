from __future__ import annotations

import re
from typing import Any, Iterable


def _replace_placeholders(sql: str) -> str:
    output: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            output.append(char)
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"'}:
            quote = char
            output.append(char)
        elif char == "?":
            output.append("%s")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def translate_sql(sql: str) -> str:
    translated = _replace_placeholders(sql)
    if re.match(
        r"\s*(CREATE\s+TABLE|ALTER\s+TABLE)",
        translated,
        flags=re.IGNORECASE,
    ):
        translated = re.sub(
            r"\bINTEGER\b", "BIGINT", translated, flags=re.IGNORECASE
        )
    translated = re.sub(r"\browid\b", "ctid", translated, flags=re.IGNORECASE)
    translated = translated.replace(
        "MAX(evidence_tasks.priority, excluded.priority)",
        "GREATEST(evidence_tasks.priority, excluded.priority)",
    )
    if re.search(
        r"INSERT\s+INTO\s+news_items\b", translated, flags=re.IGNORECASE
    ):
        translated = re.sub(
            r"ON\s+CONFLICT\s+DO\s+UPDATE",
            "ON CONFLICT(symbol, source, url) DO UPDATE",
            translated,
            flags=re.IGNORECASE,
        )
    if re.search(
        r"INSERT\s+OR\s+IGNORE\s+INTO", translated, flags=re.IGNORECASE
    ):
        translated = re.sub(
            r"INSERT\s+OR\s+IGNORE\s+INTO",
            "INSERT INTO",
            translated,
            flags=re.IGNORECASE,
        )
        translated = translated.rstrip().removesuffix(";").rstrip()
        translated += " ON CONFLICT DO NOTHING"
    return translated


class PostgresConnection:
    """DB-API-like context wrapper used by the existing repository layer."""

    backend = "postgresql"

    def __init__(self, pool: Any):
        self.pool = pool
        self.connection: Any | None = None
        self._connection_context: Any | None = None
        self._transaction_context: Any | None = None

    def __enter__(self) -> "PostgresConnection":
        self._connection_context = self.pool.connection()
        self.connection = self._connection_context.__enter__()
        self._transaction_context = self.connection.transaction()
        self._transaction_context.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        assert self._transaction_context is not None
        assert self._connection_context is not None
        suppressed = self._transaction_context.__exit__(exc_type, exc, traceback)
        self._connection_context.__exit__(exc_type, exc, traceback)
        self.connection = None
        return bool(suppressed)

    def execute(self, sql: str, parameters: Iterable[Any] | None = None) -> Any:
        assert self.connection is not None
        return self.connection.execute(
            translate_sql(sql),
            tuple(parameters or ()),
        )

    def executemany(self, sql: str, parameters: Iterable[Iterable[Any]]) -> Any:
        assert self.connection is not None
        return self.connection.executemany(
            translate_sql(sql),
            [tuple(values) for values in parameters],
        )

    def executescript(self, script: str) -> None:
        assert self.connection is not None
        statements = [
            statement.strip() for statement in script.split(";") if statement.strip()
        ]
        tables: dict[str, tuple[str, set[str]]] = {}
        unique_indexes: dict[str, list[str]] = {}
        remaining: list[str] = []
        for statement in statements:
            unique_index = re.match(
                r"CREATE\s+UNIQUE\s+INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+\w+"
                r"\s+ON\s+(\w+)",
                statement,
                flags=re.IGNORECASE,
            )
            if unique_index is not None:
                unique_indexes.setdefault(unique_index.group(1), []).append(statement)
                continue
            match = re.match(
                r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)",
                statement,
                flags=re.IGNORECASE,
            )
            if match is None:
                remaining.append(statement)
                continue
            name = match.group(1)
            dependencies = set(
                re.findall(r"REFERENCES\s+(\w+)", statement, flags=re.IGNORECASE)
            )
            dependencies.discard(name)
            if name == "trade_reviews":
                dependencies.discard("trade_review_versions")
                statement = re.sub(
                    r"current_version_id\s+TEXT\s+"
                    r"REFERENCES\s+trade_review_versions\(id\)\s+"
                    r"ON\s+DELETE\s+SET\s+NULL",
                    "current_version_id TEXT",
                    statement,
                    flags=re.IGNORECASE,
                )
            tables[name] = (statement, dependencies)

        unresolved = set(tables)
        while unresolved:
            ready = sorted(
                name
                for name in unresolved
                if not (tables[name][1] & unresolved)
            )
            if not ready:
                raise RuntimeError(
                    "PostgreSQL schema contains unresolved foreign-key cycles: "
                    + ", ".join(sorted(unresolved))
                )
            for name in ready:
                self.connection.execute(translate_sql(tables[name][0]))
                for index_statement in unique_indexes.pop(name, []):
                    self.connection.execute(translate_sql(index_statement))
                unresolved.remove(name)

        if "trade_reviews" in tables and "trade_review_versions" in tables:
            self.connection.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'fk_trade_reviews_current_version'
                    ) THEN
                        ALTER TABLE trade_reviews
                        ADD CONSTRAINT fk_trade_reviews_current_version
                        FOREIGN KEY(current_version_id)
                        REFERENCES trade_review_versions(id)
                        ON DELETE SET NULL;
                    END IF;
                END
                $$
                """
            )
        for statement in remaining:
            self.connection.execute(translate_sql(statement))
        for statements_for_table in unique_indexes.values():
            for statement in statements_for_table:
                self.connection.execute(translate_sql(statement))


def create_postgres_pool(database_url: str) -> Any:
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise RuntimeError(
            "PostgreSQL requires the psycopg binary and pool dependencies"
        ) from exc
    url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    pool = ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=20,
        kwargs={"autocommit": False, "row_factory": dict_row},
        open=True,
    )
    pool.wait(timeout=15)
    return pool


__all__ = ["PostgresConnection", "create_postgres_pool", "translate_sql"]
