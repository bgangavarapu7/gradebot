import psycopg
from psycopg.rows import dict_row

from app.config import get_settings


def connect(database_url: str | None = None, **kwargs) -> psycopg.Connection:
    """Open a connection that returns rows as dicts.

    autocommit: every statement is its own transaction. The grade is written with a single
    INSERT, so that is atomic, and no transaction is held open while we wait on the LLM.
    """
    return psycopg.connect(
        database_url or get_settings().database_url,
        row_factory=dict_row,
        autocommit=True,
        **kwargs,
    )
