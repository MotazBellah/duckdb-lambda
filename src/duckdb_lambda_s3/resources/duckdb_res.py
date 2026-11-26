import os
from typing import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import duckdb


@dataclass
class DuckDBResource:
    temp_directory: str
    memory_limit: str
    threads: int

    def connect(self, name: str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        """Opens a persistent database stored under temp_directory"""
        db_dir = f"{self.temp_directory}/db"
        name = f"{db_dir}/{name}"
        os.makedirs(db_dir, exist_ok=True)
        conn = duckdb.connect(
            database=name,
            read_only=read_only,
            config={
                # Help reduce memory footprint
                # See https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads#the-preserve_insertion_order-option
                "preserve_insertion_order": "false",
                # Handle larger-than-memory datasets by spilling to disk
                # See https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads#spilling-to-disk
                "temp_directory": self.temp_directory,
                "memory_limit": self.memory_limit,
                # Avoid too many threads
                # See https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads#too-many-threads
                "threads": str(self.threads),
            },
        )
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute("SET TimeZone='UTC'")
        self._configure_s3(conn)

        return conn

    @staticmethod
    def _configure_s3(conn: duckdb.DuckDBPyConnection) -> None:
        """Demo setup: read/write s3:// on Floci.

        Credentials come from the S3_KEY_ID, S3_SECRET and S3_REGION env vars.
        """
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute(f"""
            CREATE OR REPLACE SECRET floci (
                TYPE S3,
                KEY_ID '{os.environ["S3_KEY_ID"]}',
                SECRET '{os.environ["S3_SECRET"]}',
                REGION '{os.environ["S3_REGION"]}',
                ENDPOINT 'host.docker.internal:4566',
                URL_STYLE 'path',
                USE_SSL false
            )
        """)

    @contextmanager
    def open_database(
        self, name: str, read_only: bool = False
    ) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        conn = self.connect(name, read_only=read_only)
        try:
            yield conn
        finally:
            conn.close()
