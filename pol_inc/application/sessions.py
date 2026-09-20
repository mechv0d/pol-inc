from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass

from pol_inc.config import Settings
from pol_inc.domain.enums import SessionStatus
from pol_inc.domain.errors import (
    ChatAlreadyHasSession,
    NotSessionCreator,
    SessionAttachedToAnotherChat,
    SessionNotFound,
    UserAlreadyInSession,
    UserNotInSession,
)
from pol_inc.domain.packs import GamePack, GamePackMeta
from pol_inc.domain.session import Party, Session


@dataclass(slots=True)
class JoinResult:
    session: Session
    already_joined: bool


@dataclass(slots=True)
class LeaveResult:
    code: str
    closed: bool
    closed_by_creator: bool


class SessionManager:
    _alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sessions: dict[str, Session] = {}
        self._chat_to_code: dict[int, str] = {}
        self._user_to_code: dict[int, str] = {}
        self._lock = asyncio.Lock()

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

    async def create(self, chat_id: int, user_id: int, username: str | None) -> Session:
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

            session.add_player(user_id=user_id, username=username)

            self._sessions[code] = session
            self._chat_to_code[chat_id] = code
            self._user_to_code[user_id] = code

            return session

    async def join(
        self,
        code: str,
        chat_id: int,
        user_id: int,
        username: str | None,
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

            session.add_player(user_id=user_id, username=username)
            self._user_to_code[user_id] = session.code

            return JoinResult(session=session, already_joined=False)

    async def leave(self, user_id: int) -> LeaveResult:
        async with self._lock:
            code = self._user_to_code.get(user_id)
            if code is None:
                raise UserNotInSession("Вы не участвуете в сессии.")

            session = self._sessions[code]
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

    async def register_party(self, user_id: int, party: Party) -> Session:
        async with self._lock:
            code = self._user_to_code.get(user_id)
            if code is None:
                raise UserNotInSession("Вы не участвуете в сессии.")

            session = self._sessions[code]
            session.register_party(user_id=user_id, party=party)
            return session

    async def close_expired(self) -> list[Session]:
        async with self._lock:
            expired: list[Session] = []

            for session in list(self._sessions.values()):
                if session.is_expired(self._settings.session_ttl_hours):
                    expired.append(session)
                    self._close_locked(session)

            return expired

    def _generate_code(self) -> str:
        while True:
            code = "".join(secrets.choice(self._alphabet) for _ in range(4))
            if code not in self._sessions:
                return code

    def _close_locked(self, session: Session) -> None:
        for user_id in list(session.players.keys()):
            self._user_to_code.pop(user_id, None)

        self._chat_to_code.pop(session.chat_id, None)
        self._sessions.pop(session.code, None)
        session.status = SessionStatus.CLOSED