import pathlib
import threading
from typing import Optional

import psycopg2
import psycopg2.errors
import pytest


@pytest.fixture(scope="session")
def datadir() -> pathlib.Path:
    return pathlib.Path(__file__).parent / "data"


@pytest.fixture
def execute(postgresql):
    """Create a thread and return an execute() function that will run SQL queries in that
    thread.
    """
    threads_and_cnx = []

    def execute(
        query: str,
        commit: bool = False,
        autocommit: bool = False,
        dbname: Optional[str] = None,
    ) -> None:
        connection_parms = postgresql.info.dsn_parameters
        if dbname:
            connection_parms["dbname"] = dbname
        conn = psycopg2.connect(**connection_parms)
        conn.autocommit = autocommit

        def _execute() -> None:
            with conn.cursor() as c:
                try:
                    c.execute(query)
                except (
                    psycopg2.errors.AdminShutdown,
                    psycopg2.errors.QueryCanceledError,
                ):
                    return
                if not autocommit and commit:
                    conn.commit()

        thread = threading.Thread(target=_execute, daemon=True)
        thread.start()
        threads_and_cnx.append((thread, conn))

    yield execute

    for thread, conn in threads_and_cnx:
        thread.join(timeout=2)
        conn.close()
