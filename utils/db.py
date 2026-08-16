"""
utils/db.py
-----------
Schema repair helpers.

Every cog creates its tables with CREATE TABLE IF NOT EXISTS, which does nothing
at all when the table already exists. So a column that an older version of Clark
created as VARCHAR stays VARCHAR forever, even after the cog's DDL is corrected —
and the first insert that passes a real snowflake dies with

    DataError: invalid input for query argument $N: 1536... (expected str, got int)

These helpers bring those legacy columns back in line with what the code expects.
"""
from __future__ import annotations

from typing import Iterable

__all__ = ("ensure_bigint_columns",)


async def ensure_bigint_columns(conn, table: str, columns: Iterable[str]) -> list[str]:
    """Convert any of `columns` still typed as VARCHAR/TEXT on `table` to BIGINT.

    Idempotent: columns already BIGINT (and tables that don't exist yet) are left
    alone, so this is safe to run on every startup. Returns the columns it
    actually migrated, so the caller can log a real migration.
    """
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
        # Identifiers can't be parameterised; they come from cog source, never
        # from user input, and information_schema has already vouched for them.
        await conn.execute(
            f'ALTER TABLE "{table}" '
            f'ALTER COLUMN "{column}" TYPE BIGINT USING NULLIF("{column}", \'\')::BIGINT'
        )
        migrated.append(column)
    return migrated
