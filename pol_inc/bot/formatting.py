from __future__ import annotations

from html import escape

from pol_inc.domain.enums import SessionStatus
from pol_inc.domain.packs import GameEvent, GamePack, ResourceDelta
from pol_inc.domain.session import Player, Session, TurnResolution

STATUS_LABELS = {
    SessionStatus.NEW: "Новая",
    SessionStatus.IN_GAME: "В игре",
    SessionStatus.FINISHED: "Завершена",
    SessionStatus.CLOSED: "Закрыта",
}


def esc(value: object) -> str:
    return escape(str(value))


def format_delta(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


def _party_name(player: Player) -> str:
    if player.party is None:
        return "Без партии"
    return player.party.name


def _player_name(player: Player) -> str:
    return player.public_name


def format_session(session: Session) -> list[str]:
    pack_name = esc(session.pack_meta.name) if session.pack_meta else "не выбран"

    lines = [
        f"<b>Сессия:</b> <code>{esc(session.code)}</code>",
        f"<b>Статус:</b> {STATUS_LABELS.get(session.status, session.status.value)}",
        f"<b>Ходов:</b> {session.duration}",
        f"<b>Игроков:</b> {len(session.players)}/{session.max_players}",
        f"<b>Пак:</b> {pack_name}",
    ]

    if session.status == SessionStatus.IN_GAME:
        lines.append(f"<b>Текущий ход:</b> {session.turn_number}/{session.total_turns}")

    lines.append("")
    lines.append("<b>Игроки:</b>")

    if not session.players:
        lines.append("- пусто")
        return lines

    for player in session.players.values():
        prefix = "👑 " if player.user_id == session.creator_id else ""
        party = f" — {esc(_party_name(player))}" if player.party else ""
        eliminated = " 🚩" if player.eliminated else ""

        lines.append(f"- {prefix}{esc(_player_name(player))}{party}{eliminated}")

    return lines


def format_lobby(session: Session) -> list[str]:
    pack_name = esc(session.pack_meta.name) if session.pack_meta else "не выбран"
    registered = session.registered_parties_count
    total = len(session.players)

    lines = [
        "<b>POL Inc. — лобби</b>",
        f"Код сессии: <code>{esc(session.code)}</code>",
        f"Статус: {STATUS_LABELS.get(session.status, session.status.value)}",
        f"Ходов: {session.duration}",
        f"Пак: {pack_name}",
        f"Игроков: {total}/{session.max_players}",
        f"Партий зарегистрировано: {registered}/{total}",
        "",
        "<b>Игроки:</b>",
    ]

    if not session.players:
        lines.append("- пусто")
        return lines

    for player in session.players.values():
        prefix = "👑 " if player.user_id == session.creator_id else ""

        if player.party is not None:
            icon = "✅"
            party_text = f" — {esc(player.party.name)}"
        else:
            icon = "❌"
            party_text = " — партия не зарегистрирована"

        lines.append(f"{icon} {prefix}{esc(_player_name(player))}{party_text}")

    lines.append("")

    if session.pack is None:
        lines.append("❌ Пак не выбран. Создатель может установить его через /ss pack id")

    if registered < total:
        lines.append("❌ Не все партии зарегистрированы.")
        lines.append(f"Зарегистрировано партий: {registered} из {total}.")
        lines.append("Каждый игрок должен отправить боту в личные сообщения команду /reg")
    elif session.pack is not None:
        lines.append("✅ Все партии зарегистрированы.")
        lines.append("Создатель может запустить игру: /startgame")

    return lines


def format_pack_list(metas: list) -> list[str]:
    if not metas:
        return ["Доступных паков пока нет."]

    lines = ["<b>Доступные GamePack:</b>"]

    for meta in metas:
        description = f" {esc(meta.description)}" if meta.description else ""
        lines.append(f"- <code>{esc(meta.id)}</code> — {esc(meta.name)}.{description}")

    lines.append("")
    lines.append("Установка: /ss pack id")

    return lines


def format_welcome(session: Session) -> list[str]:
    return [
        "<b>Игра началась!</b>",
        "",
        "Каждый ход бот будет публиковать событие.",
        "Ваша задача — тайно выбирать фракцию в личных сообщениях бота.",
        "",
        "Команда голосования: /vote номер",
        "Изменить голос можно не чаще одного раза в минуту.",
        "",
        "Побеждает партия с наибольшим количеством процентов избирателей.",
    ]


def format_turn(session: Session, pack: GamePack, event: GameEvent) -> list[str]:
    lines = [
        f"<b>Ход {session.turn_number}/{session.total_turns}.</b> {esc(event.title)}"
    ]

    if event.description:
        lines.append("")
        lines.append(esc(event.description))

    lines.append("")
    lines.append("<b>Партии:</b>")

    for player in session.players.values():
        eliminated = " 🚩" if player.eliminated else ""
        lines.append(
            f"{esc(_party_name(player))}, {esc(_player_name(player))}{eliminated} "
            f"— {player.percent}% {player.influence}v"
        )

    lines.append("")
    lines.append("<b>Доступные фракции:</b>")

    for index, faction in enumerate(pack.factions, start=1):
        emoji = faction.emoji or faction.id.emoji
        lines.append(f"{index}. {emoji} {esc(faction.name)}")

    lines.append("")
    lines.append("Выбор фракций тайный и проходит только в личных сообщениях бота.")
    lines.append("Команда: /vote номер")
    lines.append("Изменить выбор можно не чаще одного раза в минуту.")

    return lines


def format_resolution(session: Session, resolution: TurnResolution) -> list[str]:
    lines = [
        f"<b>Итог хода {resolution.turn_number}.</b>"
    ]

    if resolution.outcome.description:
        lines.append("")
        lines.append(esc(resolution.outcome.description))

    lines.append("")
    lines.append("<b>Результаты:</b>")

    for player in session.players.values():
        delta = resolution.deltas.get(player.user_id, ResourceDelta())
        vote_emoji = player.vote.emoji if player.vote else "❔"

        lines.append(
            f"{esc(_party_name(player))}, {esc(_player_name(player))} {vote_emoji}: "
            f"{format_delta(delta.percent)}% {format_delta(delta.influence)}v "
            f"→ {player.percent}% {player.influence}v"
        )

    if resolution.overtime_started:
        lines.append("")
        lines.append("По итогам основного времени ничья по процентам. Овертайм: +3 хода.")

    return lines


def format_final(session: Session) -> list[str]:
    players = list(session.players.values())

    if not players:
        return ["Игра завершена."]

    sorted_players = sorted(players, key=lambda player: player.percent, reverse=True)
    max_percent = sorted_players[0].percent
    winners = [player for player in sorted_players if player.percent == max_percent]

    lines = ["<b>Игра завершена.</b>", ""]

    if len(winners) == 1:
        winner = winners[0]
        lines.append(
            f"Победитель: {esc(_party_name(winner))}, {esc(_player_name(winner))} "
            f"— {winner.percent}%"
        )
    elif len(winners) == len(sorted_players):
        lines.append("Все игроки набрали одинаковое количество процентов. Все считаются проигравшими.")
    else:
        lines.append("Ничья между:")

        for player in winners:
            lines.append(
                f"- {esc(_party_name(player))}, {esc(_player_name(player))} — {player.percent}%"
            )

        lines.append("Остальные игроки считаются проигравшими.")

    lines.append("")
    lines.append("<b>Итоговая таблица:</b>")

    for player in sorted_players:
        eliminated = " 🚩" if player.eliminated else ""
        lines.append(
            f"{esc(_party_name(player))}, {esc(_player_name(player))}{eliminated} "
            f"— {player.percent}% {player.influence}v"
        )

    return lines