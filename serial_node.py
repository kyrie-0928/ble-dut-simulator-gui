"""Threaded serial connection to one ESP32 simulator node."""

from __future__ import annotations

import queue
import threading
from typing import Callable, Dict, List, Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # Kept optional so protocol/storage tests need no pyserial.
    serial = None
    list_ports = None


def available_ports() -> List[str]:
    if list_ports is None:
        return []
    return [port.device for port in list_ports.comports()]


def parse_sim_line(line: str) -> Dict[str, str]:
    result: Dict[str, str] = {"raw": line.strip()}
    parts = line.strip().split()
    if len(parts) < 2 or parts[0] != "@SIM":
        return result
    result["kind"] = parts[1]
    for part in parts[2:]:
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


class SerialNode:
    def __init__(self, index: int, event_callback: Callable[[int, Dict[str, str]], None]):
        self.index = index
        self._event_callback = event_callback
        self._port = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._sequence = 0

    @property
    def connected(self) -> bool:
        return self._port is not None and bool(self._port.is_open)

    def next_sequence(self) -> int:
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        return self._sequence

    def connect(self, port_name: str, baudrate: int = 1_000_000) -> None:
        if serial is None:
            raise RuntimeError("缺少 pyserial，请先执行 pip install -r requirements.txt")
        if self.connected:
            self.disconnect()
        self._port = serial.Serial(port_name, baudrate, timeout=0.2,
                                   write_timeout=1.0)
        self._stop.clear()
        self._thread = threading.Thread(target=self._read_loop,
                                        name=f"sim-node-{self.index}", daemon=True)
        self._thread.start()
        self._emit({"kind": "LOCAL_CONNECTED", "port": port_name})

    def disconnect(self) -> None:
        self._stop.set()
        port = self._port
        self._port = None
        if port is not None:
            try:
                port.close()
            except Exception as exc:
                self._emit({"kind": "LOCAL_ERROR", "message": str(exc)})
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=0.8)
        self._thread = None
        self._emit({"kind": "LOCAL_DISCONNECTED"})

    def send(self, command: str) -> None:
        port = self._port
        if port is None or not port.is_open:
            raise RuntimeError(f"节点 {self.index} 尚未连接")
        encoded = command.encode("ascii")
        with self._write_lock:
            port.write(encoded)
            port.flush()
        self._emit({"kind": "LOCAL_TX", "raw": command.strip()})

    def _emit(self, event: Dict[str, str]) -> None:
        self._event_callback(self.index, event)

    def _read_loop(self) -> None:
        try:
            while not self._stop.is_set() and self._port is not None:
                raw = self._port.readline()
                if raw:
                    self._emit(parse_sim_line(raw.decode("utf-8", errors="replace")))
        except Exception as exc:
            self._emit({"kind": "LOCAL_ERROR", "message": str(exc)})
        finally:
            port = self._port
            self._port = None
            if port is not None:
                try:
                    port.close()
                except Exception:
                    pass
            self._emit({"kind": "LOCAL_DISCONNECTED"})
