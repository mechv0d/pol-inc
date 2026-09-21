from __future__ import annotations

from html import escape

from pol_inc.application.tarbin_packs import TarbinPackMeta
from pol_inc.domain.enums import SessionStatus
from pol_inc.domain.tarbin_game import TurnReport
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

GLOBAL_STAT_RU = {
    "trust_global": "Доверие",
    "initiative": "Инициатива",
    "budget": "Бюджет",
    "corruption": "Коррупция",
    "al_nazra_support": "Поддержка Al Nazra",
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
                names = ", ".join(esc(_role_name(pack, r)) for r in player.role_ids)
                roles = f" — {names}"
            mark = " ✅" if player.confirmed else ""
            lines.append(f"- {prefix}{esc(player.public_name)}{roles}{mark}")

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
        f"Доверие: {state.trust}%",
        f"Инициатива: {state.initiative}",
        f"Коррупция: {state.corruption}%",
        f"Поддержка Al Nazra: {state.al_support}%",
        f"Бюджет: {state.budget} млн",
    ]


def format_briefing(
    session, pack: TarbinGamePack | None, event=None, region_name: str = ""
) -> list[str]:
    state = session.state
    turn = state.turn if state is not None else 1
    total = state.total_turns if state is not None else session.duration
    lines = [f"<b>ХОД {turn}/{total}</b>", ""]
    if event is not None:
        title = esc(event.title)
        if region_name:
            lines.append(f"{title} — {esc(region_name)}")
        else:
            lines.append(title)
        lines.append("")
        if event.description:
            lines.append(esc(event.description))
            lines.append("")
    else:
        lines.append("Тихий ход. Активных событий нет.")
        lines.append("")
    lines.append("<b>Состояние:</b>")
    lines.extend(_state_lines(session))
    lines.append("")
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
        lines.append("<b>Ход Al Nazra:</b>")
        if report.al_nazra_operation:
            lines.append(esc(report.al_nazra_operation))
        for note in report.al_nazra_notes:
            lines.append(f"- {esc(note)}")
        lines.append("")
    lines.append(f"Следующий ход: {report.turn + 1}")
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
                f"- {esc(region.name)}: {_region_status_ru(region.status)} "
                f"(безоп. {region.security}, доверие {region.trust}, Al Nazra {region.al_nazra})"
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
    ready = sum(1 for p in session.players.values() if p.confirmed)
    lines.append(f"Готовы: {ready}/{len(session.players)}")
    return lines


def format_regions(session, show_hideouts: bool = False) -> list[str]:
    state = session.state
    if state is None:
        return ["Игра ещё не запущена."]
    lines = [f"<b>Регионы. Ход {state.turn}:</b>", ""]
    hideout_regions = {h.region_id for h in state.hideouts} if show_hideouts else set()
    for region in state.regions.values():
        lines.append(
            f"<b>{esc(region.name)}</b> ({esc(region.region_id)}) — {_region_status_ru(region.status)}"
        )
        lines.append(
            f"Безоп. {region.security}, доверие {region.trust}, экономика {region.economy}, "
            f"правит. {region.government}, Al Nazra {region.al_nazra}, инфра. {region.infrastructure}"
        )
        if show_hideouts and region.region_id in hideout_regions:
            revealed = any(
                h.region_id == region.region_id and h.revealed for h in state.hideouts
            )
            if revealed:
                lines.append("⚠️ Логово Al Nazra подтверждено.")
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
    for index, role_id in enumerate(roles, start=1):
        lines.append(
            f"{index}. {esc(_role_name(pack, role_id))} (<code>{esc(role_id)}</code>)"
        )
    state = session.state
    if state is not None:
        lines.append("")
        lines.append(
            f"Ход {state.turn}/{state.total_turns}. Бюджет: {state.budget} млн"
        )
        submitted = [r for r in roles if state.submissions.get(r)]
        if submitted:
            names = ", ".join(_role_name(pack, r) for r in submitted)
            lines.append(f"Заявки поданы: {escape(names)}")
        if player.confirmed:
            lines.append("✅ Вы готовы к разрешению хода.")
        else:
            lines.append("Выберите действия кнопками ниже, затем нажмите «Готов».")
    return lines


def format_research_menu(session) -> list[str]:
    pack = session.pack
    state = session.state
    if pack is None or state is None:
        return ["Игра ещё не запущена."]
    lines = ["<b>Доступные технологии:</b>", ""]
    branches: dict[str, list] = {}
    for tech in pack.tech_tree:
        branches.setdefault(tech.branch, []).append(tech)
    for branch in sorted(branches):
        lines.append(f"<b>{esc(branch)}:</b>")
        for tech in sorted(branches[branch], key=lambda t: t.tier):
            done = " ✅" if tech.id in state.researched else ""
            lines.append(
                f"- {esc(tech.name)} (<code>{esc(tech.id)}</code>) — {tech.cost} млн{done}"
            )
        lines.append("")
    lines.append("Выберите технологию для исследования.")
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
            lines.append("Проголосуйте за один вариант.")
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
            lines.append(
                f"- {esc(_role_name(pack, role_id))} (<code>{esc(role_id)}</code>)"
            )
    else:
        lines.append("Роли не назначены.")
    lines.append("")
    if state is None:
        lines.append("Игра ещё не запущена.")
        return lines
    lines.append("<b>Заявки хода:</b>")
    has_any = False
    for role_id in player.role_ids:
        for sub in state.submissions.get(role_id, []):
            has_any = True
            if sub.kind == "action":
                target = f" → {esc(sub.region_id)}" if sub.region_id else ""
                lines.append(
                    f"- {esc(_role_name(pack, role_id))}: {esc(sub.action_id)}{target}"
                )
            elif sub.kind == "research":
                lines.append(
                    f"- {esc(_role_name(pack, role_id))}: исследование {esc(sub.tech_id)}"
                )
    if not has_any:
        lines.append("- пока нет")
    lines.append("")
    if state.researched:
        lines.append(f"Исследовано: {esc(', '.join(state.researched))}")
    else:
        lines.append("Исследовано: пока ничего")
    if state.event_id:
        vote = state.event_votes.get(user_id)
        lines.append(f"Голос по событию: {esc(vote) if vote else 'не голосовали'}")
    lines.append(f"Готов: {'да ✅' if player.confirmed else 'нет'}")
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
        "/help — помощь",
        "",
        "<b>Личные сообщения:</b>",
        "/menu — главное меню штаба",
        "/actions [номер роли] — действия ролей",
        "/research — технологии",
        "/regions — состояние регионов",
        "/event — голосование по событию",
        "/confirm — готов",
        "/cancel — сбросить заявки хода",
        "/loy — личная карточка",
        "/help — помощь",
    ]
