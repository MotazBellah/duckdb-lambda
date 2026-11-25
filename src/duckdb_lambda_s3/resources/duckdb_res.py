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

        return conn

    @contextmanager
    def open_database(
        self, name: str, read_only: bool = False
    ) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        conn = self.connect(name, read_only=read_only)
        try:
            yield conn
        finally:
            conn.close()