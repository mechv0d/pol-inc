from html import escape

from pol_inc.domain.enums import SessionStatus
from pol_inc.domain.packs import GamePackMeta
from pol_inc.domain.session import Session

STATUS_LABELS = {
    SessionStatus.NEW: "Новая",
    SessionStatus.IN_GAME: "В игре",
    SessionStatus.FINISHED: "Завершена",
    SessionStatus.CLOSED: "Закрыта",
}


def esc(value: object) -> str:
    return escape(str(value))


def format_session(session: Session) -> list[str]:
    pack_name = esc(session.pack_meta.name) if session.pack_meta else "не выбран"

    lines = [
        f"<b>Сессия:</b> <code>{esc(session.code)}</code>",
        f"<b>Статус:</b> {STATUS_LABELS.get(session.status, session.status.value)}",
        f"<b>Ходов:</b> {session.duration}",
        f"<b>Игроков:</b> {len(session.players)}/{session.max_players}",
        f"<b>Пак:</b> {pack_name}",
        "",
        "<b>Игроки:</b>",
    ]

    if not session.players:
        lines.append("- пусто")
        return lines

    for player in session.players.values():
        name = esc(player.username) if player.username else esc(player.user_id)
        prefix = "👑 " if player.user_id == session.creator_id else ""
        party = f" — {esc(player.party.name)}" if player.party else ""

        lines.append(f"- {prefix}{name}{party}")

    return lines


def format_pack_list(metas: list[GamePackMeta]) -> list[str]:
    if not metas:
        return ["Доступных паков пока нет."]

    lines = ["<b>Доступные GamePack:</b>"]

    for meta in metas:
        description = f" {esc(meta.description)}" if meta.description else ""
        lines.append(f"- <code>{esc(meta.id)}</code> — {esc(meta.name)}.{description}")

    lines.append("")
    lines.append("Установка: /ss pack <id>")

    return lines