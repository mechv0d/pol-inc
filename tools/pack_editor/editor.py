"""Графический редактор GamePack (tkinter).

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

from tools.pack_editor.pack_model import (  # noqa: E402
    collect_images,
    load_pack_file,
    new_pack_template,
    save_pack_file,
    validate_pack,
)


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


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


class PackEditorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Редактор GamePack")
        self.root.geometry("1020x720")

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
        self.tab_factions = ttk.Frame(self.notebook)
        self.tab_alliances = ttk.Frame(self.notebook)
        self.tab_abilities = ttk.Frame(self.notebook)
        self.tab_events = ttk.Frame(self.notebook)
        self.tab_images = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_pack, text="Пак")
        self.notebook.add(self.tab_factions, text="Фракции")
        self.notebook.add(self.tab_alliances, text="Альянсы")
        self.notebook.add(self.tab_abilities, text="Способности")
        self.notebook.add(self.tab_events, text="События")
        self.notebook.add(self.tab_images, text="Изображения")

        self._build_pack_tab()
        self._build_factions_tab()
        self._build_alliances_tab()
        self._build_abilities_tab()
        self._build_events_tab()
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
        self.root.title(f"Редактор GamePack — {name}{star}")

    def pack_faction_ids(self) -> list[str]:
        if not self.data:
            return []

        return [
            faction.get("id")
            for faction in self.data.get("factions", []) or []
            if isinstance(faction, dict) and faction.get("id")
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

    @staticmethod
    def selected_index(listbox: tk.Listbox) -> int | None:
        selection = listbox.curselection()
        return selection[0] if selection else None

    # ---------- вкладка "Пак" ----------

    def _build_pack_tab(self) -> None:
        self.pack_id_entry = self.entry_row(self.tab_pack, "ID пака")
        self.pack_name_entry = self.entry_row(self.tab_pack, "Название")
        self.pack_desc_text = self.text_block(self.tab_pack, "Описание", height=5)
        self.pack_durations_entry = self.entry_row(
            self.tab_pack, "Длительности (через ,)", label_width=24
        )

    def load_pack_tab(self) -> None:
        if not self.data:
            return

        self.pack_id_entry.delete(0, "end")
        self.pack_id_entry.insert(0, self.data.get("id", ""))
        self.pack_name_entry.delete(0, "end")
        self.pack_name_entry.insert(0, self.data.get("name", ""))
        self.pack_desc_text.delete("1.0", "end")
        self.pack_desc_text.insert("1.0", self.data.get("description", ""))
        self.pack_durations_entry.delete(0, "end")
        self.pack_durations_entry.insert(
            0, ", ".join(str(d) for d in self.data.get("durations", []) or [])
        )

    def flush_pack_tab(self) -> None:
        if not self.data:
            return

        self.data["id"] = self.pack_id_entry.get().strip()
        self.data["name"] = self.pack_name_entry.get().strip()
        self.data["description"] = self.pack_desc_text.get("1.0", "end-1c")

        raw = self.pack_durations_entry.get().strip()
        if raw:
            try:
                self.data["durations"] = [
                    int(part.strip()) for part in raw.split(",") if part.strip()
                ]
            except ValueError:
                self.set_status("Длительности: нужны целые числа через запятую.")

    # ---------- вкладка "Фракции" ----------

    def _build_factions_tab(self) -> None:
        buttons, self.factions_list = self.list_panel(self.tab_factions)
        ttk.Button(buttons, text="+", width=4, command=self.faction_add).pack(side="left")
        ttk.Button(buttons, text="-", width=4, command=self.faction_delete).pack(
            side="left", padx=4
        )
        self.factions_list.bind("<<ListboxSelect>>", self._on_faction_select)

        right = ttk.Frame(self.tab_factions)
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(right, text="ID", width=16, anchor="w").pack(fill="x")
        self.faction_id_entry = ttk.Entry(right)
        self.faction_id_entry.pack(fill="x", pady=2)

        self.faction_name_entry = self.entry_row(right, "Название")
        self.faction_color_entry = self.entry_row(right, "Цвет")
        self.faction_emoji_entry = self.entry_row(right, "Эмодзи")
        self.faction_feature_text = self.text_block(right, "Особенность", height=5)

        self.current_faction: int | None = None

    def faction_items(self) -> list[dict]:
        if not self.data:
            return []

        self.data.setdefault("factions", [])
        return self.data["factions"]

    def reload_factions_list(self) -> None:
        self.factions_list.delete(0, "end")
        for faction in self.faction_items():
            self.factions_list.insert(
                "end", f"{faction.get('id', '?')} — {faction.get('name', '')}"
            )

    def _on_faction_select(self, _event: object = None) -> None:
        if self._loading:
            return

        self.flush_faction_fields()
        index = self.selected_index(self.factions_list)
        self.current_faction = index
        self.load_faction_fields()

    def load_faction_fields(self) -> None:
        items = self.faction_items()
        faction = (
            items[self.current_faction]
            if self.current_faction is not None and self.current_faction < len(items)
            else {}
        )

        self.faction_id_entry.delete(0, "end")
        self.faction_id_entry.insert(0, faction.get("id", ""))
        self.faction_name_entry.delete(0, "end")
        self.faction_name_entry.insert(0, faction.get("name", ""))
        self.faction_color_entry.delete(0, "end")
        self.faction_color_entry.insert(0, faction.get("color", ""))
        self.faction_emoji_entry.delete(0, "end")
        self.faction_emoji_entry.insert(0, faction.get("emoji", ""))
        self.faction_feature_text.delete("1.0", "end")
        self.faction_feature_text.insert("1.0", faction.get("feature", ""))

    def flush_faction_fields(self) -> None:
        if self.current_faction is None:
            return

        items = self.faction_items()
        if self.current_faction >= len(items):
            return

        items[self.current_faction] = {
            "id": self.faction_id_entry.get().strip(),
            "name": self.faction_name_entry.get().strip(),
            "color": self.faction_color_entry.get().strip(),
            "emoji": self.faction_emoji_entry.get().strip(),
            "feature": self.faction_feature_text.get("1.0", "end-1c"),
        }
        self.mark_dirty()

    def faction_add(self) -> None:
        if not self.data:
            return

        self.flush_faction_fields()
        self.faction_items().append(
            {"id": "new", "name": "Новая фракция", "color": "", "emoji": "", "feature": ""}
        )
        self.reload_factions_list()
        self.factions_list.selection_clear(0, "end")
        self.factions_list.selection_set("end")
        self.factions_list.see("end")
        self._on_faction_select()
        self.mark_dirty()
        self.refresh_alliance_faction_box()

    def faction_delete(self) -> None:
        index = self.selected_index(self.factions_list)
        if index is None:
            return

        self.current_faction = None
        del self.faction_items()[index]
        self.reload_factions_list()
        self.load_faction_fields()
        self.mark_dirty()
        self.refresh_alliance_faction_box()

    # ---------- вкладка "Альянсы" ----------

    def _build_alliances_tab(self) -> None:
        buttons, self.alliances_list = self.list_panel(self.tab_alliances)
        ttk.Button(buttons, text="+", width=4, command=self.alliance_add).pack(side="left")
        ttk.Button(buttons, text="-", width=4, command=self.alliance_delete).pack(
            side="left", padx=4
        )
        self.alliances_list.bind("<<ListboxSelect>>", self._on_alliance_select)

        right = ttk.Frame(self.tab_alliances)
        right.pack(side="left", fill="both", expand=True)

        self.alliance_id_entry = self.entry_row(right, "ID")
        self.alliance_name_entry = self.entry_row(right, "Название")

        ttk.Label(right, text="Фракции альянса:", anchor="w").pack(fill="x", pady=(6, 2))
        self.alliance_factions_frame = ttk.Frame(right)
        self.alliance_factions_frame.pack(fill="x")

        self.alliance_faction_vars: dict[str, tk.BooleanVar] = {}
        self.current_alliance: int | None = None

    def alliance_items(self) -> list[dict]:
        if not self.data:
            return []

        self.data.setdefault("alliances", [])
        return self.data["alliances"]

    def reload_alliances_list(self) -> None:
        self.alliances_list.delete(0, "end")
        for alliance in self.alliance_items():
            self.alliances_list.insert(
                "end", f"{alliance.get('id', '?')} — {alliance.get('name', '')}"
            )

    def refresh_alliance_faction_box(self) -> None:
        for widget in self.alliance_factions_frame.winfo_children():
            widget.destroy()

        self.alliance_faction_vars = {}
        for faction_id in self.pack_faction_ids():
            var = tk.BooleanVar(value=False)
            self.alliance_faction_vars[faction_id] = var
            ttk.Checkbutton(
                self.alliance_factions_frame, text=faction_id, variable=var
            ).pack(anchor="w")

        self.load_alliance_fields()

    def _on_alliance_select(self, _event: object = None) -> None:
        if self._loading:
            return

        self.flush_alliance_fields()
        self.current_alliance = self.selected_index(self.alliances_list)
        self.load_alliance_fields()

    def load_alliance_fields(self) -> None:
        items = self.alliance_items()
        alliance = (
            items[self.current_alliance]
            if self.current_alliance is not None and self.current_alliance < len(items)
            else {}
        )

        self.alliance_id_entry.delete(0, "end")
        self.alliance_id_entry.insert(0, alliance.get("id", ""))
        self.alliance_name_entry.delete(0, "end")
        self.alliance_name_entry.insert(0, alliance.get("name", ""))

        selected = set(alliance.get("factions", []) or [])
        for faction_id, var in self.alliance_faction_vars.items():
            var.set(faction_id in selected)

    def flush_alliance_fields(self) -> None:
        if self.current_alliance is None:
            return

        items = self.alliance_items()
        if self.current_alliance >= len(items):
            return

        items[self.current_alliance] = {
            "id": self.alliance_id_entry.get().strip(),
            "name": self.alliance_name_entry.get().strip(),
            "factions": [
                faction_id
                for faction_id, var in self.alliance_faction_vars.items()
                if var.get()
            ],
        }
        self.mark_dirty()

    def alliance_add(self) -> None:
        if not self.data:
            return

        self.flush_alliance_fields()
        self.alliance_items().append({"id": "new", "name": "Новый альянс", "factions": []})
        self.reload_alliances_list()
        self.alliances_list.selection_clear(0, "end")
        self.alliances_list.selection_set("end")
        self.alliances_list.see("end")
        self._on_alliance_select()
        self.mark_dirty()

    def alliance_delete(self) -> None:
        index = self.selected_index(self.alliances_list)
        if index is None:
            return

        self.current_alliance = None
        del self.alliance_items()[index]
        self.reload_alliances_list()
        self.load_alliance_fields()
        self.mark_dirty()

    # ---------- вкладка "Способности" ----------

    def _build_abilities_tab(self) -> None:
        buttons, self.abilities_list = self.list_panel(self.tab_abilities)
        ttk.Button(buttons, text="+", width=4, command=self.ability_add).pack(side="left")
        ttk.Button(buttons, text="-", width=4, command=self.ability_delete).pack(
            side="left", padx=4
        )
        self.abilities_list.bind("<<ListboxSelect>>", self._on_ability_select)

        right = ttk.Frame(self.tab_abilities)
        right.pack(side="left", fill="both", expand=True)

        self.ability_id_entry = self.entry_row(right, "ID")
        self.ability_name_entry = self.entry_row(right, "Название")
        self.ability_desc_text = self.text_block(right, "Описание", height=4)
        self.ability_cost_p_entry = self.entry_row(right, "Цена: проценты")
        self.ability_cost_v_entry = self.entry_row(right, "Цена: влияние")

        self.ability_targeted_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            right, text="Таргетированная", variable=self.ability_targeted_var
        ).pack(anchor="w", pady=2)

        ttk.Label(right, text="Фракция (пусто — любая)", anchor="w").pack(fill="x")
        self.ability_faction_combo = ttk.Combobox(right, values=[""])
        self.ability_faction_combo.pack(fill="x", pady=2)

        self.current_ability: int | None = None

    def refresh_ability_faction_values(self) -> None:
        current = self.ability_faction_combo.get()
        self.ability_faction_combo["values"] = [""] + self.pack_faction_ids()
        self.ability_faction_combo.set(current)

    def ability_items(self) -> list[dict]:
        if not self.data:
            return []

        self.data.setdefault("abilities", [])
        return self.data["abilities"]

    def reload_abilities_list(self) -> None:
        self.abilities_list.delete(0, "end")
        for ability in self.ability_items():
            self.abilities_list.insert(
                "end", f"{ability.get('id', '?')} — {ability.get('name', '')}"
            )

    def _on_ability_select(self, _event: object = None) -> None:
        if self._loading:
            return

        self.flush_ability_fields()
        self.current_ability = self.selected_index(self.abilities_list)
        self.load_ability_fields()

    def load_ability_fields(self) -> None:
        items = self.ability_items()
        ability = (
            items[self.current_ability]
            if self.current_ability is not None and self.current_ability < len(items)
            else {}
        )
        cost = ability.get("cost", {}) if isinstance(ability.get("cost"), dict) else {}

        self.ability_id_entry.delete(0, "end")
        self.ability_id_entry.insert(0, ability.get("id", ""))
        self.ability_name_entry.delete(0, "end")
        self.ability_name_entry.insert(0, ability.get("name", ""))
        self.ability_desc_text.delete("1.0", "end")
        self.ability_desc_text.insert("1.0", ability.get("description", ""))
        self.ability_cost_p_entry.delete(0, "end")
        self.ability_cost_p_entry.insert(0, str(cost.get("percent", 0)))
        self.ability_cost_v_entry.delete(0, "end")
        self.ability_cost_v_entry.insert(0, str(cost.get("influence", 0)))
        self.ability_targeted_var.set(bool(ability.get("targeted", False)))
        self.ability_faction_combo.set(ability.get("faction") or "")

    def flush_ability_fields(self) -> None:
        if self.current_ability is None:
            return

        items = self.ability_items()
        if self.current_ability >= len(items):
            return

        faction = self.ability_faction_combo.get().strip() or None
        items[self.current_ability] = {
            "id": self.ability_id_entry.get().strip(),
            "name": self.ability_name_entry.get().strip(),
            "description": self.ability_desc_text.get("1.0", "end-1c"),
            "cost": {
                "percent": parse_int(self.ability_cost_p_entry.get()),
                "influence": parse_int(self.ability_cost_v_entry.get()),
            },
            "targeted": bool(self.ability_targeted_var.get()),
            "faction": faction,
        }
        self.mark_dirty()

    def ability_add(self) -> None:
        if not self.data:
            return

        self.flush_ability_fields()
        self.ability_items().append(
            {
                "id": "new",
                "name": "Новая способность",
                "description": "",
                "cost": {"percent": 0, "influence": 0},
                "targeted": False,
                "faction": None,
            }
        )
        self.reload_abilities_list()
        self.abilities_list.selection_clear(0, "end")
        self.abilities_list.selection_set("end")
        self.abilities_list.see("end")
        self._on_ability_select()
        self.mark_dirty()

    def ability_delete(self) -> None:
        index = self.selected_index(self.abilities_list)
        if index is None:
            return

        self.current_ability = None
        del self.ability_items()[index]
        self.reload_abilities_list()
        self.load_ability_fields()
        self.mark_dirty()

    # ---------- вкладка "События" ----------

    def _build_events_tab(self) -> None:
        buttons, self.events_list = self.list_panel(self.tab_events)
        ttk.Button(buttons, text="+", width=4, command=self.event_add).pack(side="left")
        ttk.Button(buttons, text="-", width=4, command=self.event_delete).pack(
            side="left", padx=4
        )
        self.events_list.bind("<<ListboxSelect>>", self._on_event_select)

        middle = ttk.Frame(self.tab_events, width=200)
        middle.pack(side="left", fill="y", padx=(0, 6))
        middle.pack_propagate(False)
        ttk.Label(middle, text="Исходы:", anchor="w").pack(fill="x")
        self.outcomes_list = tk.Listbox(middle, exportselection=False)
        self.outcomes_list.pack(fill="both", expand=True)
        self.outcomes_list.bind("<<ListboxSelect>>", self._on_outcome_select)

        outcome_buttons = ttk.Frame(middle)
        outcome_buttons.pack(fill="x", pady=4)
        ttk.Button(outcome_buttons, text="+", width=4, command=self.outcome_add).pack(
            side="left"
        )
        ttk.Button(outcome_buttons, text="-", width=4, command=self.outcome_delete).pack(
            side="left", padx=4
        )

        right = ttk.Frame(self.tab_events)
        right.pack(side="left", fill="both", expand=True)

        self.event_id_entry = self.entry_row(right, "ID события")
        self.event_title_entry = self.entry_row(right, "Заголовок")
        self.event_banner_entry = self.entry_row(right, "Баннер")
        self.event_desc_text = self.text_block(right, "Описание", height=4)

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)

        self.outcome_id_entry = self.entry_row(right, "ID исхода")
        self.outcome_banner_entry = self.entry_row(right, "Баннер исхода")
        self.outcome_desc_text = self.text_block(right, "Описание исхода", height=3)

        ttk.Label(right, text="Эффекты (проценты / влияние):", anchor="w").pack(fill="x")
        self.effects_frame = ttk.Frame(right)
        self.effects_frame.pack(fill="x")

        self.current_event: int | None = None
        self.current_outcome: int | None = None
        self.effect_vars: dict[str, tuple[ttk.Entry, ttk.Entry]] = {}

    def event_items(self) -> list[dict]:
        if not self.data:
            return []

        self.data.setdefault("events", [])
        return self.data["events"]

    def outcome_items(self) -> list[dict]:
        events = self.event_items()
        if self.current_event is None or self.current_event >= len(events):
            return []

        events[self.current_event].setdefault("outcomes", [])
        return events[self.current_event]["outcomes"]

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

    def reload_outcomes_list(self) -> None:
        self.outcomes_list.delete(0, "end")
        for outcome in self.outcome_items():
            self.outcomes_list.insert("end", outcome.get("id", "?"))

    def _on_event_select(self, _event: object = None) -> None:
        if self._loading:
            return

        self.flush_event_fields()
        self.current_event = self.selected_index(self.events_list)
        self.current_outcome = 0 if self.outcome_items() else None
        self.reload_outcomes_list()
        if self.current_outcome is not None:
            self.outcomes_list.selection_set(self.current_outcome)
        self.load_event_fields()

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
        self.event_desc_text.delete("1.0", "end")
        self.event_desc_text.insert("1.0", event.get("description", ""))
        self.load_outcome_fields()

    def rebuild_effects_grid(self, effects: dict) -> None:
        for widget in self.effects_frame.winfo_children():
            widget.destroy()

        self.effect_vars = {}
        for row, faction_id in enumerate(self.pack_faction_ids()):
            values = effects.get(faction_id, {}) if isinstance(effects, dict) else {}
            if not isinstance(values, dict):
                values = {}

            ttk.Label(self.effects_frame, text=faction_id, width=12).grid(
                row=row, column=0, sticky="w"
            )
            percent = ttk.Entry(self.effects_frame, width=8)
            percent.insert(0, str(values.get("percent", 0)))
            percent.grid(row=row, column=1, padx=4)
            influence = ttk.Entry(self.effects_frame, width=8)
            influence.insert(0, str(values.get("influence", 0)))
            influence.grid(row=row, column=2, padx=4)
            self.effect_vars[faction_id] = (percent, influence)

    def load_outcome_fields(self) -> None:
        outcome = self.current_outcome_dict() or {}

        self.outcome_id_entry.delete(0, "end")
        self.outcome_id_entry.insert(0, outcome.get("id", ""))
        self.outcome_banner_entry.delete(0, "end")
        self.outcome_banner_entry.insert(0, outcome.get("banner") or "")
        self.outcome_desc_text.delete("1.0", "end")
        self.outcome_desc_text.insert("1.0", outcome.get("description", ""))
        self.rebuild_effects_grid(outcome.get("effects", {}) or {})

    def flush_event_fields(self) -> None:
        if self.current_event is None:
            return

        events = self.event_items()
        if self.current_event >= len(events):
            return

        banner = self.event_banner_entry.get().strip() or None
        events[self.current_event].update(
            {
                "id": self.event_id_entry.get().strip(),
                "title": self.event_title_entry.get().strip(),
                "description": self.event_desc_text.get("1.0", "end-1c"),
                "banner": banner,
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
                "description": self.outcome_desc_text.get("1.0", "end-1c"),
                "banner": banner,
                "effects": {
                    faction_id: {
                        "percent": parse_int(percent_entry.get()),
                        "influence": parse_int(influence_entry.get()),
                    }
                    for faction_id, (
                        percent_entry,
                        influence_entry,
                    ) in self.effect_vars.items()
                },
            }
        )
        self.mark_dirty()

    def event_add(self) -> None:
        if not self.data:
            return

        self.flush_event_fields()
        self.event_items().append(
            {
                "id": "new_event",
                "title": "Новое событие",
                "description": "",
                "banner": None,
                "outcomes": [],
            }
        )
        self.reload_events_list()
        self.events_list.selection_clear(0, "end")
        self.events_list.selection_set("end")
        self.events_list.see("end")
        self._on_event_select()
        self.mark_dirty()

    def event_delete(self) -> None:
        index = self.selected_index(self.events_list)
        if index is None:
            return

        self.current_event = None
        self.current_outcome = None
        del self.event_items()[index]
        self.reload_events_list()
        self.reload_outcomes_list()
        self.load_event_fields()
        self.mark_dirty()

    def outcome_add(self) -> None:
        if self.current_event is None:
            messagebox.showinfo("Исходы", "Сначала выберите событие.")
            return

        self.flush_outcome_fields()
        self.outcome_items().append(
            {"id": "new", "description": "", "banner": None, "effects": {}}
        )
        self.reload_outcomes_list()
        self.outcomes_list.selection_clear(0, "end")
        self.outcomes_list.selection_set("end")
        self.outcomes_list.see("end")
        self._on_outcome_select()
        self.mark_dirty()

    def outcome_delete(self) -> None:
        index = self.selected_index(self.outcomes_list)
        if index is None:
            return

        self.current_outcome = None
        del self.outcome_items()[index]
        self.reload_outcomes_list()
        self.load_outcome_fields()
        self.mark_dirty()

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
        if current == "Альянсы":
            self.flush_alliance_fields()
            self.refresh_alliance_faction_box()
        elif current == "Способности":
            self.flush_ability_fields()
            self.refresh_ability_faction_values()
            self.load_ability_fields()
        elif current == "Изображения":
            self.refresh_images()

    def flush_all(self) -> None:
        self.flush_pack_tab()
        self.flush_faction_fields()
        self.reload_factions_list()
        self.flush_alliance_fields()
        self.reload_alliances_list()
        self.flush_ability_fields()
        self.reload_abilities_list()
        self.flush_event_fields()
        self.reload_events_list()
        self.reload_outcomes_list()

    def reload_all(self) -> None:
        self._loading = True
        try:
            self.load_pack_tab()

            self.current_faction = None
            self.reload_factions_list()
            self.load_faction_fields()

            self.current_alliance = None
            self.refresh_alliance_faction_box()
            self.reload_alliances_list()

            self.current_ability = None
            self.refresh_ability_faction_values()
            self.reload_abilities_list()
            self.load_ability_fields()

            self.current_event = None
            self.current_outcome = None
            self.reload_events_list()
            self.reload_outcomes_list()
            self.load_event_fields()
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
            title="Открыть GamePack",
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
            title="Сохранить GamePack как",
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
