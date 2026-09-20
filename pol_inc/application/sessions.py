from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass

from pol_inc.config import Settings
from pol_inc.domain.enums import SessionStatus
from pol_inc.domain.errors import (
    ChatAlreadyHasSession,
    GameNotRunning,
    NotSessionCreator,
    SessionAttachedToAnotherChat,
    SessionCannotStart,
    SessionNotFound,
    UserAlreadyInSession,
    UserNotInSession,
    VoteError,
)
from pol_inc.domain.packs import GamePack, GamePackMeta
from pol_inc.domain.session import Party, PartyRecord, Session, TurnResolution
from pol_inc.application.parties import PartyRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class JoinResult:
    session: Session
    already_joined: bool


@dataclass(slots=True)
class LeaveResult:
    code: str
    closed: bool
    closed_by_creator: bool
    eliminated: bool = False
    resolution: TurnResolution | None = None
    session: Session | None = None


class SessionManager:
    _alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(self, settings: Settings, party_repo: PartyRepository | None = None) -> None:
        self._settings = settings
        self._sessions: dict[str, Session] = {}
        self._chat_to_code: dict[int, str] = {}
        self._user_to_code: dict[int, str] = {}
        self._lock = asyncio.Lock()
        self._party_repo = party_repo

    def get(self, code: str) -> Session:
        session = self._sessions.get(code.upper())
        if session is None:
            raise SessionNotFound("Сессия не найдена.")
        return session

    def get_by_chat(self, chat_id: int) -> Session | None:
        code = self._chat_to_code.get(chat_id)
        if code is None:
            return None
        return self._sessions.get(code)

    def get_by_user(self, user_id: int) -> Session | None:
        code = self._user_to_code.get(user_id)
        if code is None:
            return None
        return self._sessions.get(code)

    async def create(
        self,
        chat_id: int,
        user_id: int,
        username: str | None,
        display_name: str | None = None,
    ) -> Session:
        async with self._lock:
            if chat_id in self._chat_to_code:
                raise ChatAlreadyHasSession("В этом чате уже есть игровая сессия.")

            if user_id in self._user_to_code:
                raise UserAlreadyInSession("Вы уже участвуете в другой сессии.")

            code = self._generate_code()
            session = Session(
                code=code,
                chat_id=chat_id,
                creator_id=user_id,
                max_players=self._settings.max_players,
                min_players=self._settings.min_players,
            )

            session.add_player(
                user_id=user_id,
                username=username,
                display_name=display_name,
            )

            self._sessions[code] = session
            self._chat_to_code[chat_id] = code
            self._user_to_code[user_id] = code

            await self._apply_persisted_party_locked(session, user_id)

            return session

    async def join(
        self,
        code: str,
        chat_id: int,
        user_id: int,
        username: str | None,
        display_name: str | None = None,
    ) -> JoinResult:
        async with self._lock:
            session = self._sessions.get(code.upper())
            if session is None:
                raise SessionNotFound("Сессия не найдена.")

            if chat_id != session.chat_id:
                raise SessionAttachedToAnotherChat("Сессия привязана к другому чату.")

            existing_code = self._user_to_code.get(user_id)
            if existing_code:
                if existing_code == session.code and user_id in session.players:
                    return JoinResult(session=session, already_joined=True)

                raise UserAlreadyInSession("Вы уже участвуете в другой сессии.")

            session.add_player(
                user_id=user_id,
                username=username,
                display_name=display_name,
            )

            self._user_to_code[user_id] = session.code

            await self._apply_persisted_party_locked(session, user_id)

            return JoinResult(session=session, already_joined=False)

    async def leave(self, user_id: int) -> LeaveResult:
        async with self._lock:
            code = self._user_to_code.get(user_id)
            if code is None:
                raise UserNotInSession("Вы не участвуете в сессии.")

            session = self._sessions.get(code)
            if session is None:
                self._user_to_code.pop(user_id, None)
                raise SessionNotFound("Сессия не найдена.")

            if session.status == SessionStatus.NEW:
                closed_by_creator = user_id == session.creator_id
                closed = closed_by_creator or len(session.players) <= 1

                if closed:
                    self._close_locked(session)
                else:
                    session.remove_player(user_id)
                    self._user_to_code.pop(user_id, None)

                return LeaveResult(
                    code=code,
                    closed=closed,
                    closed_by_creator=closed_by_creator,
                    eliminated=False,
                    resolution=None,
                    session=session,
                )

            if session.status == SessionStatus.IN_GAME:
                session.drop_player(user_id)
                self._user_to_code.pop(user_id, None)

                if all(player.eliminated for player in session.players.values()):
                    self._close_locked(session)
                    return LeaveResult(
                        code=code,
                        closed=True,
                        closed_by_creator=False,
                        eliminated=True,
                        resolution=None,
                        session=session,
                    )

                resolution: TurnResolution | None = None

                if session.pack is not None:
                    session.ensure_auto_votes(session.pack)

                    if session.all_votes_ready():
                        resolution = session.resolve_turn(session.pack)

                        if resolution.game_finished:
                            self._finish_locked(session)

                return LeaveResult(
                    code=code,
                    closed=False,
                    closed_by_creator=False,
                    eliminated=True,
                    resolution=resolution,
                    session=session,
                )

            self._user_to_code.pop(user_id, None)

            return LeaveResult(
                code=code,
                closed=False,
                closed_by_creator=False,
                eliminated=False,
                resolution=None,
                session=session,
            )

    async def close(self, code: str, requester_id: int) -> Session:
        async with self._lock:
            session = self._sessions.get(code.upper())
            if session is None:
                raise SessionNotFound("Сессия не найдена.")

            if requester_id != session.creator_id:
                raise NotSessionCreator("Закрыть сессию может только создатель.")

            self._close_locked(session)
            return session

    async def set_pack(
        self,
        chat_id: int,
        user_id: int,
        meta: GamePackMeta,
        pack: GamePack,
    ) -> Session:
        async with self._lock:
            code = self._chat_to_code.get(chat_id)
            if code is None:
                raise SessionNotFound("В этом чате нет игровой сессии.")

            session = self._sessions[code]

            if user_id != session.creator_id:
                raise NotSessionCreator("Менять параметры сессии может только создатель.")

            session.set_pack(meta=meta, pack=pack)
            return session

    async def set_duration(self, chat_id: int, user_id: int, turns: int) -> Session:
        async with self._lock:
            code = self._chat_to_code.get(chat_id)
            if code is None:
                raise SessionNotFound("В этом чате нет игровой сессии.")

            session = self._sessions[code]

            if user_id != session.creator_id:
                raise NotSessionCreator("Менять параметры сессии может только создатель.")

            session.set_duration(turns)
            return session

    async def register_party(self, user_id: int, party: Party) -> Session | None:
        if self._party_repo is not None:
            record = PartyRecord.from_party(user_id=user_id, party=party)
            await self._party_repo.upsert(record)

        async with self._lock:
            code = self._user_to_code.get(user_id)
            if code is None:
                return None

            session = self._sessions[code]
            if session.status != SessionStatus.NEW:
                return session

            session.register_party(user_id=user_id, party=party)
            return session

    async def get_persisted_party(self, user_id: int) -> Party | None:
        if self._party_repo is None:
            return None
        record = await self._party_repo.get(user_id)
        if record is None:
            return None
        return record.to_party()

    async def start_game(self, chat_id: int, user_id: int) -> Session:
        async with self._lock:
            code = self._chat_to_code.get(chat_id)
            if code is None:
                raise SessionNotFound("В этом чате нет игровой сессии.")

            session = self._sessions[code]

            if user_id != session.creator_id:
                raise NotSessionCreator("Запустить игру может только создатель сессии.")

            session.start_game()

            if session.pack is not None:
                session.ensure_auto_votes(session.pack)

            return session

    async def register_vote(
        self,
        user_id: int,
        choice: str,
    ) -> tuple[Session, bool, TurnResolution | None]:
        async with self._lock:
            code = self._user_to_code.get(user_id)
            if code is None:
                raise UserNotInSession("Вы не участвуете в сессии.")

            session = self._sessions[code]

            if session.status != SessionStatus.IN_GAME:
                raise GameNotRunning("Голосование доступно только в запущенной игре.")

            if session.pack is None:
                raise SessionCannotStart("В сессии не выбран пак.")

            faction_id = self._parse_faction_choice(session.pack, choice)
            changed = session.register_vote(user_id=user_id, faction_id=faction_id)

            session.ensure_auto_votes(session.pack)

            resolution: TurnResolution | None = None

            if session.all_votes_ready():
                resolution = session.resolve_turn(session.pack)

                if resolution.game_finished:
                    self._finish_locked(session)

            return session, changed, resolution

    async def close_expired(self) -> list[Session]:
        async with self._lock:
            expired: list[Session] = []

            for session in list(self._sessions.values()):
                if session.is_expired(self._settings.session_ttl_hours):
                    expired.append(session)
                    self._close_locked(session)

            return expired

    async def set_lobby_message_id(self, chat_id: int, message_id: int) -> None:
        async with self._lock:
            code = self._chat_to_code.get(chat_id)
            if code is None:
                return

            session = self._sessions.get(code)
            if session is not None:
                session.lobby_message_id = message_id

    async def set_info_banner_message_id(self, chat_id: int, message_id: int) -> None:
        async with self._lock:
            code = self._chat_to_code.get(chat_id)
            if code is None:
                return

            session = self._sessions.get(code)
            if session is not None:
                session.info_banner_message_id = message_id

    async def set_turn_message_id(self, chat_id: int, message_id: int) -> None:
        async with self._lock:
            code = self._chat_to_code.get(chat_id)
            if code is None:
                return

            session = self._sessions.get(code)
            if session is not None:
                session.turn_message_id = message_id

    def _generate_code(self) -> str:
        while True:
            code = "".join(secrets.choice(self._alphabet) for _ in range(4))
            if code not in self._sessions:
                return code

    async def _apply_persisted_party_locked(self, session: Session, user_id: int) -> None:
        if self._party_repo is None:
            return

        try:
            record = await self._party_repo.get(user_id)
        except Exception as exc:
            logger.warning(
                "Не удалось загрузить сохранённую партию user_id=%s: %s", user_id, exc
            )
            return

        if record is None:
            return

        player = session.players.get(user_id)
        if player is None:
            return

        try:
            player.party = record.to_party()
        except Exception as exc:
            logger.warning(
                "Сохранённая партия user_id=%s некорректна: %s", user_id, exc
            )

    def _close_locked(self, session: Session) -> None:
        for user_id in list(session.players.keys()):
            self._user_to_code.pop(user_id, None)

        self._chat_to_code.pop(session.chat_id, None)
        self._sessions.pop(session.code, None)
        session.status = SessionStatus.CLOSED

    def _finish_locked(self, session: Session) -> None:
        for user_id in list(session.players.keys()):
            self._user_to_code.pop(user_id, None)

        self._chat_to_code.pop(session.chat_id, None)
        self._sessions.pop(session.code, None)

    @staticmethod
    def _parse_faction_choice(pack: GamePack, choice: str) -> str:
        raw = choice.strip().lower()

        if not raw:
            raise VoteError("Укажите номер фракции.")

        if raw.isdigit():
            index = int(raw) - 1

            if 0 <= index < len(pack.factions):
                return pack.factions[index].id

            raise VoteError("Номер фракции вне диапазона.")

        for faction in pack.factions:
            if faction.id.lower() == raw or faction.name.lower() == raw:
                return faction.id

        raise VoteError("Фракция не найдена.")