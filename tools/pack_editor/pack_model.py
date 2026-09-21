"""Логика редактора TARBIN-паков без GUI: загрузка, валидация, сохранение и сбор изображений.

Использует pydantic-модели проекта (pol_inc.domain.tarbin_pack), поэтому правила
валидации всегда совпадают с теми, что применяет движок при загрузке пака.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

GLOBAL_BANNERS = ["game_info.jpg", "game_reg.jpg"]


def new_pack_template() -> dict:
    """Минимальный валидный TARBIN-пак для написания с нуля."""
    return {
        "schema_version": "1.0",
        "pack_type": "TARBIN",
        "id": "new_pack",
        "name": "Новый пак",
        "description": "",
        "language": "ru",
        "durations": [8],
        "settings": {
            "min_players": 2,
            "max_players": 6,
            "action_points_per_role": 1,
            "event_turns": [],
            "start_budget": 120,
            "start_initiative": 50,
            "start_trust": 0,
            "start_corruption": 0,
            "start_al_nazra_support": 10,
            "initiative_decay": 4,
            "base_income": 10,
            "timeout_hours": 4,
        },
        "roles": [
            {
                "id": "commander",
                "name": "Командующий",
                "short_name": "CMD",
                "description": "",
                "passive": "",
                "available_actions": ["CMD-01"],
            },
            {
                "id": "military_coordinator",
                "name": "Координатор",
                "short_name": "MIL",
                "description": "",
                "passive": "",
                "available_actions": ["MIL-01"],
            },
        ],
        "regions": [
            {
                "id": "R1",
                "name": "Регион 1",
                "type": "",
                "population": 1000,
                "economy": 20,
                "trust": 0,
                "security": 25,
                "government": 40,
                "al_nazra": 10,
                "infrastructure": 30,
            }
        ],
        "tech_tree": [
            {
                "id": "T1",
                "branch": "security",
                "tier": 1,
                "name": "Технология 1",
                "cost": 5,
                "prerequisites": [],
                "unlocks_actions": [],
                "flags": {},
            }
        ],
        "actions": [
            {
                "id": "CMD-01",
                "role_id": "commander",
                "name": "Действие командующего",
                "description": "",
                "type": "operation",
                "cost": 2,
                "target": "none",
                "cooldown": 0,
                "requirements": {},
                "effects": [],
                "tags": [],
                "upkeep": {},
                "next_income_bonus": 0,
                "next_cost_discount": 0,
            },
            {
                "id": "MIL-01",
                "role_id": "military_coordinator",
                "name": "Действие координатора",
                "description": "",
                "type": "operation",
                "cost": 2,
                "target": "none",
                "cooldown": 0,
                "requirements": {},
                "effects": [],
                "tags": [],
                "upkeep": {},
                "next_income_bonus": 0,
                "next_cost_discount": 0,
            },
        ],
        "events": [
            {
                "id": "EVT-01",
                "title": "Новое событие",
                "description": "",
                "banner": None,
                "target_scope": "global",
                "default_region_filter": {},
                "options": [
                    {
                        "id": "A",
                        "title": "Вариант 1",
                        "cost": 0,
                        "effects": [],
                        "outcomes": [],
                    }
                ],
            }
        ],
        "al_nazra": {
            "intentions": [
                {"id": "intent_1", "name": "Намерение 1", "description": ""}
            ],
            "operations": [
                {
                    "id": "op_1",
                    "name": "Операция 1",
                    "min_support": 0,
                    "tags": [],
                    "effects": [],
                    "region_effects": [],
                    "region_modifier": "",
                }
            ],
            "hideout_threshold": 40,
            "hideout_security_max": 30,
        },
        "assets": {"cover": None},
    }


def load_pack_file(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError("Корень JSON пака должен быть объектом.")

    return data


def validate_pack(data: dict) -> list[str]:
    """Возвращает список человекочитаемых ошибок. Пустой список = пак валиден."""
    from pol_inc.domain.tarbin_pack import TarbinGamePack

    try:
        TarbinGamePack.model_validate(data)
    except ValidationError as exc:
        return [format_pydantic_error(err) for err in exc.errors()]

    return []


def format_pydantic_error(err: dict) -> str:
    loc = " → ".join(str(part) for part in err.get("loc", ()))
    message = err.get("msg", "ошибка")
    return f"{loc}: {message}" if loc else message


def save_pack_file(path: str | Path, data: dict) -> None:
    errors = validate_pack(data)
    if errors:
        raise ValueError("Пак невалиден:\n" + "\n".join(f"- {err}" for err in errors))

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def collect_images(data: dict, include_global: bool = True) -> list[dict]:
    """Собирает все имена изображений TARBIN-пака.

    Возвращает список {"name": ..., "usages": [...]} отсортированный по имени.
    """

    usages: dict[str, list[str]] = {}

    def add(name: object, usage: str) -> None:
        if not isinstance(name, str):
            return

        name = name.strip()
        if not name:
            return

        usages.setdefault(name, []).append(usage)

    for event in data.get("events", []) or []:
        if not isinstance(event, dict):
            continue

        event_label = event.get("title") or event.get("id") or "?"
        add(event.get("banner"), f"событие «{event_label}»")

        for option in event.get("options", []) or []:
            if not isinstance(option, dict):
                continue

            option_label = option.get("id") or "?"
            for outcome in option.get("outcomes", []) or []:
                if not isinstance(outcome, dict):
                    continue

                outcome_label = outcome.get("id") or "?"
                add(
                    outcome.get("banner"),
                    f"исход «{outcome_label}» варианта «{option_label}» "
                    f"события «{event_label}»",
                )

    assets = data.get("assets", {}) or {}
    if isinstance(assets, dict):
        add(assets.get("cover"), "обложка пака (assets.cover)")

    if include_global:
        for name in GLOBAL_BANNERS:
            add(name, "глобальный баннер (не из пака)")

    return [
        {"name": name, "usages": usages[name]}
        for name in sorted(usages, key=str.lower)
    ]
