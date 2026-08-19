"""Product payload serialization and simulator serial protocol."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str
    count: int = 1

MAX_DELAY_MS = 600_000
BLE_NAME_MAX_BYTES = 18


FAMILY_SCHEMAS: Dict[str, Sequence[FieldSpec]] = {
    "ES4": (
        FieldSpec("version", "u16"), FieldSpec("rx_rssi", "s16"),
        FieldSpec("illuminance", "u16", 2), FieldSpec("pir", "s16", 2),
        FieldSpec("radar", "u8", 5), FieldSpec("chip_id", "u8", 8),
        FieldSpec("key", "u8", 2),
    ),
    "ES5": (
        FieldSpec("version", "u16"), FieldSpec("rx_rssi", "s16"),
        FieldSpec("illuminance", "u16", 3), FieldSpec("battery", "u16"),
        FieldSpec("pir", "s16", 2), FieldSpec("radar", "u8", 3),
        FieldSpec("chip_id", "u8", 8), FieldSpec("power_mode", "u8", 4),
    ),
    "S5": (
        FieldSpec("version", "u8", 2), FieldSpec("infrared", "u8", 2),
        FieldSpec("illuminance", "u16", 2), FieldSpec("screen", "u8", 2),
    ),
    "E5_1": (FieldSpec("version", "u16"), FieldSpec("infrared", "u8", 2),
              FieldSpec("key", "u8"), FieldSpec("temperature", "u16")),
    "E5_2": (FieldSpec("version", "u16"), FieldSpec("infrared", "u8", 2),
              FieldSpec("key", "u8", 2), FieldSpec("temperature", "u16")),
    "E5_3": (FieldSpec("version", "u16"), FieldSpec("infrared", "u8", 2),
              FieldSpec("key", "u8", 3), FieldSpec("temperature", "u16")),
    "E5_4": (FieldSpec("version", "u16"), FieldSpec("infrared", "u8", 2),
              FieldSpec("key", "u8", 4), FieldSpec("touch", "u8"),
              FieldSpec("temperature", "u16")),
    "H3_1": (FieldSpec("version", "u16"), FieldSpec("infrared", "u8", 2),
              FieldSpec("key", "u8")),
    "H3_2": (FieldSpec("version", "u16"), FieldSpec("infrared", "u8", 2),
              FieldSpec("key", "u8", 2)),
    "H3_3": (FieldSpec("version", "u16"), FieldSpec("infrared", "u8", 2),
              FieldSpec("key", "u8", 3)),
    "T2DSB": (FieldSpec("version", "u16"), FieldSpec("temperature", "u8"),
               FieldSpec("zero_cross", "u8")),
    "C6": (FieldSpec("version", "u8"), FieldSpec("rx_rssi", "s8"),
            FieldSpec("illuminance", "u16", 2), FieldSpec("key", "u8", 2),
            FieldSpec("speed", "u8", 2)),
    "E6D": (FieldSpec("version", "u8", 2), FieldSpec("radar", "u8", 3),
             FieldSpec("zero_cross", "u8"), FieldSpec("reserve", "u8"),
             FieldSpec("key", "u8", 4)),
}

_FORMATS = {"u8": ("B", 0, 255), "s8": ("b", -128, 127),
            "u16": ("H", 0, 65535), "s16": ("h", -32768, 32767)}
_HEX_RE = re.compile(r"^[0-9a-fA-F]*$")


def field_names(family: str) -> List[str]:
    return [field.name for field in schema_for(family)]


def schema_for(family: str) -> Sequence[FieldSpec]:
    try:
        return FAMILY_SCHEMAS[family]
    except KeyError as exc:
        raise ValueError(f"未知协议族: {family}") from exc


def _values(value: Any, count: int) -> List[int]:
    if count == 1 and not isinstance(value, (list, tuple)):
        source: Iterable[Any] = [value]
    elif isinstance(value, str):
        source = [item.strip() for item in value.split(",") if item.strip()]
    else:
        source = value
    result = [int(item, 0) if isinstance(item, str) else int(item) for item in source]
    if len(result) != count:
        raise ValueError(f"需要 {count} 个值，当前为 {len(result)} 个")
    return result


def pack_payload(family: str, fields: Mapping[str, Any]) -> bytes:
    payload = bytearray()
    for field in schema_for(family):
        if field.name not in fields:
            raise ValueError(f"缺少字段: {field.name}")
        fmt, minimum, maximum = _FORMATS[field.kind]
        for value in _values(fields[field.name], field.count):
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{field.name} 超出 {field.kind} 范围: {value}")
            payload.extend(struct.pack("<" + fmt, value))
    if len(payload) > 64:
        raise ValueError("Payload 超过固件 64 字节上限")
    return bytes(payload)


def normalize_hex(raw: str) -> str:
    value = raw.replace(" ", "").replace("_", "")
    if len(value) % 2 or not _HEX_RE.fullmatch(value):
        raise ValueError("原始 Payload 必须是偶数长度十六进制")
    if len(value) // 2 > 64:
        raise ValueError("Payload 超过固件 64 字节上限")
    return value.upper()


def payload_hex(family: str, fields: Mapping[str, Any], raw_hex: str = "") -> str:
    return normalize_hex(raw_hex) if raw_hex.strip() else pack_payload(family, fields).hex().upper()


def encode_ble_name(model: Any) -> str:
    name = str(model).strip()
    if not name:
        raise ValueError("Model / BLE 名称不能为空")
    encoded = name.encode("utf-8")
    if len(encoded) > BLE_NAME_MAX_BYTES:
        raise ValueError(f"Model / BLE 名称不能超过 {BLE_NAME_MAX_BYTES} 个 UTF-8 字节")
    return encoded.hex().upper()


def decode_ble_name(encoded: str) -> str:
    value = encoded.strip()
    if not value or len(value) % 2 or not _HEX_RE.fullmatch(value):
        raise ValueError("BLE 名称编码无效")
    raw = bytes.fromhex(value)
    if len(raw) > BLE_NAME_MAX_BYTES:
        raise ValueError(f"BLE 名称不能超过 {BLE_NAME_MAX_BYTES} 个 UTF-8 字节")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("BLE 名称不是有效的 UTF-8") from exc


def build_config_command(sequence: int, product: Mapping[str, Any],
                         advertising: bool = True) -> str:
    pid = int(product["pid"])
    if not 1 <= pid <= 65535:
        raise ValueError("PID 必须在 1..65535")
    behavior = str(product.get("behavior", "normal"))
    if behavior not in {"normal", "timeout", "malformed"}:
        raise ValueError("异常模式仅支持 normal/timeout/malformed")
    delays = (int(product["ready_pcba_ms"]), int(product["ready_final_ms"]),
              int(product.get("notify_delay_ms", 0)))
    if any(value < 0 or value > MAX_DELAY_MS for value in delays):
        raise ValueError(f"延时必须在 0..{MAX_DELAY_MS} ms")
    encoded = payload_hex(str(product["family"]), product["fields"],
                          str(product.get("raw_payload_hex", "")))
    model_hex = encode_ble_name(product["model"])
    values = (
        "CONFIG", int(sequence), pid, delays[0], delays[1], delays[2], behavior,
        int(advertising), encoded, model_hex,
    )
    return " ".join(str(value) for value in values) + "\n"
