"""SQLite persistence for editable product simulator templates."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Product:
    id: Optional[int]
    name: str
    model: str
    pid: int
    family: str
    ready_pcba_ms: int
    ready_final_ms: int
    notify_delay_ms: int
    behavior: str
    fields: Dict[str, Any]
    raw_payload_hex: str = ""

    def as_mapping(self) -> Dict[str, Any]:
        return asdict(self)


class ProductStore:
    def __init__(self, db_path: Path, seed_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path))
        self._connection.row_factory = sqlite3.Row
        self._create_schema()
        self._seed_once(seed_path)

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                model TEXT NOT NULL,
                pid INTEGER NOT NULL CHECK(pid BETWEEN 1 AND 65535),
                family TEXT NOT NULL,
                ready_pcba_ms INTEGER NOT NULL CHECK(ready_pcba_ms >= 0),
                ready_final_ms INTEGER NOT NULL CHECK(ready_final_ms >= 0),
                notify_delay_ms INTEGER NOT NULL CHECK(notify_delay_ms >= 0),
                behavior TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                raw_payload_hex TEXT NOT NULL DEFAULT ''
            );
        """)
        self._connection.commit()

    def _seed_once(self, seed_path: Path) -> None:
        initialized = self._connection.execute(
            "SELECT value FROM meta WHERE key='seeded'").fetchone()
        if initialized is not None:
            return
        with seed_path.open("r", encoding="utf-8") as source:
            products = json.load(source)
        with self._connection:
            for data in products:
                self._insert(Product(id=None, **data))
            self._connection.execute(
                "INSERT INTO meta(key, value) VALUES('seeded', '1')")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Product:
        return Product(
            id=row["id"], name=row["name"], model=row["model"], pid=row["pid"],
            family=row["family"], ready_pcba_ms=row["ready_pcba_ms"],
            ready_final_ms=row["ready_final_ms"],
            notify_delay_ms=row["notify_delay_ms"], behavior=row["behavior"],
            fields=json.loads(row["fields_json"]),
            raw_payload_hex=row["raw_payload_hex"],
        )

    def list(self, search: str = "") -> List[Product]:
        pattern = f"%{search.strip()}%"
        rows = self._connection.execute(
            """SELECT * FROM products
               WHERE name LIKE ? OR model LIKE ? OR CAST(pid AS TEXT) LIKE ?
               ORDER BY name COLLATE NOCASE, pid""", (pattern, pattern, pattern)
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, product_id: int) -> Optional[Product]:
        row = self._connection.execute(
            "SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        return self._from_row(row) if row else None

    def _insert(self, product: Product) -> int:
        cursor = self._connection.execute(
            """INSERT INTO products
               (name, model, pid, family, ready_pcba_ms, ready_final_ms,
                notify_delay_ms, behavior, fields_json, raw_payload_hex)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (product.name, product.model, product.pid, product.family,
             product.ready_pcba_ms, product.ready_final_ms,
             product.notify_delay_ms, product.behavior,
             json.dumps(product.fields, ensure_ascii=False),
             product.raw_payload_hex),
        )
        return int(cursor.lastrowid)

    def add(self, product: Product) -> int:
        with self._connection:
            return self._insert(product)

    def update(self, product: Product) -> None:
        if product.id is None:
            raise ValueError("更新产品必须包含 id")
        with self._connection:
            cursor = self._connection.execute(
                """UPDATE products SET name=?, model=?, pid=?, family=?,
                   ready_pcba_ms=?, ready_final_ms=?, notify_delay_ms=?,
                   behavior=?, fields_json=?, raw_payload_hex=? WHERE id=?""",
                (product.name, product.model, product.pid, product.family,
                 product.ready_pcba_ms, product.ready_final_ms,
                 product.notify_delay_ms, product.behavior,
                 json.dumps(product.fields, ensure_ascii=False),
                 product.raw_payload_hex, product.id),
            )
            if cursor.rowcount != 1:
                raise KeyError(product.id)

    def delete(self, product_id: int) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM products WHERE id=?", (product_id,))
