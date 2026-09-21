from __future__ import annotations

from html import escape

from pol_inc.application.tarbin_packs import TarbinPackMeta
from pol_inc.domain.enums import SessionStatus
from pol_inc.domain.tarbin_game import (
    BRANCH_CATEGORY,
    TurnReport,
    role_category,
    slots_for_role,
)
from pol_inc.domain.tarbin_pack import TarbinGamePack

STATUS_LABELS = {
    SessionStatus.NEW: "подготовка",
    SessionStatus.IN_GAME: "в игре",
    SessionStatus.FINISHED: "завершена",
    SessionStatus.CLOSED: "закрыта",
}

REGION_STATUS_RU = {
    "stable": "стабильный",
    "contested": "оспариваемый",
    "unstable": "нестабильный",
    "occupied": "оккупированный",
}

REGION_STATUS_EMOJI = {
    "stable": "🟢",
    "unstable": "🟡",
    "contested": "🟠",
    "occupied": "🔴",
}

GLOBAL_STAT_RU = {
    "trust_global": "Доверие",
    "initiative": "Инициатива",
    "budget": "Бюджет",
    "corruption": "Коррупция",
    "al_nazra_support": "Поддержка Аль Назра",
}

PRIORITY_RU = {
    "security": "Безопасность",
    "civil": "Гражданское восстановление",
    "info": "Информация",
    "economy": "Экономика",
    "intel": "Разведка",
}


def esc(value: object) -> str:
    return escape(str(value))


def format_delta(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


def _status_ru(status: SessionStatus) -> str:
    return STATUS_LABELS.get(status, str(status.value))


def _role_name(pack: TarbinGamePack | None, role_id: str) -> str:
    if pack is not None:
        role = pack.role_by_id(role_id)
        if role is not None:
            return role.short_name or role.name
    return role_id


def _region_status_ru(status: str) -> str:
    return REGION_STATUS_RU.get(status, status)


def _region_status_full(status: str) -> str:
    emoji = REGION_STATUS_EMOJI.get(status, "⚪")
    return f"{emoji} {_region_status_ru(status)}"


def _votes_line(session) -> str:
    state = session.state
    if state is None or not state.event_id:
        return ""

    voted = sum(1 for user_id in session.players if user_id in state.event_votes)
    total = len(session.players)
    missing = [
        esc(player.public_name)
        for user_id, player in session.players.items()
        if user_id not in state.event_votes
    ]

    if missing:
        return (
            f"🗳 Проголосовали: {voted}/{total}. Не проголосовали: {', '.join(missing)}"
        )
    return f"🗳 Проголосовали: {voted}/{total}."


def format_pack_list(metas: list[TarbinPackMeta]) -> list[str]:
    if not metas:
        return ["Доступных паков пока нет."]

    lines = ["<b>Доступные паки TARBIN:</b>", ""]
    for meta in metas:
        lines.append(f"<code>{esc(meta.id)}</code> — {esc(meta.name)}")
        if meta.description:
            lines.append(esc(meta.description))
    lines.append("")
    lines.append("Установка: /ss pack id")
    return lines


def format_lobby(session) -> list[str]:
    pack_name = esc(session.pack_meta.name) if session.pack_meta else "не выбран"
    lines = [
        f"<b>{esc(session.operation_name)}</b>",
        "Тарбин — миротворческая операция",
        f"Статус: {_status_ru(session.status)}",
        f"Код: <code>{esc(session.code)}</code>",
        f"Пак: {pack_name}",
        f"Длительность: {session.duration} ходов",
        f"Игроки: {len(session.players)}/{session.max_players}",
        "",
        "<b>Игроки:</b>",
    ]
    if not session.players:
        lines.append("- пусто")
    else:
        for player in session.players.values():
            prefix = "👑 " if player.user_id == session.creator_id else ""
            roles = ""
            if player.role_ids:
                pack = session.pack
                names = ", ".join(
                    f"{role_category(r)}{esc(_role_name(pack, r))}"
                    for r in player.role_ids
                )
                roles = f" — {names}"
            lines.append(f"- {prefix}{esc(player.public_name)}{roles}")

    lines.append("")
    lines.append("Роли выбираются в личных сообщениях: /role")
    lines.append("")
    blockers: list[str] = []
    if session.pack is None:
        blockers.append("❌ Пак не выбран. Создатель: /ss pack id")
    min_players = max(2, session.min_players)
    if len(session.players) < min_players:
        blockers.append(
            f"❌ Нужно минимум {min_players} игрока. Присоединиться: /join {esc(session.code)}"
        )
    if blockers:
        lines.extend(blockers)
    else:
        lines.append("✅ Всё готово. Создатель может запустить игру: /startgame")
    return lines


def _state_lines(session) -> list[str]:
    state = session.state
    if state is None:
        return []
    return [
        f"🤝 Доверие: {state.trust}%",
        f"⚡ Инициатива: {state.initiative}",
        f"💸 Коррупция: {state.corruption}%",
        f"🔥 Поддержка Аль Назра: {state.al_support}%",
        f"💰 Бюджет: {state.budget} млн",
    ]


def format_briefing(
    session, pack: TarbinGamePack | None, event=None, region_name: str = ""
) -> list[str]:
    state = session.state
    turn = state.turn if state is not None else 1
    total = state.total_turns if state is not None else session.duration
    lines = [f"<b>🗺 ХОД {turn}/{total}</b>", ""]
    if event is not None:
        title = esc(event.title)
        if region_name:
            lines.append(f"❗ {title} — {esc(region_name)}")
        else:
            lines.append(f"❗ {title}")
        lines.append("")
        if event.description:
            lines.append(esc(event.description))
            lines.append("")
        votes = _votes_line(session)
        if votes:
            lines.append(votes)
            lines.append("")
    else:
        lines.append("Тихий ход. Активных событий нет.")
        lines.append("")
    lines.append("<b>📊 Состояние:</b>")
    lines.extend(_state_lines(session))
    lines.append("")
    lines.append("<b>🧑‍✈️ Штаб:</b>")
    for player in session.players.values():
        pack_roles = session.pack
        role_names = ", ".join(
            f"{role_category(r)}{esc(_role_name(pack_roles, r))}"
            for r in session.roles_of(player.user_id)
        )
        lines.append(f"- {esc(player.public_name)}: {role_names or 'без ролей'}")
    lines.append("<b>Доступные действия:</b>")
    lines.append("- действия ролей")
    lines.append("- исследования")
    if state is not None and state.event_id:
        lines.append("- голосование по событию")
    lines.append("")
    lines.append("Все решения принимаются в личных сообщениях бота: /menu")
    return lines


def _delta_label(stat: str) -> str:
    return GLOBAL_STAT_RU.get(stat, stat)


def format_report(report: TurnReport, pack: TarbinGamePack | None = None) -> list[str]:
    lines = [f"<b>ОТЧЁТ. ХОД {report.turn}</b>", ""]
    if report.event_title:
        if report.chosen_option:
            lines.append(f"Штаб выбрал вариант: {esc(report.chosen_option)}.")
        else:
            lines.append(f"Событие: {esc(report.event_title)}.")
        if report.event_region:
            lines.append(f"Регион: {esc(report.event_region)}.")
        if report.outcome_id:
            lines.append(f"Исход: {esc(report.outcome_id)}.")
        lines.append("")
    if report.actions:
        lines.append("<b>Действия игроков:</b>")
        for action in report.actions:
            lines.append(f"- {esc(action)}")
        lines.append("")
    if report.research_done:
        lines.append("<b>Исследования:</b>")
        for item in report.research_done:
            lines.append(f"- {esc(item)}")
        lines.append("")
    if report.invalid:
        lines.append("<b>Отклонено:</b>")
        for item in report.invalid:
            lines.append(f"- {esc(item)}")
        lines.append("")
    if report.global_deltas:
        lines.append("<b>Результаты:</b>")
        for stat, delta in report.global_deltas.items():
            lines.append(f"{_delta_label(stat)}: {format_delta(delta)}")
        lines.append(
            f"Доход: {format_delta(report.income)} млн (содержание: {report.upkeep_paid} млн)"
        )
        lines.append("")
    if report.region_notes:
        lines.append("<b>Регионы:</b>")
        for note in report.region_notes:
            lines.append(f"- {esc(note)}")
        lines.append("")
    if report.synergies:
        lines.append("<b>Синергии:</b>")
        for item in report.synergies:
            lines.append(f"- {esc(item)}")
        lines.append("")
    if report.al_nazra_operation or report.al_nazra_notes:
        lines.append("<b>🔥 Ход Аль Назра:</b>")
        if report.al_nazra_operation:
            lines.append(esc(report.al_nazra_operation))
        for note in report.al_nazra_notes:
            lines.append(f"- {esc(note)}")
        lines.append("")
    return lines


def format_final(session, report: TurnReport | None = None) -> list[str]:
    result = report.result if report is not None else ""
    reason = report.result_reason if report is not None else ""
    if result in ("victory_full", "victory_campaign"):
        header = "🏆 <b>ПОБЕДА. Миссия выполнена.</b>"
    elif result == "victory_partial":
        header = "🎖 <b>ЧАСТИЧНАЯ ПОБЕДА. Операция не провалена.</b>"
    elif result == "defeat":
        header = "💀 <b>ПОРАЖЕНИЕ. Миссия провалена.</b>"
    else:
        header = "<b>Игра завершена.</b>"
    lines = [header, ""]
    if reason:
        lines.append(esc(reason))
        lines.append("")
    lines.append("<b>Итоговое состояние:</b>")
    lines.extend(_state_lines(session))
    state = session.state
    if state is not None and state.regions:
        lines.append("")
        lines.append("<b>Регионы:</b>")
        for region in state.regions.values():
            lines.append(
                f"- {esc(region.name)}: {_region_status_full(region.status)} "
                f"(безоп. {region.security}, доверие {region.trust}, Аль Назра {region.al_nazra})"
            )
    return lines


def format_status(session) -> list[str]:
    state = session.state
    lines = [f"<b>{esc(session.operation_name)}</b> <code>{esc(session.code)}</code>"]
    if state is None:
        lines.append(f"Статус: {_status_ru(session.status)}")
        return lines
    lines.append(f"Ход: {state.turn}/{state.total_turns}")
    lines.extend(_state_lines(session))
    if state.event_id:
        pack = session.pack
        title = state.event_id
        if pack is not None:
            for event in pack.events:
                if event.id == state.event_id:
                    title = event.title
                    break
        lines.append(f"Событие: {esc(title)}")
        votes = _votes_line(session)
        if votes:
            lines.append(votes)
    else:
        lines.append("Событий нет — тихий ход.")

    if state is not None:
        pack = session.pack
        if pack is not None:
            total_slots = sum(slots_for_role(pack, state) for _ in state.active_roles)
            filled = sum(len(subs) for subs in state.submissions.values())
            lines.append(f"Заявки: {filled}/{total_slots}")
    return lines


def format_regions(session, show_hideouts: bool = False) -> list[str]:
    state = session.state
    if state is None:
        return ["Игра ещё не запущена."]
    lines = [f"<b>🗺 Регионы. Ход {state.turn}:</b>", ""]
    hideout_regions = {h.region_id for h in state.hideouts} if show_hideouts else set()
    for region in state.regions.values():
        lines.append(f"{_region_status_full(region.status)} <b>{esc(region.name)}</b>")
        lines.append(
            f"🛡 Безоп. {region.security} | 🤝 Доверие {region.trust} | "
            f"💰 Экономика {region.economy}"
        )
        lines.append(
            f"🏛 Правительство {region.government} | 🔥 Аль Назра {region.al_nazra} | "
            f"🏗 Инфра. {region.infrastructure}"
        )
        flags: list[str] = []
        if region.guard_until_turn >= state.turn:
            flags.append("🛡 под защитой")
        if show_hideouts and region.region_id in hideout_regions:
            revealed = any(
                h.region_id == region.region_id and h.revealed for h in state.hideouts
            )
            flags.append(
                "⚠️ логово подтверждено" if revealed else "❓ подозрение на логово"
            )
        if any(m.get("id") == "rumor" for m in region.modifiers):
            flags.append("📢 слухи")
        if flags:
            lines.append(" · ".join(flags))
        lines.append("")
    return lines


def format_roles_menu(session, user_id: int) -> list[str]:
    player = session.players.get(user_id)
    if player is None:
        return ["Вы не участвуете в операции."]
    roles = session.roles_of(user_id)
    pack = session.pack
    lines = ["<b>Штаб. Ваши роли:</b>", ""]
    if not roles:
        lines.append("У вас пока нет ролей.")
        return lines
    state = session.state
    for index, role_id in enumerate(roles, start=1):
        lines.append(
            f"{index}. {role_category(role_id)} {esc(_role_name(pack, role_id))}"
        )
        if state is not None and pack is not None:
            slots = slots_for_role(pack, state)
            left = slots - len(state.submissions.get(role_id, []))
            if left > 0:
                lines.append(f"Осталось действий: {left}/{slots}.")
            else:
                lines.append("Заявки поданы ✅")
    if state is not None:
        lines.append("")
        lines.append(
            f"Ход {state.turn}/{state.total_turns}. Бюджет: {state.budget} млн"
        )
        if session.role_owners.get("commander") == user_id and state.priority is None:
            lines.append("❗ Приоритет операции не выбран.")
    return lines


def _tech_unlocked(pack, state, tech) -> bool:
    if tech.id in state.researched:
        return False
    for submitted in state.submissions.values():
        for sub in submitted:
            if sub.kind == "research" and sub.tech_id == tech.id:
                return False
    for prerequisite in tech.prerequisites:
        if prerequisite not in state.researched:
            return False
    if tech.tier > 1:
        previous = [
            item
            for item in pack.techs_for_branch(tech.branch)
            if item.tier == tech.tier - 1
        ]
        if previous and previous[0].id not in state.researched:
            return False
    return True


def format_research_menu(session) -> list[str]:
    pack = session.pack
    state = session.state
    if pack is None or state is None:
        return ["Игра ещё не запущена."]
    lines = ["<b>🔬 Доступные технологии:</b>", ""]
    branches: dict[str, list] = {}
    for tech in pack.tech_tree:
        if not _tech_unlocked(pack, state, tech):
            continue
        branches.setdefault(tech.branch, []).append(tech)
    shown = False
    for branch in sorted(branches):
        items = [t for t in sorted(branches[branch], key=lambda t: t.tier)]
        if not items:
            continue
        shown = True
        lines.append(f"<b>{BRANCH_CATEGORY.get(branch, '⚪')} {esc(branch)}:</b>")
        for tech in items:
            lines.append(f"- {esc(tech.name)} — {tech.cost} млн")
            if tech.description:
                lines.append(f"  <i>{esc(tech.description)}</i>")
        lines.append("")
    if not shown:
        lines.append("Доступных технологий нет. Откройте «Подробнее».")
        lines.append("")
    lines.append("Выберите технологию для исследования.")
    return lines


def format_research_details(session) -> list[str]:
    pack = session.pack
    state = session.state
    if pack is None or state is None:
        return ["Игра ещё не запущена."]
    lines = ["<b>🔬 Технологии. Подробнее:</b>", ""]
    if state.researched:
        lines.append("<b>Изучено ✅:</b>")
        for tech_id in state.researched:
            tech = pack.tech_by_id(tech_id)
            name = tech.name if tech else tech_id
            lines.append(f"- ✅ {esc(name)}")
        lines.append("")
    branches: dict[str, list] = {}
    for tech in pack.tech_tree:
        if tech.id in state.researched:
            continue
        branches.setdefault(tech.branch, []).append(tech)
    lines.append("<b>Закрыто 🔒:</b>")
    any_locked = False
    for branch in sorted(branches):
        for tech in sorted(branches[branch], key=lambda t: t.tier):
            lines.append(f"- 🔒 {esc(tech.name)} — {tech.cost} млн")
            if tech.description:
                lines.append(f"  <i>{esc(tech.description)}</i>")
            any_locked = True
    if not any_locked:
        lines.append("- нет")
    return lines


def format_event_menu(session) -> list[str]:
    pack = session.pack
    state = session.state
    if pack is None or state is None:
        return ["Игра ещё не запущена."]
    if not state.event_id:
        return ["Сейчас нет активного события."]
    for event in pack.events:
        if event.id == state.event_id:
            lines = [f"<b>Активное событие: {esc(event.title)}</b>", ""]
            if event.description:
                lines.append(esc(event.description))
                lines.append("")
            for option in event.options:
                lines.append(
                    f"{esc(option.id)} — {esc(option.title)} ({option.cost} млн)"
                )
            lines.append("")
            votes = _votes_line(session)
            if votes:
                lines.append(votes)
                lines.append("")
            lines.append("Голос обязателен. Проголосуйте за один вариант.")
            return lines
    return ["Событие не найдено в паке."]


def format_loy(session, user_id: int) -> list[str]:
    player = session.players.get(user_id)
    if player is None:
        return ["Вы не участвуете в операции."]
    pack = session.pack
    state = session.state
    lines = [f"<b>Карточка: {esc(player.public_name)}</b>", ""]
    if player.role_ids:
        lines.append("<b>Роли:</b>")
        for role_id in player.role_ids:
            lines.append(f"- {role_category(role_id)} {esc(_role_name(pack, role_id))}")
    else:
        lines.append("Роли не назначены.")
    lines.append("")
    if state is None:
        lines.append("Игра ещё не запущена.")
        return lines
    lines.append("<b>Заявки хода:</b>")
    has_any = False
    for role_id in player.role_ids:
        submitted = state.submissions.get(role_id, [])
        if pack is not None:
            left = (
                max(0, slots_for_role(pack, state) - len(submitted))
                if role_id in session.active_roles
                else 0
            )
            lines.append(
                f"{role_category(role_id)} {esc(_role_name(pack, role_id))}: "
                f"осталось действий {left}."
            )
        for sub in submitted:
            has_any = True
            if sub.kind == "action":
                action = pack.action_by_id(sub.action_id) if pack else None
                name = action.name if action else sub.action_id
                target = f" → {esc(sub.region_id)}" if sub.region_id else ""
                lines.append(f"- {esc(name)}{target}")
            elif sub.kind == "research":
                tech = pack.tech_by_id(sub.tech_id) if pack else None
                name = tech.name if tech else sub.tech_id
                lines.append(f"- исследование: {esc(name)}")
    if not has_any:
        lines.append("- пока нет")
    lines.append("")
    if state.researched:
        researched_names = []
        for tech_id in state.researched:
            tech = pack.tech_by_id(tech_id) if pack else None
            researched_names.append(tech.name if tech else tech_id)
        lines.append(f"Исследовано: {esc(', '.join(researched_names))}")
    else:
        lines.append("Исследовано: пока ничего")
    if state.event_id:
        vote = state.event_votes.get(user_id)
        lines.append(f"Голос по событию: {esc(vote) if vote else 'не голосовали'}")
    return lines


def format_help() -> list[str]:
    return [
        "<b>TARBIN: Миротворческая миссия — помощь</b>",
        "",
        "<b>Групповой чат:</b>",
        "/newgame — создать операцию",
        "/join [код] — присоединиться",
        "/leavegame — покинуть операцию",
        "/operation &lt;название&gt; — название операции",
        "/startgame — запустить игру",
        "/closegame [код] — закрыть операцию",
        "/game — лобби или статус игры",
        "/ss — параметры сессии",
        "/ss pack &lt;id&gt; — выбрать пак",
        "/ss turns &lt;n&gt; — длительность",
        "/status — снимок состояния",
        "/map — карта Тарбина",
        "/help — помощь",
        "",
        "<b>Личные сообщения:</b>",
        "/menu — главное меню штаба",
        "/actions [номер роли] — действия ролей",
        "/research — технологии",
        "/regions — состояние регионов",
        "/event — голосование по событию",
        "/role — выбор роли на этапе подготовки",
        "/cancel — сбросить заявки хода",
        "/loy — личная карточка",
        "/map — карта Тарбина",
        "/help — помощь",
        "",
        "<b>🎯 Цель:</b> штабом довести операцию до победы.",
        "Полная победа сразу: доверие 100%, поддержка Аль Назра ≤20%, инициатива &gt;0.",
        "В конце последнего хода: доверие ≥70, поддержка ≤10, без логовов,",
        "все регионы не хуже нестабильных, инициатива ≥30.",
        "Частичная победа: доверие ≥50, поддержка ≤25, инициатива ≥20.",
        "",
        "<b>💀 Поражение:</b> инициатива 0, бюджет −20 млн и ниже,",
        "поддержка Аль Назра 100, 4 оккупированных региона,",
        "оккупирована столица, развал штаба.",
        "",
        "<b>📊 Ресурсы:</b>",
        "🤝 Доверие 0–100 — главная цель, падает от жёстких операций.",
        "⚡ Инициатива 0–100 — каждый ход −4, при нуле поражение.",
        "💰 Бюджет — оплата действий; доход зависит от экономики и коррупции.",
        "💸 Коррупция 0–100 — +1 за ход, удорожает всё.",
        "🔥 Поддержка Аль Назра 0–100 — сила боевиков.",
        "",
        "<b>🗺 Регионы:</b> 🟢 стабильный, 🟡 нестабильный,",
        "🟠 оспариваемый, 🔴 оккупированный. У каждого своя экономика,",
        "доверие, безопасность и присутствие боевиков.",
        "",
        "<b>🎬 Роли:</b> 🏛 командование, 🔴 силовые, 🟢 гражданские,",
        "🔵 экономика. Каждая активная роль — 1 действие за ход.",
        "Голосование по событию действие не тратит и обязательно для всех.",
        "",
        "<b>🔬 Технологии:</b> занимают действие роли, завершаются",
        "в конце хода, открывают новые действия и бонусы.",
        "",
        "<b>⏭ Ход:</b> когда все роли заявили действия и все проголосовали,",
        "выходит отчёт с кнопкой «Далее». Новый ход начинается,",
        "когда «Далее» нажмут все игроки.",
    ]


def format_regions_help() -> list[str]:
    return [
        "<b>🗺 Регионы. Инструкция:</b>",
        "",
        "<b>Статусы:</b>",
        "🟢 стабильный — безопасность ≥60 и боевиков ≤20.",
        "Даёт +1 к экономике и правительству за ход.",
        "🟡 нестабильный — обычное состояние, риск беспорядков",
        "при низкой безопасности или доверии.",
        "🟠 оспариваемый — боевиков ≥45 или безопасность &lt;25.",
        "Выше шанс атак.",
        "🔴 оккупированный — боевиков ≥70 и правительство &lt;30.",
        "Регион частично вне контроля.",
        "",
        "<b>Параметры:</b>",
        "🛡 Безопасность — защита от атак и боевиков.",
        "🤝 Доверие — поддержка населения; высокое доверие (+60)",
        "даёт +1 к безопасности.",
        "💰 Экономика — даёт доход в бюджет.",
        "🏛 Правительство — присутствие власти; падает, если боевиков",
        "в регионе больше, чем безопасности.",
        "🔥 Аль Назра — присутствие боевиков; ≥40 при безопасности ≤30",
        "может дать логово (+2 боевиков за ход).",
        "🏗 Инфраструктура — объекты и развитие.",
        "",
        "🛡 «под защитой» — гарнизон или оборона объекта до следующего хода.",
        "📢 «слухи» — негативный модификатор, снимается развенчанием.",
        "⚠️ «логово подтверждено» — видно разведке и командующему,",
        "уничтожается спецоперацией или глубокой агентурой.",
    ]


def format_roles_pick(session) -> list[str]:
    pack = session.pack
    lines = ["<b>🎭 Выбор ролей:</b>", ""]
    taken = {}
    for player in session.players.values():
        for role_id in player.role_ids:
            taken[role_id] = player.public_name
    roles = [role.id for role in pack.roles] if pack is not None else []
    for index, role_id in enumerate(roles, start=1):
        lines.append(
            f"{index}. {role_category(role_id)} {esc(_role_name(pack, role_id))}"
        )
        role = pack.role_by_id(role_id) if pack is not None else None
        if role is not None and role.description:
            lines.append(f"  <i>{esc(role.description)}</i>")
        if role_id in taken:
            lines.append(f"  Занята: {esc(taken[role_id])}")
    lines.append("")
    lines.append("Нажмите роль, чтобы выбрать или снять выбор.")
    return lines


def format_hints(session) -> list[str]:
    state = session.state
    pack = session.pack
    if state is None or pack is None:
        return ["Игра ещё не запущена."]

    hints: list[str] = []

    if state.al_support >= 50:
        hints.append(
            f"🔥 Поддержка боевиков {state.al_support}% — критическая. "
            "Давите рейдами, контрпропагандой и агентурой."
        )
    elif state.al_support >= 25:
        hints.append(
            f"🔥 Поддержка боевиков {state.al_support}% растёт. "
            "Усильте безопасность и информацию."
        )

    if state.trust < 20:
        hints.append(
            "🤝 Доверие ниже 20: военные действия дают дополнительный штраф. "
            "Сначала поднимите доверие гражданскими проектами."
        )

    if state.corruption >= 40:
        hints.append(
            f"💸 Коррупция {state.corruption}%: всё сильно дорожает. Срочно аудит."
        )
    elif state.corruption >= 20:
        hints.append(
            f"💸 Коррупция {state.corruption}%: действия дороже на 10%. Присмотрите аудит."
        )

    if state.budget < 20:
        hints.append(
            f"💰 Бюджет {state.budget} млн на исходе. Финансисту нужны помощь и пакеты."
        )

    if 0 < state.initiative < 20:
        hints.append(
            f"⚡ Инициатива {state.initiative}: близко к поражению. "
            "Нужны заявления, успехи и решённые события."
        )

    for region in state.regions.values():
        if region.status == "occupied":
            hints.append(f"🔴 {region.name} оккупирован. Нужны войска и зачистка.")
        elif region.status == "contested":
            hints.append(f"🟠 {region.name} оспаривается. Укрепите безопасность.")
        if (
            region.al_nazra >= 40
            and region.security <= 30
            and not any(h.region_id == region.region_id for h in state.hideouts)
        ):
            hints.append(
                f"❓ В регионе {region.name} зреют условия для логова. "
                "Разведка и патрули."
            )

    revealed_hideouts = [h for h in state.hideouts if h.revealed]
    if revealed_hideouts:
        names = ", ".join(
            esc(state.regions[h.region_id].name)
            for h in revealed_hideouts
            if h.region_id in state.regions
        )
        hints.append(f"⚠️ Подтверждены логова: {names}. Уничтожайте спецоперацией.")
    elif state.hideouts:
        hints.append("❓ Есть неподтверждённые логова. Разведке стоит их подтвердить.")

    if state.event_id:
        voted = sum(1 for u in session.players if u in state.event_votes)
        total = len(session.players)
        if voted < total:
            missing = ", ".join(
                esc(p.public_name)
                for u, p in session.players.items()
                if u not in state.event_votes
            )
            hints.append(
                f"🗳 Событие ждёт голосов ({voted}/{total}). Не проголосовали: {missing}."
            )

    no_submission_roles = [
        role_id
        for role_id in state.active_roles
        if role_id not in state.vacant_roles and not state.submissions.get(role_id)
    ]
    if no_submission_roles:
        names = ", ".join(
            esc(_role_name(pack, role_id)) for role_id in no_submission_roles
        )
        hints.append(f"📝 Без заявок: {names}.")

    if state.priority is None:
        hints.append(
            "❗ Приоритет операции не выбран. Командующий, задайте его в меню."
        )

    if state.vacant_roles:
        names = ", ".join(
            esc(_role_name(pack, role_id)) for role_id in state.vacant_roles
        )
        hints.append(
            f"🪑 Вакантные роли ({names}): каждый ход −1 инициативы за каждую."
        )

    unresearched = [
        tech
        for tech in pack.tech_tree
        if tech.tier == 1 and tech.id not in state.researched
    ]
    if unresearched and state.turn <= 3:
        hints.append(
            "🔬 Ранние ходы — время первых исследований: они открывают действия."
        )

    if not hints:
        hints.append(
            "✅ Критических проблем нет. Держите темп: безопасность, доверие, бюджет."
        )

    lines = ["<b>💡 Подсказка штаба:</b>", ""]
    lines.extend(f"- {hint}" for hint in hints[:12])
    return lines
