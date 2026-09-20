"""Логика редактора GamePack без GUI: загрузка, валидация, сохранение и сбор изображений.

Использует pydantic-модели проекта, поэтому правила валидации всегда совпадают
с теми, что применяет бот при загрузке пака.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

GLOBAL_BANNERS = ["game_info.jpg", "game_reg.jpg"]


def load_pack_file(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError("Корень JSON пака должен быть объектом.")

    return data


def validate_pack(data: dict) -> list[str]:
    """Возвращает список человекочитаемых ошибок. Пустой список = пак валиден."""
    from pol_inc.domain.packs import GamePack

    try:
        GamePack.model_validate(data)
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
    """Собирает все имена изображений пака.

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

        for outcome in event.get("outcomes", []) or []:
            if not isinstance(outcome, dict):
                continue

            outcome_label = outcome.get("id") or "?"
            add(outcome.get("banner"), f"исход «{outcome_label}» события «{event_label}»")

    if include_global:
        for name in GLOBAL_BANNERS:
            add(name, "глобальный баннер (не из пака)")

    return [
        {"name": name, "usages": usages[name]}
        for name in sorted(usages, key=str.lower)
    ]
