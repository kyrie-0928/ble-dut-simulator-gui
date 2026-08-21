"""SQLite persistence for editable product simulator templates."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from protocol import FAMILY_SCHEMAS, FieldSpec, pack_fields, validate_schema


LEGACY_SCHEMA_NAMES = {
    "E5_1": "E5_SINGLE_KEY",
    "E5_2": "E5_DOUBLE_KEY",
    "E5_3": "E5_THREE_KEY",
    "E5_4": "E5_FOUR_KEY",
    "H3_1": "H3_SINGLE_KEY",
    "H3_2": "H3_DOUBLE_KEY",
    "H3_3": "H3_THREE_KEY",
    "T2DSB": "E7D",
}
LEGACY_PUBLIC_FAMILIES = {
    "E5_1": "E5", "E5_2": "E5", "E5_3": "E5", "E5_4": "E5",
    "H3_1": "H3", "H3_2": "H3", "H3_3": "H3",
    "T2DSB": "E7D",
}


def _legacy_public_family(
    old_family: str, product_name: str, model: str, protocol_name: str
) -> str:
    if protocol_name.strip():
        return protocol_name.strip()
    if old_family == "C6":
        normalized_name = product_name.strip().upper()
        normalized_model = model.strip().lower()
        return (
            "C6"
            if normalized_name.startswith("C6") or ".c6" in normalized_model
            else "CE1"
        )
    return LEGACY_PUBLIC_FAMILIES.get(old_family, old_family)


def _migrated_schema_name(old_schema: str, public_family: str) -> str:
    if old_schema == "C6" and public_family == "CE1":
        return "CE1"
    return LEGACY_SCHEMA_NAMES.get(old_schema, old_schema)


@dataclass
class Product:
    id: Optional[int]
    name: str
    model: str
    pid: int
    family: str
    schema_name: str
    ready_pcba_ms: int
    ready_final_ms: int
    notify_delay_ms: int
    behavior: str
    fields: Dict[str, Any]
    raw_payload_hex: str = ""

    def as_mapping(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProtocolFamily:
    name: str
    fields: Sequence[FieldSpec]
    builtin: bool = False


def _schema_to_json(fields: Sequence[FieldSpec]) -> str:
    return json.dumps([asdict(field) for field in fields], ensure_ascii=False)


def _schema_from_json(value: str) -> Sequence[FieldSpec]:
    return tuple(FieldSpec(**item) for item in json.loads(value))


def default_fields(fields: Sequence[FieldSpec]) -> Dict[str, Any]:
    result = {}
    for field in fields:
        default = field.default
        if field.count > 1 and not isinstance(default, (list, tuple)):
            default = [default] * field.count
        result[field.name] = list(default) if isinstance(default, tuple) else default
    return result


class ProductStore:
    def __init__(self, db_path: Path, seed_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path))
        self._connection.row_factory = sqlite3.Row
        self._create_schema()
        self._migrate_protocol_families()
        self._migrate_products()
        self._seed_families()
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
                schema_name TEXT NOT NULL,
                ready_pcba_ms INTEGER NOT NULL CHECK(ready_pcba_ms >= 0),
                ready_final_ms INTEGER NOT NULL CHECK(ready_final_ms >= 0),
                notify_delay_ms INTEGER NOT NULL CHECK(notify_delay_ms >= 0),
                behavior TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                raw_payload_hex TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS protocol_families (
                name TEXT PRIMARY KEY,
                fields_json TEXT NOT NULL,
                builtin INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 1000
            );
        """)
        self._connection.commit()

    def _migrate_protocol_families(self) -> None:
        with self._connection:
            for old_name, new_name in LEGACY_SCHEMA_NAMES.items():
                legacy = self._connection.execute(
                    """SELECT fields_json, builtin, sort_order
                       FROM protocol_families WHERE name=?""",
                    (old_name,),
                ).fetchone()
                if legacy is None:
                    continue
                self._connection.execute(
                    """INSERT OR IGNORE INTO protocol_families
                       (name, fields_json, builtin, sort_order)
                       VALUES (?, ?, ?, ?)""",
                    (
                        new_name, legacy["fields_json"],
                        legacy["builtin"], legacy["sort_order"],
                    ),
                )
                self._connection.execute(
                    "DELETE FROM protocol_families WHERE name=?", (old_name,)
                )

            c6 = self._connection.execute(
                """SELECT fields_json, builtin, sort_order
                   FROM protocol_families WHERE name='C6'"""
            ).fetchone()
            if c6 is not None:
                self._connection.execute(
                    """INSERT OR IGNORE INTO protocol_families
                       (name, fields_json, builtin, sort_order)
                       VALUES ('CE1', ?, ?, ?)""",
                    (c6["fields_json"], c6["builtin"], c6["sort_order"]),
                )

    def _migrate_products(self) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(products)")
        }
        if "schema_name" in columns and "protocol_name" not in columns:
            legacy_names = tuple(LEGACY_SCHEMA_NAMES)
            placeholders = ",".join("?" for _ in legacy_names)
            migration_needed = self._connection.execute(
                f"""SELECT 1 FROM products
                    WHERE schema_name IN ({placeholders})
                       OR family IN ({placeholders})
                       OR (family='CE1' AND schema_name='C6')
                    LIMIT 1""",
                legacy_names + legacy_names,
            ).fetchone()
            if migration_needed is None:
                return

        rows = self._connection.execute("SELECT * FROM products").fetchall()
        has_protocol_name = "protocol_name" in columns
        has_schema_name = "schema_name" in columns
        with self._connection:
            self._connection.execute("DROP TABLE IF EXISTS products_migrated")
            self._connection.execute("""
                CREATE TABLE products_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    pid INTEGER NOT NULL CHECK(pid BETWEEN 1 AND 65535),
                    family TEXT NOT NULL,
                    schema_name TEXT NOT NULL,
                    ready_pcba_ms INTEGER NOT NULL CHECK(ready_pcba_ms >= 0),
                    ready_final_ms INTEGER NOT NULL CHECK(ready_final_ms >= 0),
                    notify_delay_ms INTEGER NOT NULL CHECK(notify_delay_ms >= 0),
                    behavior TEXT NOT NULL,
                    fields_json TEXT NOT NULL,
                    raw_payload_hex TEXT NOT NULL DEFAULT ''
                )
            """)
            for row in rows:
                protocol_name = (
                    str(row["protocol_name"]) if has_protocol_name else ""
                )
                public_family = _legacy_public_family(
                    str(row["family"]), str(row["name"]),
                    str(row["model"]), protocol_name,
                )
                old_schema = (
                    str(row["schema_name"])
                    if has_schema_name and str(row["schema_name"]).strip()
                    else str(row["family"])
                )
                schema_name = _migrated_schema_name(
                    old_schema, public_family
                )
                self._connection.execute(
                    """INSERT INTO products_migrated
                       (id, name, model, pid, family, schema_name,
                        ready_pcba_ms, ready_final_ms, notify_delay_ms,
                        behavior, fields_json, raw_payload_hex)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"], row["name"], row["model"], row["pid"],
                        public_family, schema_name, row["ready_pcba_ms"],
                        row["ready_final_ms"], row["notify_delay_ms"],
                        row["behavior"], row["fields_json"],
                        row["raw_payload_hex"],
                    ),
                )
            self._connection.execute("DROP TABLE products")
            self._connection.execute(
                "ALTER TABLE products_migrated RENAME TO products"
            )

    def _seed_families(self) -> None:
        with self._connection:
            for order, (name, fields) in enumerate(FAMILY_SCHEMAS.items()):
                self._connection.execute(
                    """INSERT OR IGNORE INTO protocol_families
                       (name, fields_json, builtin, sort_order)
                       VALUES (?, ?, 1, ?)""",
                    (name, _schema_to_json(fields), order),
                )

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
            family=row["family"], schema_name=row["schema_name"],
            ready_pcba_ms=row["ready_pcba_ms"],
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
        if self.get_family(product.schema_name) is None:
            raise ValueError(f"未知字段结构: {product.schema_name}")
        cursor = self._connection.execute(
            """INSERT INTO products
               (name, model, pid, family, schema_name,
                ready_pcba_ms, ready_final_ms, notify_delay_ms,
                behavior, fields_json, raw_payload_hex)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                product.name, product.model, product.pid, product.family,
                product.schema_name, product.ready_pcba_ms,
                product.ready_final_ms, product.notify_delay_ms,
                product.behavior,
                json.dumps(product.fields, ensure_ascii=False),
                product.raw_payload_hex,
            ),
        )
        return int(cursor.lastrowid)

    def add(self, product: Product) -> int:
        with self._connection:
            return self._insert(product)

    def update(self, product: Product) -> None:
        if product.id is None:
            raise ValueError("更新产品必须包含 id")
        if self.get_family(product.schema_name) is None:
            raise ValueError(f"未知字段结构: {product.schema_name}")
        with self._connection:
            cursor = self._connection.execute(
                """UPDATE products SET name=?, model=?, pid=?, family=?,
                   schema_name=?, ready_pcba_ms=?, ready_final_ms=?,
                   notify_delay_ms=?, behavior=?, fields_json=?,
                   raw_payload_hex=? WHERE id=?""",
                (
                    product.name, product.model, product.pid, product.family,
                    product.schema_name, product.ready_pcba_ms,
                    product.ready_final_ms, product.notify_delay_ms,
                    product.behavior,
                    json.dumps(product.fields, ensure_ascii=False),
                    product.raw_payload_hex, product.id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(product.id)

    def delete(self, product_id: int) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM products WHERE id=?", (product_id,))

    def list_families(self) -> List[ProtocolFamily]:
        rows = self._connection.execute(
            """SELECT name, fields_json, builtin FROM protocol_families
               ORDER BY sort_order, name COLLATE NOCASE"""
        ).fetchall()
        return [
            ProtocolFamily(row["name"], _schema_from_json(row["fields_json"]),
                           bool(row["builtin"]))
            for row in rows
        ]

    def get_family(self, name: str) -> Optional[ProtocolFamily]:
        row = self._connection.execute(
            """SELECT name, fields_json, builtin FROM protocol_families
               WHERE name=?""", (name,)
        ).fetchone()
        if row is None:
            return None
        return ProtocolFamily(
            row["name"], _schema_from_json(row["fields_json"]), bool(row["builtin"])
        )

    def add_family(self, family: ProtocolFamily) -> None:
        name = family.name.strip()
        if not name:
            raise ValueError("协议族名称不能为空")
        validate_schema(family.fields)
        try:
            with self._connection:
                self._connection.execute(
                    """INSERT INTO protocol_families
                       (name, fields_json, builtin, sort_order)
                       VALUES (?, ?, ?, 1000)""",
                    (name, _schema_to_json(family.fields), int(family.builtin)),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"协议族已存在: {name}") from exc

    def family_usage_count(self, name: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM products WHERE schema_name=?", (name,)
        ).fetchone()
        return int(row["count"])

    def update_family(self, old_name: str, family: ProtocolFamily) -> None:
        current = self.get_family(old_name)
        if current is None:
            raise KeyError(old_name)
        name = family.name.strip()
        if not name:
            raise ValueError("协议族名称不能为空")
        if current.builtin and name != old_name:
            raise ValueError("内置协议族不能改名，请先复制为自定义协议族")
        validate_schema(family.fields)
        if name != old_name and self.get_family(name) is not None:
            raise ValueError(f"协议族已存在: {name}")
        defaults = default_fields(family.fields)
        with self._connection:
            rows = self._connection.execute(
                """SELECT id, fields_json, family FROM products
                   WHERE schema_name=?""",
                (old_name,),
            ).fetchall()
            self._connection.execute(
                """UPDATE protocol_families
                   SET name=?, fields_json=? WHERE name=?""",
                (name, _schema_to_json(family.fields), old_name),
            )
            for row in rows:
                existing = json.loads(row["fields_json"])
                merged = {}
                for field in family.fields:
                    value = existing.get(field.name, defaults[field.name])
                    try:
                        pack_fields((field,), {field.name: value})
                    except (TypeError, ValueError):
                        value = defaults[field.name]
                    merged[field.name] = value
                public_family = (
                    name if row["family"] == old_name else row["family"]
                )
                self._connection.execute(
                    """UPDATE products
                       SET family=?, schema_name=?, fields_json=? WHERE id=?""",
                    (
                        public_family, name,
                        json.dumps(merged, ensure_ascii=False), row["id"],
                    ),
                )

    def delete_family(self, name: str) -> None:
        family = self.get_family(name)
        if family is None:
            raise KeyError(name)
        if family.builtin:
            raise ValueError("内置协议族不能删除，可复制后创建自定义协议族")
        usage = self.family_usage_count(name)
        if usage:
            raise ValueError(f"协议族正在被 {usage} 个产品模板使用，不能删除")
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM protocol_families WHERE name=?", (name,)
            )
            if cursor.rowcount != 1:
                raise KeyError(name)
