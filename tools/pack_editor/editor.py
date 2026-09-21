"""Графический редактор TARBIN-паков (tkinter).

Запуск из корня репозитория:
    python tools/pack_editor/editor.py
или
    python -m tools.pack_editor.editor
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from pol_inc.domain.tarbin_pack import (  # noqa: E402
    GLOBAL_STATS,
    KNOWN_TECH_FLAGS,
    REGION_STATS,
)
from tools.pack_editor.pack_model import (  # noqa: E402
    collect_images,
    load_pack_file,
    new_pack_template,
    save_pack_file,
    validate_pack,
)

ALL_STATS = sorted(REGION_STATS | GLOBAL_STATS)
KNOWN_FLAGS = sorted(KNOWN_TECH_FLAGS)

ACTION_TAGS = [
    "military",
    "recon",
    "intel_reveal",
    "hideout_buster",
    "reveal_hideout",
    "guard",
    "info",
    "debunk",
    "statement",
    "infra_project",
    "mobilize",
    "emergency",
]

ALNAZRA_TAGS = ["serious"]

REGION_NUMERIC_FIELDS = [
    "population",
    "economy",
    "trust",
    "security",
    "government",
    "al_nazra",
    "infrastructure",
]


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_int_list(raw: str) -> list[int]:
    result: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if part:
            result.append(int(part))
    return result


def parse_region_filter(raw: str) -> tuple[dict[str, int], list[str]]:
    """Разбирает 'ключ: число, ключ: число'. Возвращает (фильтр, плохие части)."""
    result: dict[str, int] = {}
    bad: list[str] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            bad.append(part)
            continue
        key, _, value = part.partition(":")
        key = key.strip()
        value = value.strip()
        try:
            result[key] = int(value)
        except ValueError:
            bad.append(part)
    return result, bad


def format_region_filter(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    return ", ".join(f"{key}: {val}" for key, val in value.items())


def enable_russian_shortcuts(root: tk.Tk) -> None:
    """Ctrl+C/V/X/Z/A не работают на русской раскладке: у клавиш другие keysym.

    Перехватываем <Control-KeyPress> и вручную генерируем стандартные
    виртуальные события. Латинские сочетания не трогаем (их обрабатывают
    дефолтные биндинги), чтобы не было двойного срабатывания.
    """
    ru_to_virtual = {
        "Cyrillic_es": "<<Copy>>",
        "Cyrillic_em": "<<Paste>>",
        "Cyrillic_che": "<<Cut>>",
        "Cyrillic_ya": "<<Undo>>",
        "Cyrillic_ef": "<<SelectAll>>",
        "с": "<<Copy>>",
        "м": "<<Paste>>",
        "ч": "<<Cut>>",
        "я": "<<Undo>>",
        "ф": "<<SelectAll>>",
    }

    def on_ctrl_keypress(event: tk.Event) -> str | None:
        keysym = event.keysym or ""
        virtual = ru_to_virtual.get(keysym) or ru_to_virtual.get(keysym.lower())

        if virtual is None:
            return None

        try:
            event.widget.event_generate(virtual)
        except Exception:
            pass

        return "break"

    root.bind_all("<Control-KeyPress>", on_ctrl_keypress, add="+")


class EffectsEditor:
    """Переиспользуемый построчный редактор эффектов (stat/target/delta)."""

    def __init__(
        self,
        parent: tk.Widget,
        stats_provider=None,
        on_change=None,
        title: str = "Эффекты:",
    ) -> None:
        self.stats_provider = stats_provider or (lambda: list(ALL_STATS))
        self.on_change = on_change
        self.rows: list[dict] = []

        self.container = ttk.Frame(parent)
        self.container.pack(fill="x", pady=2)

        top = ttk.Frame(self.container)
        top.pack(fill="x")
        ttk.Label(top, text=title, anchor="w").pack(side="left")
        ttk.Button(top, text="+", width=3, command=self._on_add).pack(side="right")

        self.rows_frame = ttk.Frame(self.container)
        self.rows_frame.pack(fill="x")

    def _on_add(self) -> None:
        self.add_row()
        if self.on_change is not None:
            self.on_change()

    def add_row(self, effect: dict | None = None) -> None:
        effect = dict(effect or {})
        row = ttk.Frame(self.rows_frame)
        row.pack(fill="x", pady=1)

        stats = list(self.stats_provider()) or list(ALL_STATS)
        stat_combo = ttk.Combobox(row, values=stats, width=20)
        stat_combo.set(str(effect.get("stat", stats[0] if stats else "")))
        stat_combo.pack(side="left", padx=(0, 4))

        target_combo = ttk.Combobox(row, values=["global", "region"], width=8)
        target_combo.set(str(effect.get("target", "global")))
        target_combo.pack(side="left", padx=(0, 4))

        delta_entry = ttk.Entry(row, width=8)
        delta_entry.insert(0, str(effect.get("delta", 0)))
        delta_entry.pack(side="left", padx=(0, 4))

        ttk.Button(
            row, text="×", width=2, command=lambda: self._remove_row(row)
        ).pack(side="left")

        self.rows.append(
            {"frame": row, "stat": stat_combo, "target": target_combo,
             "delta": delta_entry}
        )

    def _remove_row(self, row: tk.Widget) -> None:
        self.rows = [item for item in self.rows if item["frame"] is not row]
        row.destroy()
        if self.on_change is not None:
            self.on_change()

    def get(self) -> list[dict]:
        effects: list[dict] = []
        for item in self.rows:
            stat = item["stat"].get().strip()
            if not stat:
                continue
            effects.append(
                {
                    "stat": stat,
                    "target": item["target"].get().strip() or "global",
                    "delta": parse_int(item["delta"].get()),
                }
            )
        return effects

    def set(self, effects: object) -> None:
        for item in self.rows:
            item["frame"].destroy()
        self.rows = []
        if isinstance(effects, list):
            for effect in effects:
                if isinstance(effect, dict):
                    self.add_row(effect)


class PackEditorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Редактор TARBIN-пака")
        self.root.geometry("1100x760")

        self.data: dict | None = None
        self.path: str | None = None
        self.dirty = False
        self._loading = False

        self._build_menu()
        self._build_tabs()
        self._build_statusbar()

        enable_russian_shortcuts(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

    # ---------- каркас ----------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Новый пак", command=self.on_new, accelerator="Ctrl+N")
        file_menu.add_command(label="Открыть...", command=self.on_open, accelerator="Ctrl+O")
        file_menu.add_command(label="Сохранить", command=self.on_save, accelerator="Ctrl+S")
        file_menu.add_command(label="Сохранить как...", command=self.on_save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.on_exit)
        menubar.add_cascade(label="Файл", menu=file_menu)

        pack_menu = tk.Menu(menubar, tearoff=0)
        pack_menu.add_command(label="Проверить пак", command=self.on_validate)
        menubar.add_cascade(label="Пак", menu=pack_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Control-n>", lambda _event: self.on_new())
        self.root.bind("<Control-o>", lambda _event: self.on_open())
        self.root.bind("<Control-s>", lambda _event: self.on_save())

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)

        self.tab_pack = ttk.Frame(self.notebook)
        self.tab_roles = ttk.Frame(self.notebook)
        self.tab_regions = ttk.Frame(self.notebook)
        self.tab_techs = ttk.Frame(self.notebook)
        self.tab_actions = ttk.Frame(self.notebook)
        self.tab_events = ttk.Frame(self.notebook)
        self.tab_alnazra = ttk.Frame(self.notebook)
        self.tab_images = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_pack, text="Пак")
        self.notebook.add(self.tab_roles, text="Роли")
        self.notebook.add(self.tab_regions, text="Регионы")
        self.notebook.add(self.tab_techs, text="Технологии")
        self.notebook.add(self.tab_actions, text="Действия")
        self.notebook.add(self.tab_events, text="События")
        self.notebook.add(self.tab_alnazra, text="Al Nazra")
        self.notebook.add(self.tab_images, text="Изображения")

        self._build_pack_tab()
        self._build_roles_tab()
        self._build_regions_tab()
        self._build_techs_tab()
        self._build_actions_tab()
        self._build_events_tab()
        self._build_alnazra_tab()
        self._build_images_tab()

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="Откройте JSON пака: Файл → Открыть...")
        statusbar = ttk.Label(
            self.root, textvariable=self.status_var, relief="sunken", anchor="w"
        )
        statusbar.pack(fill="x", side="bottom")

    # ---------- общие хелперы ----------

    def set_status(self, text: str) -> None:
        self.status_var.set(text)
        self.root.update_idletasks()

    def mark_dirty(self) -> None:
        self.dirty = True
        self._refresh_title()

    def _refresh_title(self) -> None:
        name = self.path if self.path else "без файла"
        star = "*" if self.dirty else ""
        self.root.title(f"Редактор TARBIN-пака — {name}{star}")

    def pack_role_ids(self) -> list[str]:
        if not self.data:
            return []
        return [
            role.get("id")
            for role in self.data.get("roles", []) or []
            if isinstance(role, dict) and role.get("id")
        ]

    def pack_action_ids(self) -> list[str]:
        if not self.data:
            return []
        return [
            action.get("id")
            for action in self.data.get("actions", []) or []
            if isinstance(action, dict) and action.get("id")
        ]

    def pack_tech_ids(self) -> list[str]:
        if not self.data:
            return []
        return [
            tech.get("id")
            for tech in self.data.get("tech_tree", []) or []
            if isinstance(tech, dict) and tech.get("id")
        ]

    @staticmethod
    def entry_row(parent: tk.Widget, label: str, label_width: int = 16) -> ttk.Entry:
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=2)
        ttk.Label(frame, text=label, width=label_width, anchor="w").pack(side="left")
        entry = ttk.Entry(frame)
        entry.pack(side="left", fill="x", expand=True)
        return entry

    @staticmethod
    def combo_row(
        parent: tk.Widget, label: str, values: list[str], label_width: int = 16
    ) -> ttk.Combobox:
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=2)
        ttk.Label(frame, text=label, width=label_width, anchor="w").pack(side="left")
        combo = ttk.Combobox(frame, values=list(values))
        combo.pack(side="left", fill="x", expand=True)
        return combo

    @staticmethod
    def text_block(parent: tk.Widget, label: str, height: int = 4) -> tk.Text:
        ttk.Label(parent, text=label, anchor="w").pack(fill="x")
        text = tk.Text(parent, height=height, wrap="word")
        text.pack(fill="both", expand=True, pady=2)
        return text

    @staticmethod
    def list_panel(parent: tk.Widget) -> tuple[ttk.Frame, tk.Listbox]:
        left = ttk.Frame(parent, width=220)
        left.pack(side="left", fill="y", padx=(0, 6))
        left.pack_propagate(False)

        scrollbar = ttk.Scrollbar(left)
        scrollbar.pack(side="right", fill="y")

        listbox = tk.Listbox(left, yscrollcommand=scrollbar.set, exportselection=False)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        buttons = ttk.Frame(left)
        buttons.pack(side="bottom", fill="x", pady=4)
        return buttons, listbox

    def list_actions(
        self,
        buttons: ttk.Frame,
        listbox: tk.Listbox,
        on_add,
        on_delete,
    ) -> None:
        ttk.Button(buttons, text="Добавить", command=on_add).pack(
            side="top", fill="x", pady=(0, 2)
        )
        ttk.Button(buttons, text="Удалить", command=on_delete).pack(
            side="top", fill="x"
        )
        listbox.bind(
            "<Delete>", lambda _event, delete=on_delete: delete()
        )

    @staticmethod
    def selected_index(listbox: tk.Listbox) -> int | None:
        selection = listbox.curselection()
        return selection[0] if selection else None

    @staticmethod
    def scrollable(parent: tk.Widget) -> ttk.Frame:
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        return inner

    def rebuild_checkboxes(
        self, frame: ttk.Frame, keys: list[str], selected: set[str]
    ) -> dict[str, tk.BooleanVar]:
        for widget in frame.winfo_children():
            widget.destroy()
        variables: dict[str, tk.BooleanVar] = {}
        for key in keys:
            var = tk.BooleanVar(value=key in selected)
            variables[key] = var
            ttk.Checkbutton(frame, text=key, variable=var).pack(anchor="w")
        return variables

    # ---------- вкладка "Пак" ----------

    def _build_pack_tab(self) -> None:
        self.pack_id_entry = self.entry_row(self.tab_pack, "ID пака")
        self.pack_name_entry = self.entry_row(self.tab_pack, "Название")
        self.pack_language_entry = self.entry_row(self.tab_pack, "Язык")
        self.pack_desc_text = self.text_block(self.tab_pack, "Описание", height=4)
        self.pack_durations_entry = self.entry_row(
            self.tab_pack, "Длительности (через ,)", label_width=24
        )
        self.pack_cover_entry = self.entry_row(
            self.tab_pack, "Обложка (assets.cover)", label_width=24
        )

        ttk.Separator(self.tab_pack, orient="horizontal").pack(fill="x", pady=6)
        ttk.Label(self.tab_pack, text="Настройки (settings):", anchor="w").pack(fill="x")

        settings_frame = ttk.Frame(self.tab_pack)
        settings_frame.pack(fill="x")
        self.settings_entries: dict[str, ttk.Entry] = {}
        settings_fields = [
            ("min_players", "Мин. игроков"),
            ("max_players", "Макс. игроков"),
            ("action_points_per_role", "ОД на роль"),
            ("event_turns", "Ходы событий (через ,)"),
            ("start_budget", "Старт: бюджет"),
            ("start_initiative", "Старт: инициатива"),
            ("start_trust", "Старт: доверие"),
            ("start_corruption", "Старт: коррупция"),
            ("start_al_nazra_support", "Старт: поддержка AN"),
            ("initiative_decay", "Распад инициативы"),
            ("base_income", "Базовый доход"),
            ("timeout_hours", "Таймаут (часы)"),
        ]
        for key, label in settings_fields:
            row = ttk.Frame(settings_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, width=24, anchor="w").pack(side="left")
            entry = ttk.Entry(row)
            entry.pack(side="left", fill="x", expand=True)
            self.settings_entries[key] = entry

    def load_pack_tab(self) -> None:
        if not self.data:
            return

        settings = self.data.get("settings", {}) or {}
        assets = self.data.get("assets", {}) or {}

        self.pack_id_entry.delete(0, "end")
        self.pack_id_entry.insert(0, self.data.get("id", ""))
        self.pack_name_entry.delete(0, "end")
        self.pack_name_entry.insert(0, self.data.get("name", ""))
        self.pack_language_entry.delete(0, "end")
        self.pack_language_entry.insert(0, self.data.get("language", "ru"))
        self.pack_desc_text.delete("1.0", "end")
        self.pack_desc_text.insert("1.0", self.data.get("description", ""))
        self.pack_durations_entry.delete(0, "end")
        self.pack_durations_entry.insert(
            0, ", ".join(str(d) for d in self.data.get("durations", []) or [])
        )
        self.pack_cover_entry.delete(0, "end")
        self.pack_cover_entry.insert(0, assets.get("cover") or "")

        for key, entry in self.settings_entries.items():
            entry.delete(0, "end")
            value = settings.get(key, "")
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            entry.insert(0, str(value))

    def flush_pack_tab(self) -> None:
        if not self.data:
            return

        self.data["id"] = self.pack_id_entry.get().strip()
        self.data["name"] = self.pack_name_entry.get().strip()
        self.data["language"] = self.pack_language_entry.get().strip() or "ru"
        self.data["description"] = self.pack_desc_text.get("1.0", "end-1c")

        raw = self.pack_durations_entry.get().strip()
        if raw:
            try:
                self.data["durations"] = parse_int_list(raw)
            except ValueError:
                self.set_status("Длительности: нужны целые числа через запятую.")

        assets = self.data.setdefault("assets", {})
        if isinstance(assets, dict):
            assets["cover"] = self.pack_cover_entry.get().strip() or None

        settings = self.data.setdefault("settings", {})
        if isinstance(settings, dict):
            for key, entry in self.settings_entries.items():
                if key == "event_turns":
                    try:
                        settings[key] = parse_int_list(entry.get())
                    except ValueError:
                        self.set_status("Ходы событий: нужны целые числа через запятую.")
                else:
                    settings[key] = parse_int(entry.get())

    # ---------- вкладка "Роли" ----------

    def _build_roles_tab(self) -> None:
        buttons, self.roles_list = self.list_panel(self.tab_roles)
        self.list_actions(buttons, self.roles_list, self.role_add, self.role_delete)
        self.roles_list.bind("<<ListboxSelect>>", self._on_role_select)

        right = ttk.Frame(self.tab_roles)
        right.pack(side="left", fill="both", expand=True)

        self.role_id_entry = self.entry_row(right, "ID")
        self.role_name_entry = self.entry_row(right, "Название")
        self.role_short_entry = self.entry_row(right, "Короткое имя")
        self.role_desc_text = self.text_block(right, "Описание", height=4)
        self.role_passive_text = self.text_block(right, "Пассивка", height=3)

        ttk.Label(right, text="Доступные действия:", anchor="w").pack(fill="x", pady=(6, 2))
        self.role_actions_frame = ttk.Frame(right)
        self.role_actions_frame.pack(fill="x")
        self.role_action_vars: dict[str, tk.BooleanVar] = {}

        self.current_role: int | None = None

    def role_items(self) -> list[dict]:
        if not self.data:
            return []
        self.data.setdefault("roles", [])
        return self.data["roles"]

    def reload_roles_list(self) -> None:
        self.roles_list.delete(0, "end")
        for role in self.role_items():
            self.roles_list.insert(
                "end", f"{role.get('id', '?')} — {role.get('name', '')}"
            )

    def refresh_role_actions_box(self) -> None:
        items = self.role_items()
        role = (
            items[self.current_role]
            if self.current_role is not None and self.current_role < len(items)
            else {}
        )
        selected = set(role.get("available_actions", []) or [])
        self.role_action_vars = self.rebuild_checkboxes(
            self.role_actions_frame, self.pack_action_ids(), selected
        )

    def _on_role_select(self, _event: object = None) -> None:
        if self._loading:
            return
        self.flush_role_fields()
        self.current_role = self.selected_index(self.roles_list)
        self.refresh_role_actions_box()
        self.load_role_fields()

    def load_role_fields(self) -> None:
        items = self.role_items()
        role = (
            items[self.current_role]
            if self.current_role is not None and self.current_role < len(items)
            else {}
        )

        self.role_id_entry.delete(0, "end")
        self.role_id_entry.insert(0, role.get("id", ""))
        self.role_name_entry.delete(0, "end")
        self.role_name_entry.insert(0, role.get("name", ""))
        self.role_short_entry.delete(0, "end")
        self.role_short_entry.insert(0, role.get("short_name", ""))
        self.role_desc_text.delete("1.0", "end")
        self.role_desc_text.insert("1.0", role.get("description", ""))
        self.role_passive_text.delete("1.0", "end")
        self.role_passive_text.insert("1.0", role.get("passive", ""))

        selected = set(role.get("available_actions", []) or [])
        for action_id, var in self.role_action_vars.items():
            var.set(action_id in selected)

    def flush_role_fields(self) -> None:
        if self.current_role is None:
            return
        items = self.role_items()
        if self.current_role >= len(items):
            return
        items[self.current_role] = {
            "id": self.role_id_entry.get().strip(),
            "name": self.role_name_entry.get().strip(),
            "short_name": self.role_short_entry.get().strip(),
            "description": self.role_desc_text.get("1.0", "end-1c"),
            "passive": self.role_passive_text.get("1.0", "end-1c"),
            "available_actions": [
                action_id
                for action_id, var in self.role_action_vars.items()
                if var.get()
            ],
        }
        self.mark_dirty()

    def role_add(self) -> None:
        if not self.data:
            return
        self.flush_role_fields()
        self.role_items().append(
            {
                "id": "new_role",
                "name": "Новая роль",
                "short_name": "",
                "description": "",
                "passive": "",
                "available_actions": [],
            }
        )
        self.reload_roles_list()
        self.roles_list.selection_clear(0, "end")
        self.roles_list.selection_set("end")
        self.roles_list.see("end")
        self._on_role_select()
        self.mark_dirty()
        self.set_status("Роль добавлена.")

    def role_delete(self) -> None:
        index = self.selected_index(self.roles_list)
        if index is None:
            self.set_status("Выберите роль для удаления.")
            return
        self.current_role = None
        del self.role_items()[index]
        self.reload_roles_list()
        self.refresh_role_actions_box()
        self.load_role_fields()
        self.mark_dirty()
        self.set_status("Роль удалена.")

    # ---------- вкладка "Регионы" ----------

    def _build_regions_tab(self) -> None:
        buttons, self.regions_list = self.list_panel(self.tab_regions)
        self.list_actions(buttons, self.regions_list, self.region_add, self.region_delete)
        self.regions_list.bind("<<ListboxSelect>>", self._on_region_select)

        right = ttk.Frame(self.tab_regions)
        right.pack(side="left", fill="both", expand=True)

        self.region_id_entry = self.entry_row(right, "ID")
        self.region_name_entry = self.entry_row(right, "Название")
        self.region_type_entry = self.entry_row(right, "Тип")
        self.region_numeric_entries: dict[str, ttk.Entry] = {}
        for field in REGION_NUMERIC_FIELDS:
            self.region_numeric_entries[field] = self.entry_row(right, field)

        self.current_region: int | None = None

    def region_items(self) -> list[dict]:
        if not self.data:
            return []
        self.data.setdefault("regions", [])
        return self.data["regions"]

    def reload_regions_list(self) -> None:
        self.regions_list.delete(0, "end")
        for region in self.region_items():
            self.regions_list.insert(
                "end", f"{region.get('id', '?')} — {region.get('name', '')}"
            )

    def _on_region_select(self, _event: object = None) -> None:
        if self._loading:
            return
        self.flush_region_fields()
        self.current_region = self.selected_index(self.regions_list)
        self.load_region_fields()

    def load_region_fields(self) -> None:
        items = self.region_items()
        region = (
            items[self.current_region]
            if self.current_region is not None and self.current_region < len(items)
            else {}
        )
        self.region_id_entry.delete(0, "end")
        self.region_id_entry.insert(0, region.get("id", ""))
        self.region_name_entry.delete(0, "end")
        self.region_name_entry.insert(0, region.get("name", ""))
        self.region_type_entry.delete(0, "end")
        self.region_type_entry.insert(0, region.get("type", ""))
        for field, entry in self.region_numeric_entries.items():
            entry.delete(0, "end")
            entry.insert(0, str(region.get(field, 0)))

    def flush_region_fields(self) -> None:
        if self.current_region is None:
            return
        items = self.region_items()
        if self.current_region >= len(items):
            return
        record = {
            "id": self.region_id_entry.get().strip(),
            "name": self.region_name_entry.get().strip(),
            "type": self.region_type_entry.get().strip(),
        }
        for field, entry in self.region_numeric_entries.items():
            record[field] = parse_int(entry.get())
        items[self.current_region] = record
        self.mark_dirty()

    def region_add(self) -> None:
        if not self.data:
            return
        self.flush_region_fields()
        self.region_items().append(
            {
                "id": "R_new",
                "name": "Новый регион",
                "type": "",
                "population": 1000,
                "economy": 20,
                "trust": 0,
                "security": 25,
                "government": 40,
                "al_nazra": 10,
                "infrastructure": 30,
            }
        )
        self.reload_regions_list()
        self.regions_list.selection_clear(0, "end")
        self.regions_list.selection_set("end")
        self.regions_list.see("end")
        self._on_region_select()
        self.mark_dirty()
        self.set_status("Регион добавлен.")

    def region_delete(self) -> None:
        index = self.selected_index(self.regions_list)
        if index is None:
            self.set_status("Выберите регион для удаления.")
            return
        self.current_region = None
        del self.region_items()[index]
        self.reload_regions_list()
        self.load_region_fields()
        self.mark_dirty()
        self.set_status("Регион удалён.")

    # ---------- вкладка "Технологии" ----------

    def _build_techs_tab(self) -> None:
        buttons, self.techs_list = self.list_panel(self.tab_techs)
        self.list_actions(buttons, self.techs_list, self.tech_add, self.tech_delete)
        self.techs_list.bind("<<ListboxSelect>>", self._on_tech_select)

        right = self.scrollable(self.tab_techs)

        self.tech_id_entry = self.entry_row(right, "ID")
        self.tech_branch_entry = self.entry_row(right, "Ветка")
        self.tech_tier_entry = self.entry_row(right, "Тир")
        self.tech_name_entry = self.entry_row(right, "Название")
        self.tech_cost_entry = self.entry_row(right, "Стоимость")

        ttk.Label(right, text="Prerequisites:", anchor="w").pack(fill="x", pady=(6, 2))
        self.tech_prereq_frame = ttk.Frame(right)
        self.tech_prereq_frame.pack(fill="x")
        self.tech_prereq_vars: dict[str, tk.BooleanVar] = {}

        ttk.Label(right, text="Открывает действия:", anchor="w").pack(fill="x", pady=(6, 2))
        self.tech_unlocks_frame = ttk.Frame(right)
        self.tech_unlocks_frame.pack(fill="x")
        self.tech_unlocks_vars: dict[str, tk.BooleanVar] = {}

        ttk.Label(right, text="Флаги (числа):", anchor="w").pack(fill="x", pady=(6, 2))
        self.tech_flag_entries: dict[str, ttk.Entry] = {}
        for flag in KNOWN_FLAGS:
            self.tech_flag_entries[flag] = self.entry_row(right, flag, label_width=24)

        self.current_tech: int | None = None

    def tech_items(self) -> list[dict]:
        if not self.data:
            return []
        self.data.setdefault("tech_tree", [])
        return self.data["tech_tree"]

    def reload_techs_list(self) -> None:
        self.techs_list.delete(0, "end")
        for tech in self.tech_items():
            self.techs_list.insert(
                "end", f"{tech.get('id', '?')} — {tech.get('name', '')}"
            )

    def refresh_tech_boxes(self) -> None:
        items = self.tech_items()
        tech = (
            items[self.current_tech]
            if self.current_tech is not None and self.current_tech < len(items)
            else {}
        )
        others = [tid for tid in self.pack_tech_ids() if tid != tech.get("id")]
        self.tech_prereq_vars = self.rebuild_checkboxes(
            self.tech_prereq_frame, others, set(tech.get("prerequisites", []) or [])
        )
        self.tech_unlocks_vars = self.rebuild_checkboxes(
            self.tech_unlocks_frame,
            self.pack_action_ids(),
            set(tech.get("unlocks_actions", []) or []),
        )

    def _on_tech_select(self, _event: object = None) -> None:
        if self._loading:
            return
        self.flush_tech_fields()
        self.current_tech = self.selected_index(self.techs_list)
        self.refresh_tech_boxes()
        self.load_tech_fields()

    def load_tech_fields(self) -> None:
        items = self.tech_items()
        tech = (
            items[self.current_tech]
            if self.current_tech is not None and self.current_tech < len(items)
            else {}
        )
        self.tech_id_entry.delete(0, "end")
        self.tech_id_entry.insert(0, tech.get("id", ""))
        self.tech_branch_entry.delete(0, "end")
        self.tech_branch_entry.insert(0, tech.get("branch", ""))
        self.tech_tier_entry.delete(0, "end")
        self.tech_tier_entry.insert(0, str(tech.get("tier", 1)))
        self.tech_name_entry.delete(0, "end")
        self.tech_name_entry.insert(0, tech.get("name", ""))
        self.tech_cost_entry.delete(0, "end")
        self.tech_cost_entry.insert(0, str(tech.get("cost", 0)))

        prereq = set(tech.get("prerequisites", []) or [])
        for tech_id, var in self.tech_prereq_vars.items():
            var.set(tech_id in prereq)
        unlocks = set(tech.get("unlocks_actions", []) or [])
        for action_id, var in self.tech_unlocks_vars.items():
            var.set(action_id in unlocks)

        flags = tech.get("flags", {}) or {}
        for flag, entry in self.tech_flag_entries.items():
            entry.delete(0, "end")
            entry.insert(0, str(flags.get(flag, 0)))

    def flush_tech_fields(self) -> None:
        if self.current_tech is None:
            return
        items = self.tech_items()
        if self.current_tech >= len(items):
            return
        flags = {
            flag: parse_int(entry.get())
            for flag, entry in self.tech_flag_entries.items()
        }
        flags = {flag: value for flag, value in flags.items() if value != 0}
        items[self.current_tech] = {
            "id": self.tech_id_entry.get().strip(),
            "branch": self.tech_branch_entry.get().strip(),
            "tier": parse_int(self.tech_tier_entry.get(), 1),
            "name": self.tech_name_entry.get().strip(),
            "cost": parse_int(self.tech_cost_entry.get()),
            "prerequisites": [
                tech_id for tech_id, var in self.tech_prereq_vars.items() if var.get()
            ],
            "unlocks_actions": [
                action_id
                for action_id, var in self.tech_unlocks_vars.items()
                if var.get()
            ],
            "flags": flags,
        }
        self.mark_dirty()

    def tech_add(self) -> None:
        if not self.data:
            return
        self.flush_tech_fields()
        self.tech_items().append(
            {
                "id": "T_new",
                "branch": "",
                "tier": 1,
                "name": "Новая технология",
                "cost": 0,
                "prerequisites": [],
                "unlocks_actions": [],
                "flags": {},
            }
        )
        self.reload_techs_list()
        self.techs_list.selection_clear(0, "end")
        self.techs_list.selection_set("end")
        self.techs_list.see("end")
        self._on_tech_select()
        self.mark_dirty()
        self.set_status("Технология добавлена.")

    def tech_delete(self) -> None:
        index = self.selected_index(self.techs_list)
        if index is None:
            self.set_status("Выберите технологию для удаления.")
            return
        self.current_tech = None
        del self.tech_items()[index]
        self.reload_techs_list()
        self.refresh_tech_boxes()
        self.load_tech_fields()
        self.mark_dirty()
        self.set_status("Технология удалена.")

    # ---------- вкладка "Действия" ----------

    def _build_actions_tab(self) -> None:
        buttons, self.actions_list = self.list_panel(self.tab_actions)
        self.list_actions(buttons, self.actions_list, self.action_add, self.action_delete)
        self.actions_list.bind("<<ListboxSelect>>", self._on_action_select)

        right = self.scrollable(self.tab_actions)

        self.action_id_entry = self.entry_row(right, "ID")
        self.action_role_combo = self.combo_row(right, "Роль", [])
        self.action_name_entry = self.entry_row(right, "Название")
        self.action_desc_text = self.text_block(right, "Описание", height=3)
        self.action_type_combo = self.combo_row(
            right, "Тип", ["operation", "special"]
        )
        self.action_cost_entry = self.entry_row(right, "Стоимость")
        self.action_target_combo = self.combo_row(
            right, "Цель", ["region", "global", "none"]
        )
        self.action_cooldown_entry = self.entry_row(right, "Кулдаун")

        ttk.Label(right, text="Требования (techs):", anchor="w").pack(
            fill="x", pady=(6, 2)
        )
        self.action_techs_frame = ttk.Frame(right)
        self.action_techs_frame.pack(fill="x")
        self.action_tech_vars: dict[str, tk.BooleanVar] = {}

        ttk.Label(right, text="Теги:", anchor="w").pack(fill="x", pady=(6, 2))
        self.action_tags_frame = ttk.Frame(right)
        self.action_tags_frame.pack(fill="x")
        self.action_tag_vars: dict[str, tk.BooleanVar] = {}
        for tag in ACTION_TAGS:
            var = tk.BooleanVar(value=False)
            self.action_tag_vars[tag] = var
            ttk.Checkbutton(self.action_tags_frame, text=tag, variable=var).pack(
                anchor="w"
            )

        self.action_effects = EffectsEditor(
            right, on_change=self.mark_dirty, title="Эффекты:"
        )
        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)
        self.action_upkeep_name_entry = self.entry_row(right, "Upkeep: имя")
        self.action_upkeep_cost_entry = self.entry_row(right, "Upkeep: цена")
        self.action_income_entry = self.entry_row(right, "Бонус дохода")
        self.action_discount_entry = self.entry_row(right, "Скидка цены")

        self.current_action: int | None = None

    def action_items(self) -> list[dict]:
        if not self.data:
            return []
        self.data.setdefault("actions", [])
        return self.data["actions"]

    def reload_actions_list(self) -> None:
        self.actions_list.delete(0, "end")
        for action in self.action_items():
            self.actions_list.insert(
                "end", f"{action.get('id', '?')} — {action.get('name', '')}"
            )

    def refresh_action_role_values(self) -> None:
        current = self.action_role_combo.get()
        self.action_role_combo["values"] = self.pack_role_ids()
        self.action_role_combo.set(current)

    def refresh_action_techs_box(self) -> None:
        items = self.action_items()
        action = (
            items[self.current_action]
            if self.current_action is not None and self.current_action < len(items)
            else {}
        )
        requirements = action.get("requirements", {}) or {}
        selected = set(requirements.get("techs", []) or [])
        self.action_tech_vars = self.rebuild_checkboxes(
            self.action_techs_frame, self.pack_tech_ids(), selected
        )

    def _on_action_select(self, _event: object = None) -> None:
        if self._loading:
            return
        self.flush_action_fields()
        self.current_action = self.selected_index(self.actions_list)
        self.refresh_action_techs_box()
        self.load_action_fields()

    def load_action_fields(self) -> None:
        items = self.action_items()
        action = (
            items[self.current_action]
            if self.current_action is not None and self.current_action < len(items)
            else {}
        )
        requirements = action.get("requirements", {}) or {}
        upkeep = action.get("upkeep", {}) or {}

        self.action_id_entry.delete(0, "end")
        self.action_id_entry.insert(0, action.get("id", ""))
        self.refresh_action_role_values()
        self.action_role_combo.set(action.get("role_id", ""))
        self.action_name_entry.delete(0, "end")
        self.action_name_entry.insert(0, action.get("name", ""))
        self.action_desc_text.delete("1.0", "end")
        self.action_desc_text.insert("1.0", action.get("description", ""))
        self.action_type_combo.set(action.get("type", "operation"))
        self.action_cost_entry.delete(0, "end")
        self.action_cost_entry.insert(0, str(action.get("cost", 0)))
        self.action_target_combo.set(action.get("target", "none"))
        self.action_cooldown_entry.delete(0, "end")
        self.action_cooldown_entry.insert(0, str(action.get("cooldown", 0)))

        techs = set(requirements.get("techs", []) or [])
        for tech_id, var in self.action_tech_vars.items():
            var.set(tech_id in techs)
        tags = set(action.get("tags", []) or [])
        for tag, var in self.action_tag_vars.items():
            var.set(tag in tags)

        self.action_effects.set(action.get("effects", []) or [])

        self.action_upkeep_name_entry.delete(0, "end")
        self.action_upkeep_name_entry.insert(0, upkeep.get("name", "") if isinstance(upkeep, dict) else "")
        self.action_upkeep_cost_entry.delete(0, "end")
        self.action_upkeep_cost_entry.insert(
            0, str(upkeep.get("cost", 0)) if isinstance(upkeep, dict) else "0"
        )
        self.action_income_entry.delete(0, "end")
        self.action_income_entry.insert(0, str(action.get("next_income_bonus", 0)))
        self.action_discount_entry.delete(0, "end")
        self.action_discount_entry.insert(0, str(action.get("next_cost_discount", 0)))

    def flush_action_fields(self) -> None:
        if self.current_action is None:
            return
        items = self.action_items()
        if self.current_action >= len(items):
            return
        techs = [
            tech_id for tech_id, var in self.action_tech_vars.items() if var.get()
        ]
        upkeep_name = self.action_upkeep_name_entry.get().strip()
        upkeep_cost = parse_int(self.action_upkeep_cost_entry.get())
        upkeep: dict = {}
        if upkeep_name or upkeep_cost:
            upkeep = {"name": upkeep_name, "cost": upkeep_cost}
        items[self.current_action] = {
            "id": self.action_id_entry.get().strip(),
            "role_id": self.action_role_combo.get().strip(),
            "name": self.action_name_entry.get().strip(),
            "description": self.action_desc_text.get("1.0", "end-1c"),
            "type": self.action_type_combo.get().strip() or "operation",
            "cost": parse_int(self.action_cost_entry.get()),
            "target": self.action_target_combo.get().strip() or "none",
            "cooldown": parse_int(self.action_cooldown_entry.get()),
            "requirements": {"techs": techs} if techs else {},
            "effects": self.action_effects.get(),
            "tags": [tag for tag, var in self.action_tag_vars.items() if var.get()],
            "upkeep": upkeep,
            "next_income_bonus": parse_int(self.action_income_entry.get()),
            "next_cost_discount": parse_int(self.action_discount_entry.get()),
        }
        self.mark_dirty()

    def action_add(self) -> None:
        if not self.data:
            return
        self.flush_action_fields()
        roles = self.pack_role_ids()
        self.action_items().append(
            {
                "id": "NEW-01",
                "role_id": roles[0] if roles else "",
                "name": "Новое действие",
                "description": "",
                "type": "operation",
                "cost": 0,
                "target": "none",
                "cooldown": 0,
                "requirements": {},
                "effects": [],
                "tags": [],
                "upkeep": {},
                "next_income_bonus": 0,
                "next_cost_discount": 0,
            }
        )
        self.reload_actions_list()
        self.actions_list.selection_clear(0, "end")
        self.actions_list.selection_set("end")
        self.actions_list.see("end")
        self._on_action_select()
        self.mark_dirty()
        self.set_status("Действие добавлено.")

    def action_delete(self) -> None:
        index = self.selected_index(self.actions_list)
        if index is None:
            self.set_status("Выберите действие для удаления.")
            return
        self.current_action = None
        del self.action_items()[index]
        self.reload_actions_list()
        self.refresh_action_techs_box()
        self.load_action_fields()
        self.mark_dirty()
        self.set_status("Действие удалено.")

    # ---------- вкладка "События" ----------

    def _build_events_tab(self) -> None:
        buttons, self.events_list = self.list_panel(self.tab_events)
        self.list_actions(buttons, self.events_list, self.event_add, self.event_delete)
        self.events_list.bind("<<ListboxSelect>>", self._on_event_select)

        mid = ttk.Frame(self.tab_events, width=150)
        mid.pack(side="left", fill="y", padx=(0, 6))
        mid.pack_propagate(False)
        ttk.Label(mid, text="Варианты:", anchor="w").pack(fill="x")
        self.options_list = tk.Listbox(mid, exportselection=False)
        self.options_list.pack(fill="both", expand=True)
        self.options_list.bind("<<ListboxSelect>>", self._on_option_select)
        option_buttons = ttk.Frame(mid)
        option_buttons.pack(fill="x", pady=4)
        ttk.Button(option_buttons, text="Добавить", command=self.option_add).pack(
            side="top", fill="x", pady=(0, 2)
        )
        ttk.Button(option_buttons, text="Удалить", command=self.option_delete).pack(
            side="top", fill="x"
        )
        self.options_list.bind("<Delete>", lambda _event: self.option_delete())

        mid2 = ttk.Frame(self.tab_events, width=150)
        mid2.pack(side="left", fill="y", padx=(0, 6))
        mid2.pack_propagate(False)
        ttk.Label(mid2, text="Исходы:", anchor="w").pack(fill="x")
        self.outcomes_list = tk.Listbox(mid2, exportselection=False)
        self.outcomes_list.pack(fill="both", expand=True)
        self.outcomes_list.bind("<<ListboxSelect>>", self._on_outcome_select)
        outcome_buttons = ttk.Frame(mid2)
        outcome_buttons.pack(fill="x", pady=4)
        ttk.Button(outcome_buttons, text="Добавить", command=self.outcome_add).pack(
            side="top", fill="x", pady=(0, 2)
        )
        ttk.Button(outcome_buttons, text="Удалить", command=self.outcome_delete).pack(
            side="top", fill="x"
        )
        self.outcomes_list.bind("<Delete>", lambda _event: self.outcome_delete())

        right = self.scrollable(self.tab_events)

        self.event_id_entry = self.entry_row(right, "ID события")
        self.event_title_entry = self.entry_row(right, "Заголовок")
        self.event_banner_entry = self.entry_row(right, "Баннер")
        self.event_scope_combo = self.combo_row(
            right, "Target scope", ["global", "region"]
        )
        self.event_desc_text = self.text_block(right, "Описание", height=3)
        self.event_filter_entry = self.entry_row(
            right, "Фильтр региона", label_width=16
        )
        ttk.Label(
            right, text='Формат: "security_max: 40, infrastructure_min: 25"',
            anchor="w",
        ).pack(fill="x")

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)
        self.option_id_entry = self.entry_row(right, "ID варианта")
        self.option_title_entry = self.entry_row(right, "Заголовок вар.")
        self.option_cost_entry = self.entry_row(right, "Цена варианта")
        self.option_effects = EffectsEditor(
            right, on_change=self.mark_dirty, title="Эффекты варианта:"
        )

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)
        self.outcome_id_entry = self.entry_row(right, "ID исхода")
        self.outcome_weight_entry = self.entry_row(right, "Вес исхода")
        self.outcome_banner_entry = self.entry_row(right, "Баннер исхода")
        self.outcome_effects = EffectsEditor(
            right, on_change=self.mark_dirty, title="Эффекты исхода:"
        )

        self.current_event: int | None = None
        self.current_option: int | None = None
        self.current_outcome: int | None = None

    def event_items(self) -> list[dict]:
        if not self.data:
            return []
        self.data.setdefault("events", [])
        return self.data["events"]

    def option_items(self) -> list[dict]:
        events = self.event_items()
        if self.current_event is None or self.current_event >= len(events):
            return []
        events[self.current_event].setdefault("options", [])
        return events[self.current_event]["options"]

    def outcome_items(self) -> list[dict]:
        options = self.option_items()
        if self.current_option is None or self.current_option >= len(options):
            return []
        options[self.current_option].setdefault("outcomes", [])
        return options[self.current_option]["outcomes"]

    def current_option_dict(self) -> dict | None:
        options = self.option_items()
        if self.current_option is None or self.current_option >= len(options):
            return None
        return options[self.current_option]

    def current_outcome_dict(self) -> dict | None:
        outcomes = self.outcome_items()
        if self.current_outcome is None or self.current_outcome >= len(outcomes):
            return None
        return outcomes[self.current_outcome]

    def reload_events_list(self) -> None:
        self.events_list.delete(0, "end")
        for event in self.event_items():
            self.events_list.insert(
                "end", f"{event.get('id', '?')} — {event.get('title', '')}"
            )

    def reload_options_list(self) -> None:
        self.options_list.delete(0, "end")
        for option in self.option_items():
            self.options_list.insert(
                "end", f"{option.get('id', '?')} — {option.get('title', '')}"
            )

    def reload_outcomes_list(self) -> None:
        self.outcomes_list.delete(0, "end")
        for outcome in self.outcome_items():
            self.outcomes_list.insert("end", outcome.get("id", "?"))

    def _on_event_select(self, _event: object = None) -> None:
        if self._loading:
            return
        self.flush_event_fields()
        self.current_event = self.selected_index(self.events_list)
        self.current_option = 0 if self.option_items() else None
        self.current_outcome = 0 if self.outcome_items() else None
        self.reload_options_list()
        self.reload_outcomes_list()
        if self.current_option is not None:
            self.options_list.selection_set(self.current_option)
        if self.current_outcome is not None:
            self.outcomes_list.selection_set(self.current_outcome)
        self.load_event_fields()

    def _on_option_select(self, _event: object = None) -> None:
        if self._loading:
            return
        self.flush_option_fields()
        self.current_option = self.selected_index(self.options_list)
        self.current_outcome = 0 if self.outcome_items() else None
        self.reload_outcomes_list()
        if self.current_outcome is not None:
            self.outcomes_list.selection_set(self.current_outcome)
        self.load_option_fields()

    def _on_outcome_select(self, _event: object = None) -> None:
        if self._loading:
            return
        self.flush_outcome_fields()
        self.current_outcome = self.selected_index(self.outcomes_list)
        self.load_outcome_fields()

    def load_event_fields(self) -> None:
        events = self.event_items()
        event = (
            events[self.current_event]
            if self.current_event is not None and self.current_event < len(events)
            else {}
        )
        self.event_id_entry.delete(0, "end")
        self.event_id_entry.insert(0, event.get("id", ""))
        self.event_title_entry.delete(0, "end")
        self.event_title_entry.insert(0, event.get("title", ""))
        self.event_banner_entry.delete(0, "end")
        self.event_banner_entry.insert(0, event.get("banner") or "")
        self.event_scope_combo.set(event.get("target_scope", "global"))
        self.event_desc_text.delete("1.0", "end")
        self.event_desc_text.insert("1.0", event.get("description", ""))
        self.event_filter_entry.delete(0, "end")
        self.event_filter_entry.insert(
            0, format_region_filter(event.get("default_region_filter", {}))
        )
        self.load_option_fields()

    def load_option_fields(self) -> None:
        option = self.current_option_dict() or {}
        self.option_id_entry.delete(0, "end")
        self.option_id_entry.insert(0, option.get("id", ""))
        self.option_title_entry.delete(0, "end")
        self.option_title_entry.insert(0, option.get("title", ""))
        self.option_cost_entry.delete(0, "end")
        self.option_cost_entry.insert(0, str(option.get("cost", 0)))
        self.option_effects.set(option.get("effects", []) or [])
        self.load_outcome_fields()

    def load_outcome_fields(self) -> None:
        outcome = self.current_outcome_dict() or {}
        self.outcome_id_entry.delete(0, "end")
        self.outcome_id_entry.insert(0, outcome.get("id", ""))
        self.outcome_weight_entry.delete(0, "end")
        self.outcome_weight_entry.insert(0, str(outcome.get("weight", 100)))
        self.outcome_banner_entry.delete(0, "end")
        self.outcome_banner_entry.insert(0, outcome.get("banner") or "")
        self.outcome_effects.set(outcome.get("effects", []) or [])

    def flush_event_fields(self) -> None:
        if self.current_event is None:
            return
        events = self.event_items()
        if self.current_event >= len(events):
            return
        banner = self.event_banner_entry.get().strip() or None
        region_filter, bad = parse_region_filter(self.event_filter_entry.get())
        if bad:
            self.set_status(f"Фильтр региона: не разобрано: {', '.join(bad)}.")
        events[self.current_event].update(
            {
                "id": self.event_id_entry.get().strip(),
                "title": self.event_title_entry.get().strip(),
                "description": self.event_desc_text.get("1.0", "end-1c"),
                "banner": banner,
                "target_scope": self.event_scope_combo.get().strip() or "global",
                "default_region_filter": region_filter,
            }
        )
        self.flush_option_fields()
        self.mark_dirty()

    def flush_option_fields(self) -> None:
        option = self.current_option_dict()
        if option is None:
            return
        option.update(
            {
                "id": self.option_id_entry.get().strip(),
                "title": self.option_title_entry.get().strip(),
                "cost": parse_int(self.option_cost_entry.get()),
                "effects": self.option_effects.get(),
            }
        )
        self.flush_outcome_fields()
        self.mark_dirty()

    def flush_outcome_fields(self) -> None:
        outcome = self.current_outcome_dict()
        if outcome is None:
            return
        banner = self.outcome_banner_entry.get().strip() or None
        outcome.update(
            {
                "id": self.outcome_id_entry.get().strip(),
                "weight": parse_int(self.outcome_weight_entry.get(), 100),
                "banner": banner,
                "effects": self.outcome_effects.get(),
            }
        )
        self.mark_dirty()

    def event_add(self) -> None:
        if not self.data:
            return
        self.flush_event_fields()
        self.event_items().append(
            {
                "id": "EVT_new",
                "title": "Новое событие",
                "description": "",
                "banner": None,
                "target_scope": "global",
                "default_region_filter": {},
                "options": [],
            }
        )
        self.reload_events_list()
        self.events_list.selection_clear(0, "end")
        self.events_list.selection_set("end")
        self.events_list.see("end")
        self._on_event_select()
        self.mark_dirty()
        self.set_status("Событие добавлено.")

    def event_delete(self) -> None:
        index = self.selected_index(self.events_list)
        if index is None:
            self.set_status("Выберите событие для удаления.")
            return
        self.current_event = None
        self.current_option = None
        self.current_outcome = None
        del self.event_items()[index]
        self.reload_events_list()
        self.reload_options_list()
        self.reload_outcomes_list()
        self.load_event_fields()
        self.mark_dirty()
        self.set_status("Событие удалено.")

    def option_add(self) -> None:
        if self.current_event is None:
            messagebox.showinfo("Варианты", "Сначала выберите событие.")
            return
        self.flush_option_fields()
        self.option_items().append(
            {
                "id": "new",
                "title": "Новый вариант",
                "cost": 0,
                "effects": [],
                "outcomes": [],
            }
        )
        self.reload_options_list()
        self.options_list.selection_clear(0, "end")
        self.options_list.selection_set("end")
        self.options_list.see("end")
        self._on_option_select()
        self.mark_dirty()
        self.set_status("Вариант добавлен.")

    def option_delete(self) -> None:
        index = self.selected_index(self.options_list)
        if index is None:
            self.set_status("Выберите вариант для удаления.")
            return
        self.current_option = None
        self.current_outcome = None
        del self.option_items()[index]
        self.reload_options_list()
        self.reload_outcomes_list()
        self.load_option_fields()
        self.mark_dirty()
        self.set_status("Вариант удалён.")

    def outcome_add(self) -> None:
        if self.current_option is None:
            messagebox.showinfo("Исходы", "Сначала выберите вариант.")
            return
        self.flush_outcome_fields()
        self.outcome_items().append(
            {"id": "new", "weight": 100, "banner": None, "effects": []}
        )
        self.reload_outcomes_list()
        self.outcomes_list.selection_clear(0, "end")
        self.outcomes_list.selection_set("end")
        self.outcomes_list.see("end")
        self._on_outcome_select()
        self.mark_dirty()
        self.set_status("Исход добавлен.")

    def outcome_delete(self) -> None:
        index = self.selected_index(self.outcomes_list)
        if index is None:
            self.set_status("Выберите исход для удаления.")
            return
        self.current_outcome = None
        del self.outcome_items()[index]
        self.reload_outcomes_list()
        self.load_outcome_fields()
        self.mark_dirty()
        self.set_status("Исход удалён.")

    # ---------- вкладка "Al Nazra" ----------

    def _build_alnazra_tab(self) -> None:
        buttons, self.intentions_list = self.list_panel(self.tab_alnazra)
        self.list_actions(
            buttons, self.intentions_list, self.intention_add, self.intention_delete
        )
        self.intentions_list.bind("<<ListboxSelect>>", self._on_intention_select)

        mid_buttons, self.alnazra_ops_list = self.list_panel(self.tab_alnazra)
        self.list_actions(
            mid_buttons, self.alnazra_ops_list, self.alnazra_op_add, self.alnazra_op_delete
        )
        self.alnazra_ops_list.bind("<<ListboxSelect>>", self._on_operation_select)

        right = self.scrollable(self.tab_alnazra)

        ttk.Label(right, text="Намерение:", anchor="w").pack(fill="x")
        self.intention_id_entry = self.entry_row(right, "ID")
        self.intention_name_entry = self.entry_row(right, "Название")
        self.intention_desc_text = self.text_block(right, "Описание", height=3)

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)
        ttk.Label(right, text="Операция:", anchor="w").pack(fill="x")
        self.alnazra_op_id_entry = self.entry_row(right, "ID")
        self.alnazra_op_name_entry = self.entry_row(right, "Название")
        self.alnazra_op_support_entry = self.entry_row(right, "Мин. поддержка")

        ttk.Label(right, text="Теги:", anchor="w").pack(fill="x", pady=(6, 2))
        self.alnazra_tags_frame = ttk.Frame(right)
        self.alnazra_tags_frame.pack(fill="x")
        self.alnazra_tag_vars: dict[str, tk.BooleanVar] = {}
        for tag in ALNAZRA_TAGS:
            var = tk.BooleanVar(value=False)
            self.alnazra_tag_vars[tag] = var
            ttk.Checkbutton(self.alnazra_tags_frame, text=tag, variable=var).pack(
                anchor="w"
            )

        self.alnazra_op_effects = EffectsEditor(
            right, on_change=self.mark_dirty, title="Глобальные эффекты:"
        )
        self.alnazra_op_region_effects = EffectsEditor(
            right, on_change=self.mark_dirty, title="Региональные эффекты:"
        )
        self.alnazra_modifier_combo = self.combo_row(
            right, "Модификатор", ["", "rumor"]
        )

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)
        self.alnazra_hideout_entry = self.entry_row(right, "Порог убежища")
        self.alnazra_hideout_sec_entry = self.entry_row(right, "Убежище: макс. sec")

        self.current_intention: int | None = None
        self.current_operation: int | None = None

    def alnazra_data(self) -> dict:
        if not self.data:
            return {}
        self.data.setdefault("al_nazra", {})
        return self.data["al_nazra"]

    def intention_items(self) -> list[dict]:
        data = self.alnazra_data()
        if not isinstance(data, dict):
            return []
        data.setdefault("intentions", [])
        return data["intentions"]

    def alnazra_op_items(self) -> list[dict]:
        data = self.alnazra_data()
        if not isinstance(data, dict):
            return []
        data.setdefault("operations", [])
        return data["operations"]

    def reload_intentions_list(self) -> None:
        self.intentions_list.delete(0, "end")
        for intention in self.intention_items():
            self.intentions_list.insert(
                "end", f"{intention.get('id', '?')} — {intention.get('name', '')}"
            )

    def reload_alnazra_ops_list(self) -> None:
        self.alnazra_ops_list.delete(0, "end")
        for operation in self.alnazra_op_items():
            self.alnazra_ops_list.insert(
                "end", f"{operation.get('id', '?')} — {operation.get('name', '')}"
            )

    def _on_intention_select(self, _event: object = None) -> None:
        if self._loading:
            return
        self.flush_intention_fields()
        self.current_intention = self.selected_index(self.intentions_list)
        self.load_intention_fields()

    def _on_operation_select(self, _event: object = None) -> None:
        if self._loading:
            return
        self.flush_operation_fields()
        self.current_operation = self.selected_index(self.alnazra_ops_list)
        self.load_operation_fields()

    def load_intention_fields(self) -> None:
        items = self.intention_items()
        intention = (
            items[self.current_intention]
            if self.current_intention is not None and self.current_intention < len(items)
            else {}
        )
        self.intention_id_entry.delete(0, "end")
        self.intention_id_entry.insert(0, intention.get("id", ""))
        self.intention_name_entry.delete(0, "end")
        self.intention_name_entry.insert(0, intention.get("name", ""))
        self.intention_desc_text.delete("1.0", "end")
        self.intention_desc_text.insert("1.0", intention.get("description", ""))

    def load_operation_fields(self) -> None:
        items = self.alnazra_op_items()
        operation = (
            items[self.current_operation]
            if self.current_operation is not None and self.current_operation < len(items)
            else {}
        )
        data = self.alnazra_data()

        self.alnazra_op_id_entry.delete(0, "end")
        self.alnazra_op_id_entry.insert(0, operation.get("id", ""))
        self.alnazra_op_name_entry.delete(0, "end")
        self.alnazra_op_name_entry.insert(0, operation.get("name", ""))
        self.alnazra_op_support_entry.delete(0, "end")
        self.alnazra_op_support_entry.insert(0, str(operation.get("min_support", 0)))

        tags = set(operation.get("tags", []) or [])
        for tag, var in self.alnazra_tag_vars.items():
            var.set(tag in tags)

        self.alnazra_op_effects.set(operation.get("effects", []) or [])
        self.alnazra_op_region_effects.set(operation.get("region_effects", []) or [])
        self.alnazra_modifier_combo.set(operation.get("region_modifier", "") or "")

        self.alnazra_hideout_entry.delete(0, "end")
        self.alnazra_hideout_entry.insert(
            0, str(data.get("hideout_threshold", 40) if isinstance(data, dict) else 40)
        )
        self.alnazra_hideout_sec_entry.delete(0, "end")
        self.alnazra_hideout_sec_entry.insert(
            0,
            str(data.get("hideout_security_max", 30) if isinstance(data, dict) else 30),
        )

    def flush_intention_fields(self) -> None:
        if self.current_intention is None:
            return
        items = self.intention_items()
        if self.current_intention >= len(items):
            return
        items[self.current_intention] = {
            "id": self.intention_id_entry.get().strip(),
            "name": self.intention_name_entry.get().strip(),
            "description": self.intention_desc_text.get("1.0", "end-1c"),
        }
        self.mark_dirty()

    def flush_operation_fields(self) -> None:
        data = self.alnazra_data()
        if isinstance(data, dict):
            data["hideout_threshold"] = parse_int(self.alnazra_hideout_entry.get(), 40)
            data["hideout_security_max"] = parse_int(
                self.alnazra_hideout_sec_entry.get(), 30
            )
        if self.current_operation is None:
            return
        items = self.alnazra_op_items()
        if self.current_operation >= len(items):
            return
        items[self.current_operation] = {
            "id": self.alnazra_op_id_entry.get().strip(),
            "name": self.alnazra_op_name_entry.get().strip(),
            "min_support": parse_int(self.alnazra_op_support_entry.get()),
            "tags": [tag for tag, var in self.alnazra_tag_vars.items() if var.get()],
            "effects": self.alnazra_op_effects.get(),
            "region_effects": self.alnazra_op_region_effects.get(),
            "region_modifier": self.alnazra_modifier_combo.get().strip(),
        }
        self.mark_dirty()

    def intention_add(self) -> None:
        if not self.data:
            return
        self.flush_intention_fields()
        self.intention_items().append(
            {"id": "new_intent", "name": "Новое намерение", "description": ""}
        )
        self.reload_intentions_list()
        self.intentions_list.selection_clear(0, "end")
        self.intentions_list.selection_set("end")
        self.intentions_list.see("end")
        self._on_intention_select()
        self.mark_dirty()
        self.set_status("Намерение добавлено.")

    def intention_delete(self) -> None:
        index = self.selected_index(self.intentions_list)
        if index is None:
            self.set_status("Выберите намерение для удаления.")
            return
        self.current_intention = None
        del self.intention_items()[index]
        self.reload_intentions_list()
        self.load_intention_fields()
        self.mark_dirty()
        self.set_status("Намерение удалено.")

    def alnazra_op_add(self) -> None:
        if not self.data:
            return
        self.flush_operation_fields()
        self.alnazra_op_items().append(
            {
                "id": "new_op",
                "name": "Новая операция",
                "min_support": 0,
                "tags": [],
                "effects": [],
                "region_effects": [],
                "region_modifier": "",
            }
        )
        self.reload_alnazra_ops_list()
        self.alnazra_ops_list.selection_clear(0, "end")
        self.alnazra_ops_list.selection_set("end")
        self.alnazra_ops_list.see("end")
        self._on_operation_select()
        self.mark_dirty()
        self.set_status("Операция Al Nazra добавлена.")

    def alnazra_op_delete(self) -> None:
        index = self.selected_index(self.alnazra_ops_list)
        if index is None:
            self.set_status("Выберите операцию для удаления.")
            return
        self.current_operation = None
        del self.alnazra_op_items()[index]
        self.reload_alnazra_ops_list()
        self.load_operation_fields()
        self.mark_dirty()
        self.set_status("Операция Al Nazra удалена.")

    # ---------- вкладка "Изображения" ----------

    def _build_images_tab(self) -> None:
        top = ttk.Frame(self.tab_images)
        top.pack(fill="x", padx=4, pady=4)

        ttk.Label(top, text="Папка с картинками:").pack(side="left")
        self.images_folder_var = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.images_folder_var).pack(
            side="left", fill="x", expand=True, padx=4
        )
        ttk.Button(top, text="Обзор...", command=self.choose_images_folder).pack(
            side="left"
        )

        actions = ttk.Frame(self.tab_images)
        actions.pack(fill="x", padx=4, pady=4)
        self.global_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            actions, text="Включая game_info.jpg / game_reg.jpg", variable=self.global_var
        ).pack(side="left")
        ttk.Button(actions, text="Обновить", command=self.refresh_images).pack(
            side="left", padx=8
        )
        ttk.Button(actions, text="Экспорт списка...", command=self.export_images).pack(
            side="left"
        )
        ttk.Button(actions, text="Копировать", command=self.copy_images).pack(
            side="left", padx=8
        )

        columns = ("name", "usage", "status")
        self.images_tree = ttk.Treeview(
            self.tab_images, columns=columns, show="headings", height=20
        )
        self.images_tree.heading("name", text="Файл")
        self.images_tree.heading("usage", text="Используется")
        self.images_tree.heading("status", text="Статус")
        self.images_tree.column("name", width=240)
        self.images_tree.column("usage", width=560)
        self.images_tree.column("status", width=120)
        self.images_tree.pack(fill="both", expand=True, padx=4, pady=4)

    def choose_images_folder(self) -> None:
        folder = filedialog.askdirectory(title="Папка с изображениями")
        if folder:
            self.images_folder_var.set(folder)
            self.refresh_images()

    def _collected_images(self) -> list[dict]:
        self.flush_all()
        if not self.data:
            return []

        return collect_images(self.data, include_global=self.global_var.get())

    def refresh_images(self) -> None:
        for row in self.images_tree.get_children():
            self.images_tree.delete(row)

        if not self.data:
            self.set_status("Сначала откройте пак.")
            return

        folder = self.images_folder_var.get().strip()
        missing = 0

        for item in self._collected_images():
            if folder and os.path.isfile(os.path.join(folder, item["name"])):
                status = "✅ есть"
            elif folder:
                status = "❌ нет"
                missing += 1
            else:
                status = "—"

            self.images_tree.insert(
                "", "end", values=(item["name"], "; ".join(item["usages"]), status)
            )

        if folder:
            self.set_status(f"Изображений не хватает: {missing}.")
        else:
            self.set_status("Укажите папку с картинками, чтобы проверить наличие файлов.")

    def export_images(self) -> None:
        items = self._collected_images()
        if not items:
            messagebox.showinfo("Экспорт", "Нет изображений для экспорта.")
            return

        path = filedialog.asksaveasfilename(
            title="Сохранить список изображений",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt")],
            initialfile="images_todo.txt",
        )
        if not path:
            return

        folder = self.images_folder_var.get().strip()
        with open(path, "w", encoding="utf-8") as fh:
            for item in items:
                exists = (
                    os.path.isfile(os.path.join(folder, item["name"])) if folder else None
                )
                mark = " [НЕТ ФАЙЛА]" if exists is False else ""
                fh.write(f"{item['name']}{mark}\n")
                for usage in item["usages"]:
                    fh.write(f"    - {usage}\n")

        self.set_status(f"Список сохранён: {path}")

    def copy_images(self) -> None:
        items = self._collected_images()
        if not items:
            return

        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(item["name"] for item in items))
        self.set_status("Список изображений скопирован в буфер обмена.")

    # ---------- файл и валидация ----------

    def _on_tab_changed(self, _event: object = None) -> None:
        if not self.data:
            return

        current = self.notebook.tab(self.notebook.select(), "text")
        if current == "Роли":
            self.flush_role_fields()
            self.refresh_role_actions_box()
            self.load_role_fields()
        elif current == "Технологии":
            self.flush_tech_fields()
            self.refresh_tech_boxes()
            self.load_tech_fields()
        elif current == "Действия":
            self.flush_action_fields()
            self.refresh_action_role_values()
            self.refresh_action_techs_box()
            self.load_action_fields()
        elif current == "Изображения":
            self.refresh_images()

    def flush_all(self) -> None:
        self.flush_pack_tab()
        self.flush_role_fields()
        self.reload_roles_list()
        self.flush_region_fields()
        self.reload_regions_list()
        self.flush_tech_fields()
        self.reload_techs_list()
        self.flush_action_fields()
        self.reload_actions_list()
        self.flush_event_fields()
        self.reload_events_list()
        self.reload_options_list()
        self.reload_outcomes_list()
        self.flush_intention_fields()
        self.flush_operation_fields()
        self.reload_intentions_list()
        self.reload_alnazra_ops_list()

    def reload_all(self) -> None:
        self._loading = True
        try:
            self.load_pack_tab()

            self.current_role = None
            self.refresh_role_actions_box()
            self.reload_roles_list()
            self.load_role_fields()

            self.current_region = None
            self.reload_regions_list()
            self.load_region_fields()

            self.current_tech = None
            self.refresh_tech_boxes()
            self.reload_techs_list()
            self.load_tech_fields()

            self.current_action = None
            self.refresh_action_role_values()
            self.refresh_action_techs_box()
            self.reload_actions_list()
            self.load_action_fields()

            self.current_event = None
            self.current_option = None
            self.current_outcome = None
            self.reload_events_list()
            self.reload_options_list()
            self.reload_outcomes_list()
            self.load_event_fields()

            self.current_intention = None
            self.current_operation = None
            self.reload_intentions_list()
            self.reload_alnazra_ops_list()
            self.load_intention_fields()
            self.load_operation_fields()
        finally:
            self._loading = False

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True

        return messagebox.askyesno(
            "Несохранённые изменения",
            "Есть несохранённые изменения. Продолжить без сохранения?",
        )

    def on_new(self) -> None:
        if not self.confirm_discard():
            return

        self.data = new_pack_template()
        self.path = None
        self.dirty = True
        self._refresh_title()
        self.reload_all()
        self.set_status("Новый пак. Заполните вкладки и сохраните через Файл → Сохранить.")

    def on_open(self) -> None:
        if not self.confirm_discard():
            return

        path = filedialog.askopenfilename(
            title="Открыть TARBIN-пак",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
        )
        if not path:
            return

        try:
            data = load_pack_file(path)
        except Exception as exc:
            messagebox.showerror("Открытие", f"Не удалось открыть файл:\n{exc}")
            return

        self.data = data
        self.path = path
        self.dirty = False
        self._refresh_title()
        self.reload_all()

        errors = validate_pack(data)
        if errors:
            self.set_status(f"Открыт с ошибками валидации: {len(errors)}. См. Пак → Проверить.")
        else:
            self.set_status(f"Открыт: {path}")

    def on_save(self) -> None:
        if not self.data:
            messagebox.showinfo("Сохранение", "Сначала откройте пак.")
            return

        if not self.path:
            self.on_save_as()
            return

        self.flush_all()
        errors = validate_pack(self.data)
        if errors:
            messagebox.showerror(
                "Пак невалиден",
                "Исправьте ошибки перед сохранением:\n\n" + "\n".join(errors[:20]),
            )
            self.set_status(f"Ошибок валидации: {len(errors)}.")
            return

        try:
            save_pack_file(self.path, self.data)
        except Exception as exc:
            messagebox.showerror("Сохранение", f"Не удалось сохранить:\n{exc}")
            return

        self.dirty = False
        self._refresh_title()
        self.set_status(f"Сохранено: {self.path}")

    def on_save_as(self) -> None:
        if not self.data:
            messagebox.showinfo("Сохранение", "Сначала откройте пак.")
            return

        path = filedialog.asksaveasfilename(
            title="Сохранить TARBIN-пак как",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return

        self.path = path
        self._refresh_title()
        self.on_save()

    def on_validate(self) -> None:
        if not self.data:
            messagebox.showinfo("Проверка", "Сначала откройте пак.")
            return

        self.flush_all()
        errors = validate_pack(self.data)

        if not errors:
            messagebox.showinfo("Проверка", "Пак валиден ✅")
            self.set_status("Пак валиден ✅")
        else:
            messagebox.showerror(
                "Ошибки валидации", "\n".join(errors[:30])
            )
            self.set_status(f"Ошибок валидации: {len(errors)}.")

    def on_exit(self) -> None:
        if self.confirm_discard():
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    PackEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
