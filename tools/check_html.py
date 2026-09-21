"""Проверка HTML-разметки текстов бота.

Telegram при parse_mode=HTML падает на любом неизвестном теге вида <...>,
поэтому все пользовательские данные должны идти через esc(), а плейсхолдеры
в подсказках — через &lt;...&gt;.

Проверяет два уровня:
1. Рендер всех format_* с вредоносными данными (теги, &, кавычки).
2. Статический поиск сырых <тег> в исходниках pol_inc/bot.

Запуск из корня репозитория:
    .venv\\Scripts\\python tools\\check_html.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "a"}

TAG_RE = re.compile(r"<(/?)([A-Za-zА-Яа-яЁё]+)(?:\\s[^<>]*)?>")
SRC_TAG_RE = re.compile(r"<(/?)([A-Za-zА-Яа-яЁё]+)[^<>]*>")

EVIL = '<название> & "кавычки" <b>bold</b>'


def check_text(text: str, where: str, errors: list[str]) -> None:
    for match in TAG_RE.finditer(text):
        tag = match.group(2)
        if tag not in ALLOWED_TAGS:
            errors.append(f"{where}: сырой тег {match.group(0)!r} в {text!r}")


def check_rendered() -> list[str]:
    from pol_inc.application.tarbin_packs import TarbinPackMeta
    from pol_inc.application.tarbin_sessions import TarbinPlayer, TarbinSession
    from pol_inc.bot import formatting as fmt
    from pol_inc.domain.enums import SessionStatus
    from pol_inc.domain.tarbin_game import GameState, RegionState, TurnReport
    from pol_inc.domain.tarbin_pack import TarbinGamePack

    errors: list[str] = []

    pack = TarbinGamePack.model_validate(
        {
            "id": "test",
            "name": f"Пак {EVIL}",
            "durations": [8],
            "roles": [
                {
                    "id": "commander",
                    "name": f"Роль {EVIL}",
                    "short_name": "Ком",
                    "available_actions": [],
                }
            ],
            "regions": [
                {
                    "id": "R1",
                    "name": f"Регион {EVIL}",
                    "population": 100,
                    "economy": 10,
                    "trust": 10,
                    "security": 10,
                    "government": 10,
                    "al_nazra": 10,
                    "infrastructure": 10,
                }
            ],
            "tech_tree": [
                {
                    "id": "T1",
                    "branch": f"Ветка {EVIL}",
                    "tier": 1,
                    "name": f"Тех {EVIL}",
                    "cost": 5,
                }
            ],
            "actions": [
                {
                    "id": "A1",
                    "role_id": "commander",
                    "name": f"Действие {EVIL}",
                    "description": EVIL,
                    "cost": 1,
                    "target": "none",
                }
            ],
            "events": [
                {
                    "id": "E1",
                    "title": f"Событие {EVIL}",
                    "description": EVIL,
                    "target_scope": "global",
                    "options": [{"id": "A", "title": f"Вариант {EVIL}", "cost": 1}],
                }
            ],
            "al_nazra": {"intentions": [], "operations": []},
        }
    )

    state = GameState(turn=1, total_turns=8)
    state.regions["R1"] = RegionState(region_id="R1", name=f"Регион {EVIL}")
    player = TarbinPlayer(
        user_id=1, username="evil", display_name=f"Игрок {EVIL}", role_ids=["commander"]
    )
    session = TarbinSession(
        code="AB<CD>",
        chat_id=1,
        creator_id=1,
        operation_name=f"Операция {EVIL}",
        status=SessionStatus.IN_GAME,
        players={1: player},
        pack_meta=TarbinPackMeta("test", f"Мета {EVIL}"),
        pack=pack,
        state=state,
    )
    report = TurnReport(
        turn=1,
        event_title=f"Событие {EVIL}",
        event_region=f"Регион {EVIL}",
        chosen_option=f"Вариант {EVIL}",
        actions=[f"Действие {EVIL}"],
        research_done=[f"Тех {EVIL}"],
        invalid=[f"Ошибка {EVIL}"],
        global_deltas={"trust_global": 5},
        region_notes=[f"Заметка {EVIL}"],
        synergies=[f"Синергия {EVIL}"],
        al_nazra_operation=f"Операция {EVIL}",
        al_nazra_notes=[f"Примечание {EVIL}"],
        result="defeat",
        result_reason=f"Причина {EVIL}",
    )

    cases = [
        ("format_pack_list", fmt.format_pack_list([TarbinPackMeta("x", EVIL, EVIL)])),
        ("format_lobby", fmt.format_lobby(session)),
        ("format_briefing", fmt.format_briefing(session, pack, pack.events[0], EVIL)),
        ("format_report", fmt.format_report(report, pack)),
        ("format_final", fmt.format_final(session, report)),
        ("format_status", fmt.format_status(session)),
        ("format_regions", fmt.format_regions(session)),
        ("format_roles_menu", fmt.format_roles_menu(session, 1)),
        ("format_research_menu", fmt.format_research_menu(session)),
        ("format_event_menu", fmt.format_event_menu(session)),
        ("format_loy", fmt.format_loy(session, 1)),
        ("format_help", fmt.format_help()),
    ]

    for name, lines in cases:
        for line in lines:
            check_text(line, name, errors)

    return errors


def check_sources() -> list[str]:
    errors: list[str] = []
    root = Path(__file__).resolve().parent.parent / "pol_inc" / "bot"

    for path in sorted(root.glob("*.py")):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in SRC_TAG_RE.finditer(line):
                tag = match.group(2)
                if tag not in ALLOWED_TAGS:
                    errors.append(f"{path.name}:{lineno}: сырой тег {match.group(0)!r}")

    return errors


def main() -> int:
    errors = check_rendered() + check_sources()

    if errors:
        print("HTML CHECK FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("HTML CHECK OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
