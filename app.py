"""Windows desktop controller for up to six BLE DUT simulator boards."""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, simpledialog, ttk
from typing import Dict, List, Optional, Sequence

from protocol import (
    FIELD_KINDS,
    MAX_DELAY_MS,
    FieldSpec,
    build_config_command,
    decode_ble_name,
    encode_ble_name,
    payload_hex,
    validate_schema,
)
from serial_node import SerialNode, available_ports
from storage import (
    Product,
    ProductStore,
    ProtocolFamily,
    default_fields as family_default_fields,
)

APP_NAME = "BLE 产品产测模拟器"
NODE_COUNT = 6

DEFAULT_WINDOW_SIZE = (2100, 1400)
PRODUCT_TABLE_TEXT_PADDING = 20
PRODUCT_TABLE_BORDER_ALLOWANCE = 2
PRODUCT_TABLE_PRODUCT_MIN_WIDTH = 90
PRODUCT_TABLE_PID_MIN_WIDTH = 70
PRODUCT_TABLE_MODEL_MIN_WIDTH = 90
PRODUCT_TABLE_PID_MAX_SHARE = 0.16
PRODUCT_LIBRARY_TARGET_WIDTH = 680
EDITOR_PANEL_WIDTH_SHARE = 0.37
PRODUCT_PID_INPUT_WIDTH = 8
PRODUCT_BEHAVIOR_INPUT_WIDTH = 12
FIELD_EDITOR_MIN_HEIGHT = 80
FIELD_EDITOR_ACTION_GAP = 10
WINDOWS_GA_ROOT = 2
WINDOWS_ICON_SMALL = 0
WINDOWS_ICON_BIG = 1
WINDOWS_IMAGE_ICON = 1
WINDOWS_LOAD_FROM_FILE = 0x0010
WINDOWS_SET_ICON_MESSAGE = 0x0080
COLORS = {
    "app_bg": "#F2F4F7",
    "surface": "#FFFFFF",
    "surface_alt": "#F9FAFB",
    "input": "#F9FAFB",
    "border": "#D0D5DD",
    "border_strong": "#98A2B3",
    "text": "#101828",
    "text_muted": "#475467",
    "primary": "#175CD3",
    "primary_hover": "#1849A9",
    "focus": "#84ADFF",
    "success": "#067647",
    "success_bg": "#ECFDF3",
    "danger": "#B42318",
    "danger_bg": "#FEF3F2",
    "warning": "#B54708",
    "warning_bg": "#FFFAEB",
    "info": "#175CD3",
    "info_bg": "#EFF8FF",
    "disabled": "#98A2B3",
}

FAMILY_STRUCTURE_NAMES = {
    "E5_SINGLE_KEY": "E5 · 单键字段",
    "E5_DOUBLE_KEY": "E5 · 双键字段",
    "E5_THREE_KEY": "E5 · 三键字段",
    "E5_FOUR_KEY": "E5 · 四键字段",
    "H3_SINGLE_KEY": "H3 · 单键字段",
    "H3_DOUBLE_KEY": "H3 · 双键字段",
    "H3_THREE_KEY": "H3 · 三键字段",
    "E7D": "E7D",
    "C6": "C6",
    "CE1": "CE1",
}
PUBLIC_PROTOCOL_SCHEMAS = {
    "ES4": ("ES4",),
    "ES5": ("ES5",),
    "S5": ("S5",),
    "E5": (
        "E5_SINGLE_KEY", "E5_DOUBLE_KEY",
        "E5_THREE_KEY", "E5_FOUR_KEY",
    ),
    "H3": ("H3_SINGLE_KEY", "H3_DOUBLE_KEY", "H3_THREE_KEY"),
    "E7D": ("E7D",),
    "CE1": ("CE1",),
    "C6": ("C6",),
    "E6D": ("E6D",),
}
BUILTIN_SCHEMA_NAMES = frozenset(
    schema_name
    for schema_names in PUBLIC_PROTOCOL_SCHEMAS.values()
    for schema_name in schema_names
)
SCHEMA_PROTOCOL_NAMES = {
    schema_name: protocol_name
    for protocol_name, schema_names in PUBLIC_PROTOCOL_SCHEMAS.items()
    for schema_name in schema_names
}


def family_structure_name(schema_name: str) -> str:
    return FAMILY_STRUCTURE_NAMES.get(schema_name, schema_name)


def protocol_for_schema(schema_name: str) -> str:
    return SCHEMA_PROTOCOL_NAMES.get(schema_name, schema_name)


def _enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        per_monitor_v2 = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(per_monitor_v2):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _resource_path(relative_path: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


class LightweightResizeController:
    """连续缩放时用轻量骨架代替复杂控件树。"""

    def __init__(
        self, window: tk.Tk, content: tk.Widget, placeholder: tk.Widget, settle_ms: int = 120
    ) -> None:
        self.window = window
        self.content = content
        self.placeholder = placeholder
        self.settle_ms = settle_ms
        self.active = False
        self.suspended = True
        self.restore_timer: Optional[str] = None
        self.resume_timer: Optional[str] = None
        self.last_size = (window.winfo_width(), window.winfo_height())
        window.bind("<Configure>", self._on_configure, add="+")
        self._schedule_resume()

    def _schedule_resume(self) -> None:
        if self.resume_timer is not None:
            try:
                self.window.after_cancel(self.resume_timer)
            except tk.TclError:
                pass
        self.resume_timer = self.window.after(self.settle_ms, self._resume)

    def _resume(self) -> None:
        self.resume_timer = None
        try:
            self.last_size = (self.window.winfo_width(), self.window.winfo_height())
        except tk.TclError:
            return
        self.suspended = False

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is not self.window:
            return
        current_size = (int(event.width), int(event.height))
        if current_size[0] <= 1 or current_size[1] <= 1 or current_size == self.last_size:
            return
        self.last_size = current_size
        if self.suspended:
            self._schedule_resume()
            return
        if not self.active:
            try:
                self.content.pack_forget()
                self.placeholder.show_for_size(*current_size)
                self.placeholder.pack(fill="both", expand=True)
            except tk.TclError:
                self.content.pack(fill="both", expand=True)
                return
            self.active = True
        if self.restore_timer is not None:
            try:
                self.window.after_cancel(self.restore_timer)
            except tk.TclError:
                pass
        self.restore_timer = self.window.after(self.settle_ms, self._restore)

    def _restore(self) -> None:
        self.restore_timer = None
        if not self.active:
            return
        try:
            self.placeholder.pack_forget()
            self.content.pack(fill="both", expand=True)
        except tk.TclError:
            pass
        self.active = False


class ResizeSkeletonCanvas(tk.Canvas):
    """按模拟器页面结构绘制窗口缩放占位骨架。"""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(
            master, background=COLORS["app_bg"], bd=0, highlightthickness=0
        )
        self.target_size = (1, 1)

    def show_for_size(self, width: int, height: int) -> None:
        self.target_size = (max(1, int(width)), max(1, int(height)))
        self._redraw()

    def _block(self, x1: float, y1: float, x2: float, y2: float, fill: str) -> None:
        self.create_rectangle(x1, y1, x2, y2, fill=fill, outline=COLORS["border"])

    def _redraw(self) -> None:
        self.delete("all")
        width, height = self.target_size
        margin = 16
        toolbar_height = 66
        self._block(
            margin, margin, width - margin, toolbar_height,
            COLORS["surface"],
        )
        button_x = margin + 12
        for button_width in (120, 120, 120, 120, 120, 120):
            self._block(
                button_x, margin + 10, button_x + button_width, toolbar_height - 10,
                COLORS["info_bg"] if button_x == margin + 12 + 130 else COLORS["surface_alt"],
            )
            button_x += button_width + 10
        content_top = toolbar_height + 12
        content_bottom = max(content_top + 280, height - 14)
        available_width = width - margin * 2
        gaps = 12
        widths = (available_width * 0.38, available_width * 0.32, available_width * 0.30)
        panel_x = margin
        for panel_index, panel_width in enumerate(widths):
            panel_x2 = panel_x + panel_width - gaps
            self._block(panel_x, content_top, panel_x2, content_bottom, COLORS["surface"])
            self.create_rectangle(
                panel_x + 16, content_top + 18, panel_x2 - 16, content_top + 24,
                fill=COLORS["border_strong"], outline="",
            )
            for row in range(6):
                row_y = content_top + 50 + row * 48
                if row_y + 30 >= content_bottom:
                    break
                self.create_rectangle(
                    panel_x + 16, row_y, panel_x2 - 16, row_y + 30,
                    fill=COLORS["input"], outline=COLORS["border"],
                )
            if panel_index == 2:
                log_top = min(content_bottom - 54, content_top + 360)
                self.create_rectangle(
                    panel_x + 16, log_top, panel_x2 - 16, content_bottom - 16,
                    fill=COLORS["surface"], outline=COLORS["border"],
                )
                self.create_rectangle(
                    panel_x + 26, log_top + 40, panel_x2 - 26, content_bottom - 26,
                    fill=COLORS["surface_alt"], outline="",
                )
            panel_x = panel_x2 + gaps


def _default_fields(schema: Sequence[FieldSpec]) -> Dict[str, object]:
    return family_default_fields(schema)


class ProtocolFamilyEditorDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Misc, family: Optional[ProtocolFamily] = None,
                 suggested_name: str = ""):
        self.source = family
        self.result: Optional[ProtocolFamily] = None
        self.rows: List[Dict[str, tk.StringVar]] = []
        self.suggested_name = suggested_name
        super().__init__(parent, "编辑字段结构" if family else "新增字段结构")

    def body(self, master: tk.Misc):
        master.configure(background=COLORS["surface"])
        master.columnconfigure(1, weight=1)
        ttk.Label(master, text="结构名称", style="Field.TLabel").grid(
            row=0, column=0, sticky="w", padx=(4, 12), pady=(6, 12)
        )
        initial_name = self.source.name if self.source else self.suggested_name
        if self.source and self.source.builtin:
            initial_name = family_structure_name(self.source.name)
        self.name_var = tk.StringVar(value=initial_name)
        name_entry = ttk.Entry(master, textvariable=self.name_var, width=34)
        name_entry.grid(row=0, column=1, columnspan=4, sticky="ew", pady=(6, 12))
        if self.source and self.source.builtin:
            name_entry.configure(state="readonly")

        header_frame = ttk.Frame(master, style="Surface.TFrame")
        header_frame.grid(row=1, column=0, columnspan=5, sticky="ew")
        header_columns = (
            (0, "字段名称", 170, 3),
            (1, "类型", 90, 0),
            (2, "数量", 75, 0),
            (3, "默认值", 160, 2),
            (4, "顺序/操作", 205, 0),
        )
        for column, text, minimum, weight in header_columns:
            header_frame.columnconfigure(column, minsize=minimum, weight=weight)
            ttk.Label(header_frame, text=text, style="Muted.TLabel").grid(
                row=0, column=column, sticky="w", padx=(4, 6), pady=(0, 4)
            )
        rows_shell = ttk.Frame(master, style="Surface.TFrame")
        rows_shell.grid(row=2, column=0, columnspan=5, sticky="nsew")
        rows_shell.columnconfigure(0, weight=1)
        rows_shell.rowconfigure(0, weight=1)
        rows_canvas = tk.Canvas(
            rows_shell, background=COLORS["surface"], highlightthickness=0,
            width=720, height=260,
        )
        rows_scrollbar = ttk.Scrollbar(
            rows_shell, orient="vertical", command=rows_canvas.yview
        )
        rows_canvas.configure(yscrollcommand=rows_scrollbar.set)
        rows_canvas.grid(row=0, column=0, sticky="nsew")
        rows_scrollbar.grid(row=0, column=1, sticky="ns")
        self.rows_frame = ttk.Frame(rows_canvas, style="Surface.TFrame")
        rows_window = rows_canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw"
        )
        self.rows_frame.bind(
            "<Configure>",
            lambda _event: rows_canvas.configure(
                scrollregion=rows_canvas.bbox("all")
            ),
        )
        rows_canvas.bind(
            "<Configure>",
            lambda event: rows_canvas.itemconfigure(rows_window, width=event.width),
        )
        master.rowconfigure(2, weight=1)

        source_fields = self.source.fields if self.source else (
            FieldSpec("version", "u8", 1, 0),
        )
        for field in source_fields:
            self._append_field(field)
        ttk.Button(master, text="＋ 添加字段", command=self._add_field).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=4, pady=(10, 4)
        )
        ttk.Label(
            master,
            text="按列表顺序小端打包；总长度不得超过 64 字节",
            style="Muted.TLabel",
        ).grid(row=3, column=2, columnspan=3, sticky="e", pady=(10, 4))
        self.after_idle(lambda: self.minsize(760, 420))
        return name_entry

    def buttonbox(self) -> None:
        box = ttk.Frame(self, style="Surface.TFrame")
        ttk.Button(box, text="保存", style="Primary.TButton", command=self.ok).pack(
            side="left", padx=6
        )
        ttk.Button(box, text="取消", command=self.cancel).pack(side="left", padx=6)
        box.pack(pady=(4, 12))
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    @staticmethod
    def _default_text(field: FieldSpec) -> str:
        value = field.default
        if isinstance(value, (list, tuple)):
            return ",".join(str(item) for item in value)
        return str(value)

    def _append_field(self, field: FieldSpec) -> None:
        self.rows.append({
            "name": tk.StringVar(value=field.name),
            "kind": tk.StringVar(value=field.kind),
            "count": tk.StringVar(value=str(field.count)),
            "default": tk.StringVar(value=self._default_text(field)),
        })
        self._render_rows()

    def _add_field(self) -> None:
        self._append_field(FieldSpec(f"field_{len(self.rows) + 1}", "u8", 1, 0))

    def _render_rows(self) -> None:
        for child in self.rows_frame.winfo_children():
            child.destroy()
        for column, minimum, weight in (
            (0, 170, 3), (1, 90, 0), (2, 75, 0), (3, 160, 2), (4, 205, 0)
        ):
            self.rows_frame.columnconfigure(
                column, minsize=minimum, weight=weight
            )
        for row_index, row in enumerate(self.rows):
            ttk.Entry(self.rows_frame, textvariable=row["name"], width=16).grid(
                row=row_index, column=0, sticky="ew", padx=(4, 6), pady=3
            )
            ttk.Combobox(
                self.rows_frame, textvariable=row["kind"], values=FIELD_KINDS,
                state="readonly", width=7,
            ).grid(row=row_index, column=1, padx=6, pady=3)
            ttk.Spinbox(
                self.rows_frame, textvariable=row["count"], from_=1, to=64, width=6
            ).grid(row=row_index, column=2, padx=6, pady=3)
            ttk.Entry(self.rows_frame, textvariable=row["default"], width=16).grid(
                row=row_index, column=3, padx=6, pady=3
            )
            actions = ttk.Frame(self.rows_frame, style="Surface.TFrame")
            actions.grid(row=row_index, column=4, padx=(6, 4), pady=3)
            ttk.Button(
                actions, text="↑", width=3,
                command=lambda index=row_index: self._move(index, -1),
            ).pack(side="left")
            ttk.Button(
                actions, text="↓", width=3,
                command=lambda index=row_index: self._move(index, 1),
            ).pack(side="left", padx=3)
            ttk.Button(
                actions, text="删除", width=5,
                command=lambda index=row_index: self._remove(index),
            ).pack(side="left")

    def _move(self, index: int, offset: int) -> None:
        destination = index + offset
        if 0 <= destination < len(self.rows):
            self.rows[index], self.rows[destination] = (
                self.rows[destination], self.rows[index]
            )
            self._render_rows()

    def _remove(self, index: int) -> None:
        if len(self.rows) == 1:
            messagebox.showwarning("无法删除", "字段结构至少需要一个字段", parent=self)
            return
        del self.rows[index]
        self._render_rows()

    @staticmethod
    def _parse_default(text: str, count: int) -> object:
        values = [item.strip() for item in text.split(",") if item.strip()]
        if count == 1:
            if len(values) != 1:
                raise ValueError("单值字段只能填写一个默认值")
            return int(values[0], 0)
        if len(values) == 1:
            return [int(values[0], 0)] * count
        if len(values) != count:
            raise ValueError(f"数组默认值需要 1 个或 {count} 个数")
        return [int(item, 0) for item in values]

    def validate(self) -> bool:
        try:
            name = (
                self.source.name
                if self.source and self.source.builtin
                else self.name_var.get().strip()
            )
            if not name:
                raise ValueError("字段结构名称不能为空")
            fields = []
            for row in self.rows:
                count = int(row["count"].get())
                field = FieldSpec(
                    row["name"].get().strip(), row["kind"].get(), count,
                    self._parse_default(row["default"].get(), count),
                )
                fields.append(field)
            validate_schema(fields)
            self.result = ProtocolFamily(
                name, tuple(fields), self.source.builtin if self.source else False
            )
        except (TypeError, ValueError) as exc:
            messagebox.showerror("输入错误", str(exc), parent=self)
            return False
        return True

    def apply(self) -> None:
        pass


class ProtocolFamilyManagerDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Misc, store: ProductStore):
        self.store = store
        super().__init__(parent, "字段结构管理")

    def body(self, master: tk.Misc):
        master.configure(background=COLORS["surface"])
        master.columnconfigure(0, weight=1)
        master.rowconfigure(1, weight=1)
        ttk.Label(
            master, text="字段结构决定字段顺序和 Payload 打包格式",
            style="Muted.TLabel",
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(6, 10))
        self.family_list = tk.Listbox(
            master, height=14, exportselection=False, font=("Microsoft YaHei UI", 10),
            relief="solid", borderwidth=1,
        )
        self.family_list.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=6)
        self.family_list.bind("<<ListboxSelect>>", self._selection_changed)
        buttons = (
            ("新增", self._new_family),
            ("复制", self._copy_family),
            ("编辑", self._edit_family),
            ("删除", self._delete_family),
        )
        for column, (text, command) in enumerate(buttons):
            ttk.Button(master, text=text, command=command).grid(
                row=2, column=column, sticky="ew", padx=6, pady=(10, 4)
            )
            master.columnconfigure(column, weight=1)
        self.usage_var = tk.StringVar()
        ttk.Label(master, textvariable=self.usage_var, style="Muted.TLabel").grid(
            row=3, column=0, columnspan=4, sticky="w", padx=6, pady=(4, 0)
        )
        self._refresh()
        self.after_idle(lambda: self.minsize(560, 500))
        return self.family_list

    def buttonbox(self) -> None:
        box = ttk.Frame(self, style="Surface.TFrame")
        ttk.Button(box, text="关闭", style="Primary.TButton", command=self.ok).pack()
        box.pack(pady=(6, 12))
        self.bind("<Escape>", self.cancel)

    def _refresh(self, selected: str = "") -> None:
        self.family_list.delete(0, "end")
        families = self.store.list_families()
        for family in families:
            marker = "（内置）" if family.builtin else "（自定义）"
            self.family_list.insert(
                "end", f"{family_structure_name(family.name)}  {marker}"
            )
        names = [family.name for family in families]
        if names:
            index = names.index(selected) if selected in names else 0
            self.family_list.selection_set(index)
            self.family_list.see(index)
        self._selection_changed()

    def _selected(self) -> Optional[ProtocolFamily]:
        selection = self.family_list.curselection()
        if not selection:
            return None
        return self.store.list_families()[selection[0]]

    def _selection_changed(self, _event=None) -> None:
        family = self._selected()
        if family is None:
            self.usage_var.set("")
            return
        usage = self.store.family_usage_count(family.name)
        self.usage_var.set(
            f"{len(family.fields)} 个字段 · 被 {usage} 个产品模板使用"
        )

    def _new_family(self) -> None:
        dialog = ProtocolFamilyEditorDialog(self)
        if dialog.result is None:
            return
        try:
            self.store.add_family(dialog.result)
            self._refresh(dialog.result.name)
        except Exception as exc:
            messagebox.showerror("新增失败", str(exc), parent=self)

    def _copy_family(self) -> None:
        source = self._selected()
        if source is None:
            return
        base = f"{source.name}_COPY"
        name = base
        suffix = 2
        while self.store.get_family(name) is not None:
            name = f"{base}_{suffix}"
            suffix += 1
        dialog = ProtocolFamilyEditorDialog(
            self, ProtocolFamily(name, source.fields, False)
        )
        if dialog.result is None:
            return
        try:
            self.store.add_family(
                ProtocolFamily(dialog.result.name, dialog.result.fields, False)
            )
            self._refresh(dialog.result.name)
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc), parent=self)

    def _edit_family(self) -> None:
        source = self._selected()
        if source is None:
            return
        usage = self.store.family_usage_count(source.name)
        if usage and not messagebox.askyesno(
            "确认编辑",
            f"该字段结构被 {usage} 个产品使用。保存后这些产品的字段结构会同步更新，是否继续？",
            parent=self,
        ):
            return
        dialog = ProtocolFamilyEditorDialog(self, source)
        if dialog.result is None:
            return
        try:
            self.store.update_family(source.name, dialog.result)
            self._refresh(dialog.result.name)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)

    def _delete_family(self) -> None:
        source = self._selected()
        if source is None:
            return
        if not messagebox.askyesno(
            "确认删除", f"确定删除字段结构 {family_structure_name(source.name)}？", parent=self
        ):
            return
        try:
            self.store.delete_family(source.name)
            self._refresh()
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)


class AddProductDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Misc, store: ProductStore):
        self.store = store
        self.result: Optional[Product] = None
        super().__init__(parent, "新增产品模板")

    def body(self, master: tk.Misc):
        master.configure(background=COLORS["surface"])
        fields = (("名称", "name_var"), ("Model", "model_var"), ("PID", "pid_var"))
        for row, (label, attribute) in enumerate(fields):
            ttk.Label(master, text=label, style="Field.TLabel").grid(
                row=row, column=0, sticky="w", padx=(4, 14), pady=7
            )
            variable = tk.StringVar()
            setattr(self, attribute, variable)
            ttk.Entry(master, textvariable=variable, width=34).grid(
                row=row, column=1, sticky="ew", pady=7
            )
        ttk.Label(master, text="字段结构", style="Field.TLabel").grid(
            row=3, column=0, sticky="w", padx=(4, 14), pady=7
        )
        family_frame = ttk.Frame(master, style="Surface.TFrame")
        family_frame.grid(row=3, column=1, sticky="ew", pady=7)
        family_frame.columnconfigure(0, weight=1)
        families = self.store.list_families()
        self._family_names = [family.name for family in families]
        labels = [family_structure_name(name) for name in self._family_names]
        self.family_var = tk.StringVar(value=labels[0] if labels else "")
        self.family_combo = ttk.Combobox(
            family_frame, textvariable=self.family_var, values=labels,
            state="readonly", width=24,
        )
        self.family_combo.grid(row=0, column=0, sticky="ew")
        if labels:
            self.family_combo.current(0)
        ttk.Button(
            family_frame, text="管理…", command=self._manage_families
        ).grid(row=0, column=1, padx=(6, 0))
        return master.winfo_children()[1]

    def _manage_families(self) -> None:
        selected = self._selected_schema_name()
        ProtocolFamilyManagerDialog(self, self.store)
        families = self.store.list_families()
        self._family_names = [family.name for family in families]
        labels = [family_structure_name(name) for name in self._family_names]
        self.family_combo.configure(values=labels)
        if not labels:
            self.family_var.set("")
            return
        index = (
            self._family_names.index(selected)
            if selected in self._family_names
            else 0
        )
        self.family_combo.current(index)

    def _selected_schema_name(self) -> str:
        index = self.family_combo.current()
        if 0 <= index < len(self._family_names):
            return self._family_names[index]
        return ""

    def validate(self) -> bool:
        try:
            pid = int(self.pid_var.get())
            if not self.name_var.get().strip() or not self.model_var.get().strip():
                raise ValueError("名称和 Model 不能为空")
            encode_ble_name(self.model_var.get())
            if not 1 <= pid <= 65535:
                raise ValueError("PID 必须在 1..65535")
            if self.store.get_family(self._selected_schema_name()) is None:
                raise ValueError("请选择有效的字段结构")
        except ValueError as exc:
            messagebox.showerror("输入错误", str(exc), parent=self)
            return False
        return True

    def apply(self) -> None:
        family = self.store.get_family(self._selected_schema_name())
        if family is None:
            return
        name = self.name_var.get().strip()
        model = self.model_var.get().strip()
        self.result = Product(
            id=None, name=name, model=model, pid=int(self.pid_var.get()),
            family=protocol_for_schema(family.name),
            schema_name=family.name,
            ready_pcba_ms=5000, ready_final_ms=5000,
            notify_delay_ms=0, behavior="normal",
            fields=_default_fields(family.fields),
        )


class ProtocolStructureChoiceDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent: tk.Misc,
        protocol_name: str,
        choices: Sequence[str],
        selected: str,
    ):
        self.protocol_name = protocol_name
        self.choices = tuple(choices)
        self.selected = selected
        self.result: Optional[str] = None
        super().__init__(parent, f"选择 {protocol_name} 字段结构")

    def body(self, master: tk.Misc):
        master.configure(background=COLORS["surface"])
        ttk.Label(
            master,
            text=f"{self.protocol_name} 包含多种字段结构，请选择本产品使用的结构：",
            style="Field.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(4, 8))
        self._labels = [family_structure_name(name) for name in self.choices]
        self.structure_var = tk.StringVar()
        self.structure_combo = ttk.Combobox(
            master,
            textvariable=self.structure_var,
            values=self._labels,
            state="readonly",
            width=28,
        )
        self.structure_combo.grid(row=1, column=0, sticky="ew")
        selected_index = (
            self.choices.index(self.selected)
            if self.selected in self.choices
            else 0
        )
        if self._labels:
            self.structure_combo.current(selected_index)
        master.columnconfigure(0, weight=1)
        return self.structure_combo

    def validate(self) -> bool:
        return 0 <= self.structure_combo.current() < len(self.choices)

    def apply(self) -> None:
        self.result = self.choices[self.structure_combo.current()]


class SimulatorApp(tk.Tk):
    def __init__(self, store: ProductStore):
        super().__init__()
        self.store = store
        self.title(APP_NAME)
        self.geometry(f"{DEFAULT_WINDOW_SIZE[0]}x{DEFAULT_WINDOW_SIZE[1]}")
        self.minsize(1260, 900)
        self.configure(bg=COLORS["app_bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        png_icon_path = _resource_path("assets/linp.png")
        if png_icon_path.exists():
            try:
                self._window_icon = tk.PhotoImage(file=str(png_icon_path))
                self.iconphoto(True, self._window_icon)
            except tk.TclError:
                self._window_icon = None
        icon_path = _resource_path("assets/linp.ico")
        if icon_path.exists():
            try:
                self.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        self._native_icon_handles: List[int] = []
        self._native_icon_path = icon_path
        self.bind("<Map>", self._on_window_mapped, add="+")
        self._event_queue: queue.Queue = queue.Queue()
        self.nodes = [
            SerialNode(index + 1, self._queue_node_event) for index in range(NODE_COUNT)
        ]
        self.current_product: Optional[Product] = None
        self.selected_schema_name = ""
        self.selected_protocol_name = ""
        self.field_vars: Dict[str, tk.StringVar] = {}
        self.node_selected: List[tk.BooleanVar] = []
        self.node_port_vars: List[tk.StringVar] = []
        self.node_status_vars: List[tk.StringVar] = []
        self.node_cards: List[tk.Frame] = []
        self.node_buttons: List[ttk.Button] = []
        self.node_port_combos: List[ttk.Combobox] = []
        self.node_status_labels: List[ttk.Label] = []
        self.node_configurations: List[Optional[tuple[str, int]]] = [None] * NODE_COUNT
        self.node_ble_connected = [False] * NODE_COUNT
        self.node_adv_enabled = [False] * NODE_COUNT
        self.node_pending_sequences: List[Optional[str]] = [None] * NODE_COUNT
        self.node_pending_products: List[Optional[Product]] = [None] * NODE_COUNT
        self.pending_control_commands: Dict[tuple[int, str], str] = {}
        self.disconnect_pending_nodes: set[int] = set()
        self._discovered_port_count = 0
        self._main_pane_layout_after: Optional[str] = None
        self._fields_layout_after: Optional[str] = None
        self._editor_form_inline_min_width: Optional[int] = None
        self._editor_form_compact: Optional[bool] = None

        self._build_style()
        self._build_ui()
        self._refresh_products()
        self._refresh_ports()
        self._update_control_buttons()
        self.resize_placeholder = ResizeSkeletonCanvas(self)
        self.resize_controller = LightweightResizeController(
            self, self.main_frame, self.resize_placeholder
        )
        self.after_idle(self._set_default_window_geometry)
        self.after(80, self._drain_node_events)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.option_add("*TCombobox*Listbox.font", ("Microsoft YaHei UI", 9))
        self.option_add("*TCombobox*Listbox.background", COLORS["surface"])
        self.option_add("*TCombobox*Listbox.selectBackground", COLORS["primary"])
        self.option_add("*TCombobox*Listbox.selectForeground", COLORS["surface"])

        style.configure(".", font=("Microsoft YaHei UI", 9), background=COLORS["app_bg"])
        style.configure("App.TFrame", background=COLORS["app_bg"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Alt.TFrame", background=COLORS["surface_alt"])
        style.configure(
            "PageTitle.TLabel", background=COLORS["surface"], foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 17, "bold"),
        )
        style.configure(
            "Brand.TLabel", background=COLORS["surface"], foreground=COLORS["primary"],
            font=("Cascadia Mono", 8, "bold"),
        )
        style.configure(
            "Section.TLabel", background=COLORS["surface"], foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.configure(
            "Field.TLabel", background=COLORS["surface"], foreground=COLORS["text_muted"]
        )
        style.configure(
            "Muted.TLabel", background=COLORS["surface"], foreground=COLORS["text_muted"]
        )
        style.configure(
            "AltMuted.TLabel", background=COLORS["surface_alt"], foreground=COLORS["text_muted"]
        )
        style.configure(
            "AltValue.TLabel", background=COLORS["surface_alt"], foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.configure(
            "Data.TLabel", background=COLORS["surface"], foreground=COLORS["text"],
            font=("Cascadia Mono", 9),
        )
        style.configure(
            "Summary.TLabel", background=COLORS["info_bg"], foreground=COLORS["info"],
            font=("Microsoft YaHei UI", 9, "bold"), padding=(10, 6),
        )
        for name, foreground, background in (
            ("Neutral", COLORS["info"], COLORS["info_bg"]),
            ("Success", COLORS["success"], COLORS["success_bg"]),
            ("Warning", COLORS["warning"], COLORS["warning_bg"]),
            ("Danger", COLORS["danger"], COLORS["danger_bg"]),
        ):
            style.configure(
                f"Status{name}.TLabel", background=background, foreground=foreground,
                font=("Microsoft YaHei UI", 8, "bold"), padding=(7, 4), anchor="center",
            )
            style.configure(
                f"Action{name}.TLabel", background=COLORS["surface"], foreground=foreground,
                font=("Microsoft YaHei UI", 9, "bold"),
            )

        style.configure(
            "TEntry", fieldbackground=COLORS["input"], foreground=COLORS["text"],
            bordercolor=COLORS["border"], lightcolor=COLORS["border"],
            darkcolor=COLORS["border"], padding=(8, 6),
        )
        style.configure(
            "TCombobox", fieldbackground=COLORS["input"], foreground=COLORS["text"],
            bordercolor=COLORS["border"], arrowsize=14, padding=(7, 5),
        )
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["input"])])
        style.configure("TButton", padding=(10, 7), borderwidth=1)
        style.map(
            "TButton", background=[("active", COLORS["surface_alt"])],
            foreground=[("disabled", COLORS["disabled"])],
        )
        style.configure(
            "Primary.TButton", background=COLORS["primary"], foreground=COLORS["surface"],
            bordercolor=COLORS["primary"], font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "Primary.TButton", background=[("active", COLORS["primary_hover"])],
            foreground=[("active", COLORS["surface"])],
        )
        style.configure(
            "Danger.TButton", background=COLORS["surface"], foreground=COLORS["danger"],
            bordercolor=COLORS["border"],
        )
        style.map("Danger.TButton", background=[("active", COLORS["danger_bg"])])
        style.configure(
            "Node.TCheckbutton", background=COLORS["surface_alt"],
            foreground=COLORS["text_muted"], padding=(5, 3), anchor="center",
            borderwidth=1, relief="solid",
        )
        style.layout("Node.TCheckbutton", style.layout("Toolbutton"))
        style.map(
            "Node.TCheckbutton",
            background=[
                ("selected", COLORS["primary"]),
                ("active", COLORS["info_bg"]),
            ],
            foreground=[("selected", COLORS["surface"])],
        )
        style.configure(
            "Treeview", background=COLORS["surface"], fieldbackground=COLORS["surface"],
            foreground=COLORS["text"], rowheight=31, borderwidth=0,
        )
        style.configure(
            "Treeview.Heading", background=COLORS["surface_alt"],
            foreground=COLORS["text_muted"], font=("Microsoft YaHei UI", 9, "bold"),
            relief="flat", padding=(5, 6),
        )
        style.map(
            "Treeview", background=[("selected", COLORS["info_bg"])],
            foreground=[("selected", COLORS["primary"])],
        )

    def _build_ui(self) -> None:
        self.port_stats_var = tk.StringVar(value="发现 0 个串口 · 已连接 0 个串口")
        self.main_frame = ttk.Frame(self, style="App.TFrame")
        self.main_frame.pack(fill="both", expand=True)
        toolbar_shell = tk.Frame(
            self.main_frame, bg=COLORS["surface"], highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        toolbar_shell.pack(fill="x", padx=16, pady=(14, 10))
        toolbar = ttk.Frame(toolbar_shell, style="Surface.TFrame", padding=(10, 8))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="刷新串口", command=self._refresh_ports).pack(side="left")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(
            toolbar, text="应用配置", style="Primary.TButton", command=self._apply_to_nodes
        ).pack(side="left")
        self.start_adv_button = ttk.Button(
            toolbar, text="开始广播", command=lambda: self._send_selected("START_ADV")
        )
        self.start_adv_button.pack(side="left", padx=(8, 0))
        self.stop_adv_button = ttk.Button(
            toolbar, text="已停止广播", command=lambda: self._send_selected("STOP_ADV"),
            state="disabled",
        )
        self.stop_adv_button.pack(side="left", padx=(8, 0))
        self.disconnect_ble_button = ttk.Button(
            toolbar, text="断开 BLE", style="Danger.TButton",
            command=lambda: self._send_selected("DISCONNECT"),
        )
        self.disconnect_ble_button.pack(side="left", padx=(8, 0))
        ttk.Button(
            toolbar, text="查询状态", command=lambda: self._send_selected("STATUS")
        ).pack(side="left", padx=(8, 0))
        self.action_var = tk.StringVar(value="请选择产品与节点")
        self.action_label = ttk.Label(toolbar, textvariable=self.action_var, style="ActionNeutral.TLabel")
        self.action_label.pack(side="right", padx=6)

        self.main_panes = tk.PanedWindow(
            self.main_frame, orient="horizontal", bg=COLORS["app_bg"], bd=0,
            sashwidth=6, sashrelief="flat", showhandle=False, opaqueresize=False,
        )
        self.main_panes.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        library = self._panel(self.main_panes)
        editor = self._panel(self.main_panes)
        rack = self._panel(self.main_panes)
        self.main_panes.add(
            library, minsize=300, width=PRODUCT_LIBRARY_TARGET_WIDTH, stretch="always"
        )
        self.main_panes.add(editor, minsize=440, width=540, stretch="always")
        self.main_panes.add(rack, minsize=390, width=510, stretch="always")
        self.main_panes.bind("<Configure>", self._schedule_main_pane_layout, add="+")
        self._build_library(library)
        self._build_editor(editor)
        self._build_rack(rack)

    def _schedule_main_pane_layout(self, _event=None) -> None:
        if self._main_pane_layout_after is not None:
            try:
                self.after_cancel(self._main_pane_layout_after)
            except tk.TclError:
                pass
        self._main_pane_layout_after = self.after_idle(self._place_main_pane_sashes)

    def _place_main_pane_sashes(self) -> None:
        self._main_pane_layout_after = None
        try:
            total_width = self.main_panes.winfo_width()
            sash_width = int(self.main_panes.cget("sashwidth"))
            available_width = total_width - (sash_width * 2)
            if available_width < 1130:
                return

            library_width = PRODUCT_LIBRARY_TARGET_WIDTH
            editor_width = max(
                440, round(available_width * EDITOR_PANEL_WIDTH_SHARE)
            )
            rack_width = available_width - library_width - editor_width
            if rack_width < 390:
                shortage = 390 - rack_width
                editor_reduction = min(shortage, editor_width - 440)
                editor_width -= editor_reduction
                shortage -= editor_reduction
                library_width -= min(shortage, library_width - 300)

            self.main_panes.sash_place(0, library_width, 0)
            self.main_panes.sash_place(
                1, library_width + sash_width + editor_width, 0
            )
            if hasattr(self, "current_node_config_label"):
                self.current_node_config_label.configure(
                    wraplength=max(250, library_width - 30)
                )
        except tk.TclError:
            pass

    def _panel(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(
            parent, bg=COLORS["surface"], padx=14, pady=14,
            highlightbackground=COLORS["border"], highlightthickness=1,
        )

    def _build_library(self, parent: tk.Frame) -> None:
        header = ttk.Frame(parent, style="Surface.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="产品模板", style="Section.TLabel").pack(side="left")
        self.product_count_var = tk.StringVar(value="0 项")
        ttk.Label(header, textvariable=self.product_count_var, style="Muted.TLabel").pack(side="right")
        self.current_node_config_var = tk.StringVar(value="当前 ESP32：UART1 · 配置未知")
        self.current_node_config_label = ttk.Label(
            parent, textvariable=self.current_node_config_var, style="Summary.TLabel",
            anchor="w", justify="left", wraplength=450,
        )
        self.current_node_config_label.pack(fill="x", pady=(0, 10))
        ttk.Label(parent, text="搜索产品 / PID / Model", style="Field.TLabel").pack(anchor="w")
        self.search_var = tk.StringVar()
        search = ttk.Entry(parent, textvariable=self.search_var, justify="left")
        search.pack(fill="x", pady=(4, 10))
        self.search_var.trace_add("write", self._on_search_changed)
        search.bind("<Return>", self._normalize_search)
        search.bind("<FocusOut>", self._normalize_search)

        tree_shell = ttk.Frame(parent, style="Surface.TFrame")
        tree_shell.pack(fill="both", expand=True)
        self.product_tree = ttk.Treeview(
            tree_shell, columns=("product", "pid", "model"),
            show="headings", selectmode="browse",
        )
        self.product_tree.heading("product", text="产品", anchor="w")
        self.product_tree.heading("pid", text="PID", anchor="center")
        self.product_tree.heading("model", text="Model", anchor="center")
        column_options = (
            ("product", "w", PRODUCT_TABLE_PRODUCT_MIN_WIDTH),
            ("pid", "center", PRODUCT_TABLE_PID_MIN_WIDTH),
            ("model", "center", PRODUCT_TABLE_MODEL_MIN_WIDTH),
        )
        for column, anchor, min_width in column_options:
            self.product_tree.column(
                column, width=min_width, minwidth=min_width,
                anchor=anchor, stretch=False,
            )
        tree_font = ttk.Style(self).lookup("Treeview", "font") or "TkDefaultFont"
        self._product_tree_font = tkfont.Font(root=self, font=tree_font)
        scrollbar = ttk.Scrollbar(tree_shell, orient="vertical", command=self.product_tree.yview)
        self.product_tree.configure(yscrollcommand=scrollbar.set)
        self.product_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.product_tree.bind("<<TreeviewSelect>>", self._on_product_selected)
        self.product_tree.bind("<Configure>", self._size_product_columns, add="+")

        controls = ttk.Frame(parent, style="Surface.TFrame")
        controls.pack(fill="x", pady=(10, 0))
        for column in range(3):
            controls.columnconfigure(column, weight=1, uniform="product_actions")
        ttk.Button(controls, text="新增", command=self._add_product).grid(row=0, column=0, sticky="ew")
        ttk.Button(controls, text="复制", command=self._duplicate_product).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(controls, text="删除", style="Danger.TButton", command=self._delete_product).grid(
            row=0, column=2, sticky="ew"
        )

    def _build_editor(self, parent: tk.Frame) -> None:
        header = ttk.Frame(parent, style="Surface.TFrame")
        header.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        ttk.Label(header, text="模板参数", style="Section.TLabel").pack(side="left")
        self.editor_product_var = tk.StringVar(value="未选择产品")
        ttk.Label(header, textvariable=self.editor_product_var, style="Muted.TLabel").pack(side="right")
        self.name_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.pid_var = tk.StringVar()
        self.family_var = tk.StringVar()
        self.pcba_var = tk.StringVar()
        self.final_var = tk.StringVar()
        self.notify_var = tk.StringVar()
        self.behavior_var = tk.StringVar()

        for column in range(4):
            parent.columnconfigure(column, weight=1, uniform="editor_panel")
        self.editor_form = ttk.Frame(parent, style="Surface.TFrame")
        self.editor_form.grid(row=1, column=0, columnspan=4, sticky="ew")
        self.editor_form.columnconfigure(1, weight=1)
        self.name_label = ttk.Label(
            self.editor_form, text="名称", style="Field.TLabel"
        )
        self.name_entry = ttk.Entry(self.editor_form, textvariable=self.name_var)
        self.model_label = ttk.Label(
            self.editor_form, text="Model / BLE 名称", style="Field.TLabel"
        )
        self.model_entry = ttk.Entry(self.editor_form, textvariable=self.model_var)
        self.pid_label = ttk.Label(
            self.editor_form, text="PID", style="Field.TLabel"
        )
        self.pid_entry = ttk.Entry(
            self.editor_form, textvariable=self.pid_var, width=PRODUCT_PID_INPUT_WIDTH
        )
        self.family_label = ttk.Label(
            self.editor_form, text="协议", style="Field.TLabel"
        )
        self.family_combo = ttk.Combobox(
            self.editor_form,
            textvariable=self.family_var,
            values=self._public_protocol_choices(),
            state="readonly",
        )
        self.family_combo.bind("<<ComboboxSelected>>", self._protocol_changed)
        self.behavior_label = ttk.Label(
            self.editor_form, text="异常模式", style="Field.TLabel"
        )
        self.behavior_combo = ttk.Combobox(
            self.editor_form, textvariable=self.behavior_var,
            values=("normal", "timeout", "malformed"),
            state="readonly", width=PRODUCT_BEHAVIOR_INPUT_WIDTH,
        )
        self._layout_editor_form(compact=False)
        self.after_idle(self._initialize_editor_form_layout)
        ttk.Separator(parent).grid(row=4, column=0, columnspan=4, sticky="ew", pady=10)
        ttk.Label(parent, text="响应时序", style="Section.TLabel").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )
        timing = (
            ("半成品就绪", self.pcba_var),
            ("成品就绪", self.final_var),
            ("结果通知延时", self.notify_var),
        )
        timing_frame = ttk.Frame(parent, style="Surface.TFrame")
        timing_frame.grid(row=6, column=0, columnspan=4, sticky="ew")
        for column, (label, variable) in enumerate(timing):
            timing_frame.columnconfigure(column, weight=1, uniform="timing")
            cell = ttk.Frame(timing_frame, style="Surface.TFrame")
            cell.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))
            ttk.Label(cell, text=f"{label} (ms)", style="Field.TLabel").pack(anchor="w")
            ttk.Entry(cell, textvariable=variable).pack(fill="x", pady=(4, 0))

        ttk.Separator(parent).grid(row=7, column=0, columnspan=4, sticky="ew", pady=10)
        field_header = ttk.Frame(parent, style="Surface.TFrame")
        field_header.grid(row=8, column=0, columnspan=4, sticky="ew")
        ttk.Label(field_header, text="协议字段", style="Section.TLabel").pack(side="left")
        ttk.Label(
            parent,
            text="字段名、类型、数量、默认值、顺序均可自定义 · 数组用英文逗号分隔",
            style="Muted.TLabel",
        ).grid(row=9, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.fields_shell = ttk.Frame(parent, style="Surface.TFrame")
        self.fields_shell.grid(
            row=10, column=0, columnspan=4, sticky="ew", pady=(6, 0)
        )
        self.fields_shell.columnconfigure(0, weight=1)
        self.fields_shell.rowconfigure(0, weight=1)
        self.fields_canvas = tk.Canvas(
            self.fields_shell, background=COLORS["surface"], highlightthickness=0,
            height=FIELD_EDITOR_MIN_HEIGHT,
        )
        self.fields_scrollbar = ttk.Scrollbar(
            self.fields_shell, orient="vertical", command=self.fields_canvas.yview
        )
        self.fields_canvas.configure(yscrollcommand=self.fields_scrollbar.set)
        self.fields_canvas.grid(row=0, column=0, sticky="nsew")
        self.fields_scrollbar.grid(row=0, column=1, sticky="ns")
        self.fields_frame = ttk.Frame(self.fields_canvas, style="Surface.TFrame")
        fields_window = self.fields_canvas.create_window(
            (0, 0), window=self.fields_frame, anchor="nw"
        )
        self.fields_frame.bind("<Configure>", self._on_fields_frame_configure)
        self.fields_canvas.bind(
            "<Configure>",
            lambda event: self.fields_canvas.itemconfigure(
                fields_window, width=event.width
            ),
        )
        self.fields_frame.columnconfigure(1, weight=1)
        parent.rowconfigure(10, weight=0)
        parent.rowconfigure(11, weight=1)
        parent.rowconfigure(12, weight=0)

        self.editor_actions = ttk.Frame(parent, style="Surface.TFrame")
        self.editor_actions.grid(
            row=12, column=0, columnspan=4, sticky="ew", pady=(10, 0)
        )
        for column in (0, 2, 4):
            self.editor_actions.columnconfigure(
                column, weight=1, uniform="template_actions"
            )
        self.editor_actions.columnconfigure(1, minsize=8)
        self.editor_actions.columnconfigure(3, minsize=8)
        ttk.Button(
            self.editor_actions, text="保存模板",
            style="Primary.TButton", command=self._save_product,
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            self.editor_actions, text="管理字段结构", command=self._manage_families
        ).grid(row=0, column=2, sticky="ew")
        ttk.Button(
            self.editor_actions, text="编辑字段名称/结构",
            command=self._edit_current_family,
        ).grid(row=0, column=4, sticky="ew")
        parent.bind("<Configure>", self._on_editor_panel_configure, add="+")
        parent.bind("<Configure>", self._schedule_fields_canvas_layout, add="+")

    def _layout_editor_form(self, compact: bool) -> None:
        if self._editor_form_compact is compact:
            return
        widgets = (
            self.name_label,
            self.name_entry,
            self.model_label,
            self.model_entry,
            self.pid_label,
            self.pid_entry,
            self.family_label,
            self.family_combo,
            self.behavior_label,
            self.behavior_combo,
        )
        for widget in widgets:
            widget.grid_forget()

        self.name_label.grid(row=0, column=0, sticky="w", pady=4)
        if compact:
            self.name_entry.grid(
                row=0, column=1, sticky="ew", padx=(10, 18), pady=4
            )
            self.pid_label.grid(row=0, column=2, sticky="w", pady=4)
            self.pid_entry.grid(
                row=0, column=3, sticky="ew", padx=(10, 0), pady=4
            )
            self.model_label.configure(text="Model")
            self.model_label.grid(row=1, column=0, sticky="w", pady=4)
            self.model_entry.grid(
                row=1, column=1, columnspan=3, sticky="ew", padx=(10, 0), pady=4
            )
            self.family_label.grid(row=2, column=0, sticky="w", pady=4)
            self.family_combo.grid(
                row=2, column=1, columnspan=3, sticky="ew", padx=(10, 0), pady=4
            )
            self.behavior_label.grid(row=3, column=0, sticky="w", pady=4)
            self.behavior_combo.grid(
                row=3, column=1, columnspan=3, sticky="ew", padx=(10, 0), pady=4
            )
        else:
            self.name_entry.grid(
                row=0, column=1, columnspan=3, sticky="ew", padx=(10, 0), pady=4
            )
            self.model_label.configure(text="Model / BLE 名称")
            self.model_label.grid(row=1, column=0, sticky="w", pady=4)
            self.model_entry.grid(
                row=1, column=1, sticky="ew", padx=(10, 18), pady=4
            )
            self.pid_label.grid(row=1, column=2, sticky="w", pady=4)
            self.pid_entry.grid(
                row=1, column=3, sticky="ew", padx=(10, 0), pady=4
            )
            self.family_label.grid(row=2, column=0, sticky="w", pady=4)
            self.family_combo.grid(
                row=2, column=1, sticky="ew", padx=(10, 18), pady=4
            )
            self.behavior_label.grid(row=2, column=2, sticky="w", pady=4)
            self.behavior_combo.grid(
                row=2, column=3, sticky="ew", padx=(10, 0), pady=4
            )
        self._editor_form_compact = compact
        if hasattr(self, "fields_canvas"):
            self._schedule_fields_canvas_layout()

    def _initialize_editor_form_layout(self) -> None:
        try:
            self._editor_form_inline_min_width = self.editor_form.winfo_reqwidth()
            self._on_editor_panel_configure()
        except tk.TclError:
            pass

    def _on_editor_panel_configure(self, event=None) -> None:
        if self._editor_form_inline_min_width is None:
            return
        panel_width = (
            event.width if event is not None else self.editor_form.master.winfo_width()
        )
        available_width = max(1, panel_width - 30)
        self._layout_editor_form(
            available_width < self._editor_form_inline_min_width
        )

    def _build_rack(self, parent: tk.Frame) -> None:
        header = ttk.Frame(parent, style="Surface.TFrame")
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="ESP32 模拟节点", style="Section.TLabel").pack(side="left")
        ttk.Label(header, text="最多 6 台", style="Muted.TLabel").pack(side="right")
        ttk.Label(
            parent, text="勾选节点后可批量应用配置和控制 BLE", style="Field.TLabel"
        ).pack(anchor="w", pady=(0, 8))
        self.node_list = ttk.Frame(parent, style="Surface.TFrame")
        self.node_list.pack(fill="x")

        for index in range(NODE_COUNT):
            selected = tk.BooleanVar(value=index == 0)
            selection_mark = tk.StringVar(value="✓" if selected.get() else "")
            selected.trace_add("write", self._selection_changed)
            selected.trace_add(
                "write", lambda *_args, source=selected, target=selection_mark:
                target.set("✓" if source.get() else ""),
            )
            port_var = tk.StringVar()
            status_var = tk.StringVar(value="未连接")
            self.node_selected.append(selected)
            self.node_port_vars.append(port_var)
            self.node_status_vars.append(status_var)

            card = tk.Frame(
                self.node_list, bg=COLORS["surface_alt"],
                highlightbackground=COLORS["border"], highlightthickness=1,
            )
            card.pack(fill="x", pady=(0, 8))
            self.node_cards.append(card)
            ttk.Checkbutton(
                card, textvariable=selection_mark, width=2, variable=selected,
                style="Node.TCheckbutton", takefocus=True
            ).grid(row=0, column=0, padx=(8, 6), pady=7)
            ttk.Label(card, text=f"UART{index + 1}", style="AltValue.TLabel").grid(
                row=0, column=1, sticky="w", padx=(0, 8), pady=7
            )
            combo = ttk.Combobox(card, textvariable=port_var, width=10)
            combo.grid(row=0, column=2, sticky="ew", padx=(0, 7), pady=7)
            self.node_port_combos.append(combo)
            status = ttk.Label(card, textvariable=status_var, style="StatusNeutral.TLabel", width=9)
            status.grid(row=0, column=3, padx=(0, 7), pady=7)
            self.node_status_labels.append(status)
            button = ttk.Button(
                card, text="连接", width=7, command=lambda i=index: self._toggle_node(i)
            )
            button.grid(row=0, column=4, padx=(0, 8), pady=7)
            self.node_buttons.append(button)
            card.columnconfigure(2, weight=1)

        self.port_stats_label = ttk.Label(
            self.node_list, textvariable=self.port_stats_var,
            style="Summary.TLabel", anchor="e",
        )
        self.port_stats_label.pack(fill="x")

        self.log_shell = tk.Frame(
            parent, bg=COLORS["surface"], highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        self.log_shell.pack(fill="both", expand=True, pady=(10, 0))
        self.log_header = ttk.Frame(self.log_shell, style="Surface.TFrame", padding=(12, 7))
        self.log_header.pack(fill="x")
        self.log_header.columnconfigure(1, weight=1)
        self.log_title_label = ttk.Label(
            self.log_header, text="运行日志", style="Section.TLabel"
        )
        self.clear_log_button = ttk.Button(
            self.log_header, text="清空", command=self._clear_log
        )
        self.log_title_label.grid(row=0, column=0, sticky="w")
        self.clear_log_button.grid(row=0, column=2, sticky="e")
        self.log_body = ttk.Frame(
            self.log_shell, style="Surface.TFrame", padding=(10, 0, 10, 10)
        )
        self.log_body.pack(fill="both", expand=True)
        self.log = tk.Text(
            self.log_body, height=10, wrap="word", state="disabled",
            bg=COLORS["surface"], fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", font=("Cascadia Mono", 9), padx=10, pady=8,
        )
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("info", foreground=COLORS["text"])
        self.log.tag_configure("tx", foreground=COLORS["info"])
        self.log.tag_configure("success", foreground=COLORS["success"])
        self.log.tag_configure("warning", foreground=COLORS["warning"])
        self.log.tag_configure("error", foreground=COLORS["danger"])
        self._selection_changed()


    def _refresh_products(self, select_id: Optional[int] = None) -> None:
        selected = select_id or (self.current_product.id if self.current_product else None)
        self.product_tree.delete(*self.product_tree.get_children())
        products = self.store.list(self.search_var.get() if hasattr(self, "search_var") else "")
        for product in products:
            item = self.product_tree.insert(
                "", "end", iid=str(product.id),
                values=(product.name, product.pid, product.model),
            )
            if product.id == selected:
                self.product_tree.selection_set(item)
                self.product_tree.see(item)
        self.product_count_var.set(f"{len(products)} 项")
        children = self.product_tree.get_children()
        if children and not self.product_tree.selection():
            self.product_tree.selection_set(children[0])
            self._load_product(int(children[0]))
        self._size_product_columns()

    def _on_product_selected(self, _event=None) -> None:
        selection = self.product_tree.selection()
        if selection:
            self._load_product(int(selection[0]))

    def _on_search_changed(self, *_args) -> None:
        value = self.search_var.get()
        normalized = value.lstrip()
        if normalized != value:
            self.search_var.set(normalized)
        self._refresh_products()

    def _normalize_search(self, _event=None) -> None:
        value = self.search_var.get()
        normalized = value.strip()
        if normalized != value:
            self.search_var.set(normalized)

    def _size_product_columns(self, event=None) -> None:
        tree_width = event.width if event is not None else self.product_tree.winfo_width()
        usable_width = max(1, tree_width - PRODUCT_TABLE_BORDER_ALLOWANCE)
        products = self.store.list()
        pid_width = max((
            self._product_tree_font.measure("PID"),
            *(self._product_tree_font.measure(str(product.pid)) for product in products),
        )) + PRODUCT_TABLE_TEXT_PADDING
        pid_width = max(
            PRODUCT_TABLE_PID_MIN_WIDTH,
            min(
                pid_width,
                round(usable_width * PRODUCT_TABLE_PID_MAX_SHARE),
            ),
        )
        remaining_width = max(1, usable_width - pid_width)
        product_text_widths = [
            self._product_tree_font.measure(product.name) for product in products
        ] or [self._product_tree_font.measure("产品")]
        model_text_widths = [
            self._product_tree_font.measure(product.model) for product in products
        ] or [self._product_tree_font.measure("Model")]
        product_required_width = max(
            PRODUCT_TABLE_PRODUCT_MIN_WIDTH,
            max(product_text_widths) + PRODUCT_TABLE_TEXT_PADDING,
        )
        model_required_width = max(
            PRODUCT_TABLE_MODEL_MIN_WIDTH,
            max(model_text_widths) + PRODUCT_TABLE_TEXT_PADDING,
        )

        # Balance PID between left-aligned product text and centered model text.
        product_text_center = (
            PRODUCT_TABLE_TEXT_PADDING / 2
            + sum(product_text_widths) / (2 * len(product_text_widths))
        )
        ideal_product_width = round(
            (remaining_width + 2 * product_text_center) / 3
        )
        if remaining_width >= product_required_width + model_required_width:
            product_min_width = product_required_width
            product_max_width = remaining_width - model_required_width
        else:
            product_min_width = PRODUCT_TABLE_PRODUCT_MIN_WIDTH
            product_max_width = max(
                product_min_width,
                remaining_width - PRODUCT_TABLE_MODEL_MIN_WIDTH,
            )
        product_width = min(
            max(product_min_width, ideal_product_width), product_max_width
        )
        model_width = max(
            PRODUCT_TABLE_MODEL_MIN_WIDTH, remaining_width - product_width
        )
        self.product_tree.column("product", width=product_width)
        self.product_tree.column("pid", width=pid_width)
        self.product_tree.column("model", width=model_width)

    def _on_fields_frame_configure(self, _event=None) -> None:
        self.fields_canvas.configure(scrollregion=self.fields_canvas.bbox("all"))
        self._schedule_fields_canvas_layout()

    def _schedule_fields_canvas_layout(self, _event=None) -> None:
        if self._fields_layout_after is not None:
            try:
                self.after_cancel(self._fields_layout_after)
            except tk.TclError:
                pass
        self._fields_layout_after = self.after_idle(self._resize_fields_canvas)

    def _resize_fields_canvas(self) -> None:
        self._fields_layout_after = None
        try:
            requested_height = max(
                FIELD_EDITOR_MIN_HEIGHT,
                self.fields_frame.winfo_reqheight(),
            )
            available_height = max(
                FIELD_EDITOR_MIN_HEIGHT,
                self.fields_shell.master.winfo_height()
                - self.fields_shell.winfo_y()
                - self.editor_actions.winfo_reqheight()
                - FIELD_EDITOR_ACTION_GAP,
            )
            target_height = min(requested_height, available_height)
            if int(float(self.fields_canvas.cget("height"))) != target_height:
                self.fields_canvas.configure(height=target_height)
            if requested_height > target_height:
                self.fields_scrollbar.grid()
            else:
                self.fields_scrollbar.grid_remove()
        except tk.TclError:
            pass

    def _public_protocol_choices(self) -> tuple[str, ...]:
        family_names = {
            family.name for family in self.store.list_families()
        }
        choices = [
            protocol_name
            for protocol_name, candidates in PUBLIC_PROTOCOL_SCHEMAS.items()
            if any(candidate in family_names for candidate in candidates)
        ]
        choices.extend(
            sorted(
                family_name
                for family_name in family_names
                if family_name not in BUILTIN_SCHEMA_NAMES
            )
        )
        if (
            self.selected_protocol_name
            and self.selected_protocol_name not in choices
        ):
            choices.append(self.selected_protocol_name)
        return tuple(choices)

    def _refresh_protocol_choices(self, selected: str = "") -> None:
        choices = self._public_protocol_choices()
        self.family_combo.configure(values=choices)
        if selected:
            self.family_var.set(selected)
        elif self.family_var.get() not in choices:
            self.family_var.set("")

    def _family_key_count(self, family_name: str) -> int:
        family = self.store.get_family(family_name)
        if family is None:
            return 0
        key_field = next(
            (field for field in family.fields if field.name == "key"),
            None,
        )
        return key_field.count if key_field is not None else 0

    def _suggest_family_variant(self, candidates: Sequence[str]) -> str:
        current_key_count = self._family_key_count(self.selected_schema_name)
        if current_key_count:
            for candidate in candidates:
                if self._family_key_count(candidate) == current_key_count:
                    return candidate
        return candidates[0]

    def _resolve_family_for_protocol(
        self, protocol_name: str
    ) -> Optional[str]:
        family_names = {
            family.name for family in self.store.list_families()
        }
        mapped_candidates = PUBLIC_PROTOCOL_SCHEMAS.get(protocol_name)
        if mapped_candidates is None:
            candidates = (
                (protocol_name,) if protocol_name in family_names else ()
            )
        else:
            candidates = tuple(
                candidate
                for candidate in mapped_candidates
                if candidate in family_names
            )
        if not candidates:
            messagebox.showerror(
                "协议不可用",
                f"协议 {protocol_name} 没有可用的字段结构",
                parent=self,
            )
            return None
        if self.selected_schema_name in candidates:
            return self.selected_schema_name
        if len(candidates) == 1:
            return candidates[0]
        dialog = ProtocolStructureChoiceDialog(
            self,
            protocol_name,
            candidates,
            self._suggest_family_variant(candidates),
        )
        return dialog.result

    def _protocol_changed(self, _event=None) -> None:
        protocol_name = self.family_var.get().strip()
        if (
            not protocol_name
            or protocol_name == self.selected_protocol_name
        ):
            return
        family_name = self._resolve_family_for_protocol(protocol_name)
        if family_name is None:
            self.family_var.set(self.selected_protocol_name)
            return
        previous_family_name = self.selected_schema_name
        self.selected_protocol_name = protocol_name
        self.selected_schema_name = family_name
        if family_name != previous_family_name:
            family = self.store.get_family(family_name)
            if family is not None:
                self._rebuild_fields(_default_fields(family.fields))

    def _load_product(self, product_id: int) -> None:
        product = self.store.get(product_id)
        if product is None:
            return
        self.current_product = product
        self.name_var.set(product.name)
        self.model_var.set(product.model)
        self.pid_var.set(str(product.pid))
        self.selected_schema_name = product.schema_name
        self.selected_protocol_name = product.family
        self._refresh_protocol_choices(self.selected_protocol_name)
        self.pcba_var.set(str(product.ready_pcba_ms))
        self.final_var.set(str(product.ready_final_ms))
        self.notify_var.set(str(product.notify_delay_ms))
        self.behavior_var.set(product.behavior)
        self.editor_product_var.set(f"{product.model} · PID {product.pid}")
        self._rebuild_fields(product.fields)

    def _rebuild_fields(self, values: Dict[str, object]) -> None:
        for child in self.fields_frame.winfo_children():
            child.destroy()
        self.field_vars.clear()
        family = self.store.get_family(self.selected_schema_name)
        if family is None:
            self._schedule_fields_canvas_layout()
            return
        defaults = _default_fields(family.fields)
        for row, field in enumerate(family.fields):
            value = values.get(field.name, defaults[field.name])
            text = ",".join(str(item) for item in value) if isinstance(value, list) else str(value)
            variable = tk.StringVar(value=text)
            self.field_vars[field.name] = variable
            suffix = field.kind if field.count == 1 else f"{field.kind}[{field.count}]"
            ttk.Label(self.fields_frame, text=field.name, style="Field.TLabel", width=17).grid(
                row=row, column=0, sticky="w", pady=3
            )
            ttk.Entry(self.fields_frame, textvariable=variable, font=("Cascadia Mono", 9)).grid(
                row=row, column=1, sticky="ew", padx=(8, 8), pady=3
            )
            ttk.Label(self.fields_frame, text=suffix, style="Muted.TLabel", width=8).grid(
                row=row, column=2, sticky="w"
            )
        self.fields_canvas.yview_moveto(0)
        self._schedule_fields_canvas_layout()

    def _manage_families(self) -> None:
        product_id = self.current_product.id if self.current_product else None
        ProtocolFamilyManagerDialog(self, self.store)
        if product_id is not None:
            self._load_product(product_id)

    def _edit_current_family(self) -> None:
        source = self.store.get_family(self.selected_schema_name)
        if source is None:
            messagebox.showwarning("未选择字段结构", "请先选择字段结构", parent=self)
            return
        usage = self.store.family_usage_count(source.name)
        if usage and not messagebox.askyesno(
            "确认编辑",
            f"该字段结构被 {usage} 个产品使用。保存后这些产品的字段名称和结构会同步更新，是否继续？",
            parent=self,
        ):
            return
        dialog = ProtocolFamilyEditorDialog(self, source)
        if dialog.result is None:
            return
        try:
            product_id = self.current_product.id if self.current_product else None
            self.store.update_family(source.name, dialog.result)
            if product_id is not None:
                self._load_product(product_id)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)

    def _collect_product(self) -> Product:
        if self.current_product is None:
            raise ValueError("请先选择产品模板")
        name = self.name_var.get().strip()
        model = self.model_var.get().strip()
        if not name or not model:
            raise ValueError("名称和 Model 不能为空")
        encode_ble_name(model)
        pid = int(self.pid_var.get())
        if not 1 <= pid <= 65535:
            raise ValueError("PID 必须在 1..65535")
        fields = {name: variable.get() for name, variable in self.field_vars.items()}
        if not self.selected_schema_name or not self.selected_protocol_name:
            raise ValueError("请选择有效的协议")
        product = Product(
            id=self.current_product.id, name=name, model=model, pid=pid,
            family=self.selected_protocol_name,
            schema_name=self.selected_schema_name,
            ready_pcba_ms=int(self.pcba_var.get()),
            ready_final_ms=int(self.final_var.get()), notify_delay_ms=int(self.notify_var.get()),
            behavior=self.behavior_var.get(), fields=fields,
            raw_payload_hex="",
        )
        delays = (product.ready_pcba_ms, product.ready_final_ms, product.notify_delay_ms)
        if any(value < 0 or value > MAX_DELAY_MS for value in delays):
            raise ValueError(f"延时必须在 0..{MAX_DELAY_MS} ms")
        family = self.store.get_family(product.schema_name)
        if family is None:
            raise ValueError(f"未知字段结构: {product.schema_name}")
        payload_hex(
            product.schema_name, product.fields,
            product.raw_payload_hex, family.fields
        )
        return product

    def _save_product(self) -> None:
        try:
            product = self._collect_product()
            self.store.update(product)
            self.current_product = product
            self._refresh_products(product.id)
            self._set_action("模板已保存", "Success")
            self._append_log(f"模板已保存: {product.name} / PID {product.pid}", "success")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)

    def _add_product(self) -> None:
        dialog = AddProductDialog(self, self.store)
        if dialog.result is None:
            return
        product_id = self.store.add(dialog.result)
        self._refresh_products(product_id)

    def _duplicate_product(self) -> None:
        try:
            source = self._collect_product()
            source.id = None
            source.name += " 副本"
            product_id = self.store.add(source)
            self._refresh_products(product_id)
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc), parent=self)

    def _delete_product(self) -> None:
        if self.current_product is None:
            return
        if not messagebox.askyesno(
            "删除模板", f"确认删除“{self.current_product.name}”？", parent=self
        ):
            return
        self.store.delete(int(self.current_product.id))
        self.current_product = None
        self.selected_schema_name = ""
        self.selected_protocol_name = ""
        self._refresh_protocol_choices()
        self._refresh_products()

    def _refresh_ports(self) -> None:
        ports = available_ports()
        self._discovered_port_count = len(ports)
        for index, variable in enumerate(self.node_port_vars):
            self.node_port_combos[index].configure(values=ports)
            if not variable.get() and ports:
                used = {item.get() for item in self.node_port_vars[:index]}
                candidate = next((port for port in ports if port not in used), ports[0])
                variable.set(candidate)
        self._update_summary()
        self._append_log(f"发现 {len(ports)} 个串口")

    def _toggle_node(self, index: int) -> None:
        node = self.nodes[index]
        try:
            if node.connected:
                node.disconnect()
            else:
                port = self.node_port_vars[index].get().strip()
                if not port:
                    raise ValueError("请先选择串口")
                node.connect(port)
        except Exception as exc:
            messagebox.showerror(f"节点 {index + 1}", str(exc), parent=self)

    def _selected_connected_nodes(self) -> List[int]:
        return [
            index for index, selected in enumerate(self.node_selected)
            if selected.get() and self.nodes[index].connected
        ]

    def _apply_to_nodes(self) -> None:
        try:
            product = self._collect_product()
            indexes = self._selected_connected_nodes()
            if not indexes:
                raise ValueError("请至少选择并连接一个节点")
            for index in indexes:
                node = self.nodes[index]
                sequence = node.next_sequence()
                family = self.store.get_family(product.schema_name)
                if family is None:
                    raise ValueError(f"未知字段结构: {product.schema_name}")
                node.send(build_config_command(
                    sequence, product.as_mapping(), schema=family.fields
                ))
                self.node_pending_sequences[index] = str(sequence)
                self.node_pending_products[index] = product
                self._set_node_visual(index, "等待确认", "Warning")
            self._set_action(f"正在应用到 {len(indexes)} 个节点", "Warning")
        except Exception as exc:
            messagebox.showerror("应用失败", str(exc), parent=self)

    def _send_selected(self, command: str) -> None:
        indexes = self._selected_connected_nodes()
        if not indexes:
            messagebox.showwarning("未选择节点", "请至少选择并连接一个节点", parent=self)
            return
        sent_count = 0
        for index in indexes:
            node = self.nodes[index]
            try:
                sequence = node.next_sequence()
                node.send(f"{command} {sequence}\n")
                self.pending_control_commands[(index, str(sequence))] = command
                sent_count += 1
                if command == "DISCONNECT":
                    self.disconnect_pending_nodes.add(index)
                    self._set_node_visual(index, "正在断开", "Warning")
            except Exception as exc:
                self._append_log(f"节点 {index + 1} 发送失败: {exc}", "error")
        if not sent_count:
            return
        if command == "START_ADV":
            self.start_adv_button.configure(text="启动中...", state="disabled")
            self._set_action(f"正在启动 {sent_count} 个节点的广播", "Warning")
        elif command == "STOP_ADV":
            self.stop_adv_button.configure(text="停止中...", state="disabled")
            self._set_action(f"正在停止 {sent_count} 个节点的广播", "Warning")
        elif command == "DISCONNECT":
            self.disconnect_ble_button.configure(text="断开中...", state="disabled")
            self._set_action(f"正在断开 {sent_count} 个 BLE 连接", "Warning")
        else:
            self._set_action(f"正在查询 {sent_count} 个节点", "Neutral")

    def _queue_node_event(self, index: int, event: Dict[str, str]) -> None:
        self._event_queue.put((index, event))

    def _drain_node_events(self) -> None:
        try:
            while True:
                index, event = self._event_queue.get_nowait()
                self._handle_node_event(index, event)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(80, self._drain_node_events)

    def _handle_node_event(self, node_number: int, event: Dict[str, str]) -> None:
        index = node_number - 1
        kind = event.get("kind", "RX")
        log_level = "info"
        if kind == "LOCAL_CONNECTED":
            self.node_buttons[index].configure(text="断开")
            self._set_node_visual(index, "串口在线", "Neutral")
            try:
                sequence = self.nodes[index].next_sequence()
                self.nodes[index].send(f"STATUS {sequence}\n")
                self.pending_control_commands[(index, str(sequence))] = "STATUS"
            except Exception as exc:
                self._append_log(f"UART{node_number} 状态查询失败: {exc}", "error")
        elif kind == "LOCAL_DISCONNECTED":
            self.node_ble_connected[index] = False
            self.node_adv_enabled[index] = False
            self.disconnect_pending_nodes.discard(index)
            self._clear_pending_controls(index)
            self.node_buttons[index].configure(text="连接")
            self._set_node_visual(index, "未连接", "Neutral")
        elif kind == "EVENT" and event.get("type") == "connected":
            self.node_ble_connected[index] = True
            self._set_node_visual(index, "BLE 已连接", "Success")
            log_level = "success"
        elif kind == "EVENT" and event.get("type") == "disconnected":
            self.node_ble_connected[index] = False
            self.disconnect_pending_nodes.discard(index)
            self._set_node_visual(index, "BLE 已断开", "Danger")
            self._set_action(f"UART{node_number} BLE 已断开", "Danger")
            log_level = "error"
        elif kind == "STATUS":
            sequence = event.get("seq", "")
            if self.pending_control_commands.get((index, sequence)) == "STATUS":
                self.pending_control_commands.pop((index, sequence), None)
            self.node_ble_connected[index] = event.get("connected") == "1"
            self.node_adv_enabled[index] = event.get("adv") == "1"
            try:
                pid = int(event.get("pid", ""))
            except ValueError:
                pid = 0
            if pid:
                model = None
                model_hex = event.get("model_hex", "")
                if model_hex:
                    try:
                        model = decode_ble_name(model_hex)
                    except ValueError as exc:
                        self._append_log(
                            f"UART{node_number} 状态中的 BLE 名称无效: {exc}", "error"
                        )
                        log_level = "error"
                if model is None:
                    product = next((item for item in self.store.list() if item.pid == pid), None)
                    model = product.model if product is not None else "未知"
                self.node_configurations[index] = (model, pid)
            if self.node_ble_connected[index]:
                self._set_node_visual(index, "BLE 已连接", "Success")
            elif self.node_adv_enabled[index]:
                self._set_node_visual(index, "等待 BLE", "Warning")
            else:
                self._set_node_visual(index, "广播已停止", "Neutral")
        elif kind == "ACK":
            command = event.get("cmd", "")
            sequence = event.get("seq", "")
            if command == "CONFIG" and sequence == self.node_pending_sequences[index]:
                product = self.node_pending_products[index]
                if product is not None:
                    self.node_configurations[index] = (product.model, product.pid)
                self.node_adv_enabled[index] = True
                self.node_pending_sequences[index] = None
                self.node_pending_products[index] = None
                self._set_node_visual(index, "配置生效", "Success")
                self._set_action(f"UART{node_number} 配置已生效", "Success")
                log_level = "success"
            pending_command = self.pending_control_commands.pop((index, sequence), None)
            if pending_command == command:
                if command == "START_ADV":
                    self.node_adv_enabled[index] = True
                    self._set_action(f"UART{node_number} 正在广播", "Success")
                elif command == "STOP_ADV":
                    self.node_adv_enabled[index] = False
                    self._set_action(f"UART{node_number} 广播已停止", "Success")
                elif command == "DISCONNECT":
                    self.node_adv_enabled[index] = False
                    if not self.node_ble_connected[index]:
                        self.disconnect_pending_nodes.discard(index)
                        self._set_action(f"UART{node_number} BLE 已断开", "Success")
                log_level = "success"
        elif kind in {"ERROR", "LOCAL_ERROR"}:
            code = event.get("code", "")
            if code == "NODE_CONNECTED":
                self._set_action(f"UART{node_number} 仍被测试板占用", "Danger")
            elif code:
                self._set_action(f"UART{node_number} 操作失败：{code}", "Danger")
            self.pending_control_commands.pop((index, event.get("seq", "")), None)
            self.disconnect_pending_nodes.discard(index)
            self.node_pending_sequences[index] = None
            self.node_pending_products[index] = None
            self._set_node_visual(index, "操作失败", "Danger")
            log_level = "error"

        raw = event.get("raw") or event.get("message") or str(event)
        if kind == "EVENT" and event.get("type") == "disconnected":
            raw = f"BLE 已断开 · {raw}"
        if kind == "LOCAL_TX":
            log_level = "tx"
        self._append_log(f"UART{node_number} {raw}", log_level)
        self._update_summary()
        self._update_control_buttons()

    def _set_node_visual(self, index: int, text: str, tone: str) -> None:
        self.node_status_vars[index].set(text)
        self.node_status_labels[index].configure(style=f"Status{tone}.TLabel")

    def _selection_changed(self, *_args) -> None:
        for index, card in enumerate(self.node_cards):
            color = COLORS["primary"] if self.node_selected[index].get() else COLORS["border"]
            card.configure(highlightbackground=color)
        self._update_summary()
        self._update_control_buttons()

    def _update_summary(self) -> None:
        if not hasattr(self, "port_stats_var"):
            return
        serial_count = sum(node.connected for node in self.nodes)
        summary = (
            f"发现 {self._discovered_port_count} 个串口 · 已连接 {serial_count} 个串口"
        )
        if self.port_stats_var.get() != summary:
            self.port_stats_var.set(summary)
        if not hasattr(self, "current_node_config_var"):
            return

        indexes = [
            index for index, selected in enumerate(self.node_selected) if selected.get()
        ]
        if not indexes:
            self.current_node_config_var.set("当前 ESP32：未选择 UART")
            return
        if len(indexes) == 1:
            index = indexes[0]
            configuration = self.node_configurations[index]
            if configuration is None:
                state = "配置未知"
                self.current_node_config_var.set(
                    f"当前 ESP32：UART{index + 1} · {state}"
                )
                return
            model, pid = configuration
            if not self.nodes[index].connected:
                state = "上次确认"
            elif self.node_ble_connected[index]:
                state = "BLE 已连接"
            elif self.node_adv_enabled[index]:
                state = "正在广播"
            else:
                state = "广播已停止"
            self.current_node_config_var.set(
                f"当前 ESP32：UART{index + 1} · {model} · PID {pid} · "
                f"BLE 名称：{model} · {state}"
            )
            return

        configurations = [self.node_configurations[index] for index in indexes]
        if any(configuration is None for configuration in configurations):
            summary = f"当前 ESP32：已选 {len(indexes)} 个 UART · 部分配置未知"
        elif len(set(configurations)) != 1:
            summary = f"当前 ESP32：已选 {len(indexes)} 个 UART · 配置不一致"
        else:
            model, pid = configurations[0]
            if any(not self.nodes[index].connected for index in indexes):
                state = "上次确认"
            elif any(self.node_ble_connected[index] for index in indexes):
                state = "包含 BLE 已连接"
            elif all(self.node_adv_enabled[index] for index in indexes):
                state = "全部正在广播"
            elif any(self.node_adv_enabled[index] for index in indexes):
                state = "部分正在广播"
            else:
                state = "广播已停止"
            summary = (
                f"当前 ESP32：已选 {len(indexes)} 个 UART · {model} · PID {pid} · "
                f"BLE 名称：{model} · {state}"
            )
        self.current_node_config_var.set(summary)

    def _clear_pending_controls(self, index: int) -> None:
        for key in [key for key in self.pending_control_commands if key[0] == index]:
            self.pending_control_commands.pop(key, None)

    def _update_control_buttons(self) -> None:
        if not hasattr(self, "start_adv_button"):
            return
        indexes = self._selected_connected_nodes()
        pending_commands = {
            command for (index, _sequence), command in self.pending_control_commands.items()
            if index in indexes
        }
        if "START_ADV" in pending_commands:
            self.start_adv_button.configure(text="启动中...", state="disabled")
        else:
            advertising = [self.node_adv_enabled[index] for index in indexes]
            if advertising and all(advertising):
                self.start_adv_button.configure(text="正在广播", state="disabled")
            elif advertising and any(advertising):
                self.start_adv_button.configure(text="部分节点广播", state="normal")
            else:
                self.start_adv_button.configure(
                    text="开始广播", state="normal" if indexes else "disabled"
                )
        if "STOP_ADV" in pending_commands:
            self.stop_adv_button.configure(text="停止中...", state="disabled")
        elif any(self.node_adv_enabled[index] for index in indexes):
            self.stop_adv_button.configure(text="停止广播", state="normal")
        else:
            self.stop_adv_button.configure(text="已停止广播", state="disabled")
        if "DISCONNECT" in pending_commands or any(
            index in self.disconnect_pending_nodes for index in indexes
        ):
            self.disconnect_ble_button.configure(text="断开中...", state="disabled")
        elif any(self.node_ble_connected[index] for index in indexes):
            self.disconnect_ble_button.configure(text="断开 BLE", state="normal")
        else:
            self.disconnect_ble_button.configure(text="断开 BLE", state="disabled")

    def _set_action(self, text: str, tone: str) -> None:
        self.action_var.set(text)
        self.action_label.configure(style=f"Action{tone}.TLabel")

    def _append_log(self, message: str, level: str = "info") -> None:
        if not hasattr(self, "log"):
            return
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n", level)
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 1000:
            self.log.delete("1.0", f"{lines - 1000}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _set_default_window_geometry(self) -> None:
        try:
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            width = min(DEFAULT_WINDOW_SIZE[0], screen_width)
            height = min(DEFAULT_WINDOW_SIZE[1], screen_height)
            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 2)
            self.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:
            pass
        self.after_idle(self._place_main_pane_sashes)

    def _on_window_mapped(self, event: tk.Event) -> None:
        if event.widget is not self or self._native_icon_handles:
            return
        self.unbind("<Map>")
        self.after_idle(
            lambda: self._set_windows_window_icon(self._native_icon_path)
        )

    def _set_windows_window_icon(self, icon_path: Path) -> None:
        if os.name != "nt" or not icon_path.exists():
            return
        try:
            user32 = ctypes.windll.user32
            user32.GetAncestor.restype = ctypes.c_void_p
            user32.LoadImageW.restype = ctypes.c_void_p
            window_handle = user32.GetAncestor(self.winfo_id(), WINDOWS_GA_ROOT)
            for icon_size, icon_type in (
                (32, WINDOWS_ICON_BIG),
                (16, WINDOWS_ICON_SMALL),
            ):
                icon_handle = user32.LoadImageW(
                    None, str(icon_path), WINDOWS_IMAGE_ICON,
                    icon_size, icon_size, WINDOWS_LOAD_FROM_FILE,
                )
                if not icon_handle:
                    continue
                user32.SendMessageW(
                    window_handle, WINDOWS_SET_ICON_MESSAGE, icon_type, icon_handle
                )
                self._native_icon_handles.append(icon_handle)
        except (AttributeError, OSError, tk.TclError):
            for icon_handle in self._native_icon_handles:
                ctypes.windll.user32.DestroyIcon(icon_handle)
            self._native_icon_handles.clear()

    def _on_close(self) -> None:
        for node in self.nodes:
            node.disconnect()
        self.store.close()
        icon_handles = tuple(self._native_icon_handles)
        self._native_icon_handles.clear()
        self.destroy()
        if os.name == "nt":
            for icon_handle in icon_handles:
                ctypes.windll.user32.DestroyIcon(icon_handle)


def main() -> None:
    _enable_windows_dpi_awareness()
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    data_root = Path(os.environ.get("LOCALAPPDATA", str(base))) / "Linptech" / "BleDutSimulator"
    store = ProductStore(data_root / "products.db", base / "products.json")
    SimulatorApp(store).mainloop()


if __name__ == "__main__":
    main()
