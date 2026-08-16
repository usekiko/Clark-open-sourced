"""
utils/db.py
-----------
Schema repair.

CREATE TABLE IF NOT EXISTS does nothing when the table already exists, so a
column an old version made VARCHAR stays VARCHAR even after the DDL is fixed.
The first insert with a real snowflake then dies with "expected str, got int".
"""
from __future__ import annotations

from typing import Iterable

__all__ = ("ensure_bigint_columns",)


async def ensure_bigint_columns(conn, table: str, columns: Iterable[str]) -> list[str]:
    """Converts any of `columns` still typed VARCHAR on `table` to BIGINT.

    Safe to run every startup - already-BIGINT columns and missing tables are
    skipped. Returns what it actually changed so the caller can log it."""
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name   = $1
          AND column_name  = ANY($2::text[])
          AND data_type IN ('character varying', 'character', 'text')
        """,
        table,
        list(columns),
    )

    migrated = []
    for row in rows:
        column = row["column_name"]
        # Identifiers can't be parameterised. These come from cog source, not
        # user input, and information_schema already vouched for them.
        await conn.execute(
            f'ALTER TABLE "{table}" '
            f'ALTER COLUMN "{column}" TYPE BIGINT USING NULLIF("{column}", \'\')::BIGINT'
        )
        migrated.append(column)
    return migrated
