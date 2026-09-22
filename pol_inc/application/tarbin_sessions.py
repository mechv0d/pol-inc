from __future__ import annotations

import asyncio
import random
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pol_inc.application.tarbin_packs import TarbinPackMeta
from pol_inc.config import Settings
from pol_inc.domain.enums import SessionStatus
from pol_inc.domain.errors import (
    ActionError,
    ChatAlreadyHasSession,
    NotSessionCreator,
    SessionAlreadyStarted,
    SessionAttachedToAnotherChat,
    SessionCannotStart,
    SessionFull,
    SessionNotFound,
    UserAlreadyInSession,
    UserNotInSession,
)
from pol_inc.domain.tarbin_game import (
    PRIORITY_DIRECTIONS,
    GameState,
    Submission,
    TurnReport,
    effective_cost,
    new_game_state,
    pick_event_for_turn,
    resolve_turn,
    slots_for_role,
    validate_action_submit,
    validate_research_submit,
)
from pol_inc.domain.tarbin_pack import (
    FULL_STAFF,
    TarbinGamePack,
    active_roles_for_players,
)


@dataclass(slots=True)
class TarbinPlayer:
    user_id: int
    username: str | None
    display_name: str | None = None
    role_ids: list[str] = field(default_factory=list)

    @property
    def public_name(self) -> str:
        if self.display_name:
            return self.display_name

        if self.username:
            return f"@{self.username}"

        return str(self.user_id)


@dataclass(slots=True)
class TarbinSession:
    code: str
    chat_id: int
    creator_id: int
    operation_name: str = "ОПЕРАЦИЯ TARBIN"
    status: SessionStatus = SessionStatus.NEW
    players: dict[int, TarbinPlayer] = field(default_factory=dict)
    pack_meta: TarbinPackMeta | None = None
    pack: TarbinGamePack | None = None
    duration: int = 8
    max_players: int = 6
    min_players: int = 2
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lobby_message_id: int | None = None
    briefing_message_id: int | None = None
    state: GameState | None = None
    active_roles: list[str] = field(default_factory=list)
    role_owners: dict[str, int] = field(default_factory=dict)
    next_ready: set[int] = field(default_factory=set)
    menu_message_ids: dict[int, int] = field(default_factory=dict)
    last_report: TurnReport | None = None

    def owner_of(self, role_id: str) -> TarbinPlayer | None:
        user_id = self.role_owners.get(role_id)
        if user_id is None:
            return None
        return self.players.get(user_id)

    def roles_of(self, user_id: int) -> list[str]:
        player = self.players.get(user_id)
        if player is None:
            return []
        return [role for role in player.role_ids if role in self.active_roles]


@dataclass(slots=True)
class TarbinJoinResult:
    session: TarbinSession
    already_joined: bool


@dataclass(slots=True)
class TarbinLeaveResult:
    code: str
    closed: bool
    closed_by_creator: bool
    vacated_roles: list[str] = field(default_factory=list)
    report: TurnReport | None = None
    session: TarbinSession | None = None


@dataclass(slots=True)
class ActionOption:
    action_id: str
    name: str
    cost: int
    locked_reason: str = ""


@dataclass(slots=True)
class ResearchOption:
    tech_id: str
    name: str
    branch: str
    cost: int
    locked_reason: str = ""


class TarbinSessionManager:
    _alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sessions: dict[str, TarbinSession] = {}
        self._chat_to_code: dict[int, str] = {}
        self._user_to_code: dict[int, str] = {}
        self._lock = asyncio.Lock()
        self._rng = random.SystemRandom()

    # ----- поиск -----

    def get(self, code: str) -> TarbinSession:
        session = self._sessions.get(code.upper())
        if session is None:
            raise SessionNotFound("Сессия не найдена.")
        return session

    def get_by_chat(self, chat_id: int) -> TarbinSession | None:
        code = self._chat_to_code.get(chat_id)
        if code is None:
            return None
        return self._sessions.get(code)

    def get_by_user(self, user_id: int) -> TarbinSession | None:
        code = self._user_to_code.get(user_id)
        if code is None:
            return None
        return self._sessions.get(code)

    # ----- лобби -----

    async def create(
        self,
        chat_id: int,
        user_id: int,
        username: str | None,
        display_name: str | None = None,
    ) -> TarbinSession:
        async with self._lock:
            if chat_id in self._chat_to_code:
                raise ChatAlreadyHasSession("В этом чате уже есть операция.")

            if user_id in self._user_to_code:
                raise UserAlreadyInSession("Вы уже участвуете в другой операции.")

            code = self._generate_code()
            session = TarbinSession(
                code=code,
                chat_id=chat_id,
                creator_id=user_id,
                max_players=self._settings.max_players,
                min_players=self._settings.min_players,
            )
            session.players[user_id] = TarbinPlayer(
                user_id=user_id,
                username=username,
                display_name=display_name,
            )

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
        display_name: str | None = None,
    ) -> TarbinJoinResult:
        async with self._lock:
            session = self._sessions.get(code.upper())
            if session is None:
                raise SessionNotFound("Операция не найдена.")

            if chat_id != session.chat_id:
                raise SessionAttachedToAnotherChat("Операция привязана к другому чату.")

            existing_code = self._user_to_code.get(user_id)
            if existing_code:
                if existing_code == session.code and user_id in session.players:
                    return TarbinJoinResult(session=session, already_joined=True)

                raise UserAlreadyInSession("Вы уже участвуете в другой операции.")

            if session.status != SessionStatus.NEW:
                raise SessionAlreadyStarted("Операция уже запущена.")

            if len(session.players) >= session.max_players:
                raise SessionFull("В операции уже максимум участников.")

            session.players[user_id] = TarbinPlayer(
                user_id=user_id,
                username=username,
                display_name=display_name,
            )
            self._user_to_code[user_id] = session.code

            return TarbinJoinResult(session=session, already_joined=False)

    async def leave(self, user_id: int) -> TarbinLeaveResult:
        async with self._lock:
            code = self._user_to_code.get(user_id)
            if code is None:
                raise UserNotInSession("Вы не участвуете в операции.")

            session = self._sessions.get(code)
            if session is None:
                self._user_to_code.pop(user_id, None)
                raise SessionNotFound("Операция не найдена.")

            if session.status == SessionStatus.NEW:
                closed_by_creator = user_id == session.creator_id
                closed = closed_by_creator or len(session.players) <= 1

                if closed:
                    self._close_locked(session)
                else:
                    session.players.pop(user_id, None)
                    self._user_to_code.pop(user_id, None)

                return TarbinLeaveResult(
                    code=code,
                    closed=closed,
                    closed_by_creator=closed_by_creator,
                    session=session,
                )

            if session.status == SessionStatus.IN_GAME and session.state is not None:
                vacated = [
                    role
                    for role, owner in session.role_owners.items()
                    if owner == user_id
                ]
                for role in vacated:
                    session.role_owners.pop(role, None)
                    if role not in session.state.vacant_roles:
                        session.state.vacant_roles.append(role)

                player = session.players.pop(user_id, None)
                if player is not None:
                    player.role_ids = []
                self._user_to_code.pop(user_id, None)

                report: TurnReport | None = None
                if session.players and self._is_ready_locked(session):
                    report = self._resolve_locked(session)
                    if report.result:
                        self._finish_locked(session)
                    else:
                        self._advance_locked(session)

                if not session.players:
                    self._close_locked(session)
                    return TarbinLeaveResult(
                        code=code,
                        closed=True,
                        closed_by_creator=False,
                        vacated_roles=vacated,
                        report=report,
                        session=session,
                    )

                return TarbinLeaveResult(
                    code=code,
                    closed=False,
                    closed_by_creator=False,
                    vacated_roles=vacated,
                    report=report,
                    session=session,
                )

            self._user_to_code.pop(user_id, None)
            return TarbinLeaveResult(
                code=code,
                closed=False,
                closed_by_creator=False,
                session=session,
            )

    async def close(self, code: str, requester_id: int) -> TarbinSession:
        async with self._lock:
            session = self._sessions.get(code.upper())
            if session is None:
                raise SessionNotFound("Операция не найдена.")

            if requester_id != session.creator_id:
                raise NotSessionCreator("Закрыть операцию может только создатель.")

            self._close_locked(session)
            return session

    # ----- настройки -----

    async def set_pack(
        self,
        chat_id: int,
        user_id: int,
        meta: TarbinPackMeta,
        pack: TarbinGamePack,
    ) -> TarbinSession:
        async with self._lock:
            session = self._session_by_chat_locked(chat_id)

            if user_id != session.creator_id:
                raise NotSessionCreator("Менять параметры может только создатель.")

            if session.status != SessionStatus.NEW:
                raise SessionAlreadyStarted("Нельзя менять пак после старта.")

            if pack.id != meta.id:
                raise SessionCannotStart("Идентификатор пака не совпадает с индексом.")

            session.pack_meta = meta
            session.pack = pack
            if pack.durations:
                session.duration = pack.durations[0]
            return session

    async def set_duration(
        self, chat_id: int, user_id: int, turns: int
    ) -> TarbinSession:
        async with self._lock:
            session = self._session_by_chat_locked(chat_id)

            if user_id != session.creator_id:
                raise NotSessionCreator("Менять параметры может только создатель.")

            if session.status != SessionStatus.NEW:
                raise SessionAlreadyStarted("Нельзя менять длительность после старта.")

            if session.pack is None:
                raise SessionCannotStart("Сначала выберите пак.")

            if turns not in session.pack.durations:
                available = ", ".join(str(d) for d in session.pack.durations)
                raise SessionCannotStart(
                    f"Длительность {turns} недоступна. Доступно: {available}."
                )

            session.duration = turns
            return session

    async def set_operation_name(
        self, chat_id: int, user_id: int, name: str
    ) -> TarbinSession:
        async with self._lock:
            session = self._session_by_chat_locked(chat_id)

            if user_id != session.creator_id:
                raise NotSessionCreator("Название задаёт только создатель.")

            if session.status != SessionStatus.NEW:
                raise SessionAlreadyStarted("Нельзя менять название после старта.")

            name = name.strip()[:40]
            if not name:
                raise SessionCannotStart("Название операции не может быть пустым.")

            session.operation_name = name
            return session

    # ----- старт -----

    async def start_game(self, chat_id: int, user_id: int) -> TarbinSession:
        async with self._lock:
            session = self._session_by_chat_locked(chat_id)

            if user_id != session.creator_id:
                raise NotSessionCreator("Запустить игру может только создатель.")

            if session.status != SessionStatus.NEW:
                raise SessionAlreadyStarted("Операция уже запущена.")

            if session.pack is None:
                raise SessionCannotStart("Не выбран пак (/ss pack id).")

            min_players = max(2, session.pack.settings.min_players)
            if len(session.players) < min_players:
                raise SessionCannotStart(f"Нужно минимум {min_players} игрока.")

            active = active_roles_for_players(len(session.players))
            players = list(session.players.values())
            session.active_roles = active
            session.role_owners = {}

            for player in players:
                player.role_ids = [
                    role_id for role_id in player.role_ids if role_id in active
                ]

            for player in players:
                for role_id in player.role_ids:
                    if role_id not in session.role_owners:
                        session.role_owners[role_id] = player.user_id

            unclaimed = [
                role_id for role_id in active if role_id not in session.role_owners
            ]
            for role_id in unclaimed:
                owner = min(players, key=lambda p: len(p.role_ids))
                owner.role_ids.append(role_id)
                session.role_owners[role_id] = owner.user_id

            state = new_game_state(session.pack, session.duration, self._rng)
            state.active_roles = list(active)
            session.state = state
            session.status = SessionStatus.IN_GAME

            pick_event_for_turn(session.pack, state, self._rng)

            return session

    # ----- ходы: заявки -----

    async def submit_action(
        self, user_id: int, role_id: str, action_id: str, region_id: str = ""
    ) -> bool:
        async with self._lock:
            session, player, state = self._player_state_locked(user_id)
            self._require_role_owner(session, player, role_id)

            if state is None or session.pack is None:
                raise ActionError("Игра сейчас не запущена.")

            cost, error = validate_action_submit(
                session.pack, state, role_id, action_id, region_id
            )
            if error:
                raise ActionError(error)

            action = session.pack.action_by_id(action_id)
            if action is None:
                raise ActionError("Действие не найдено.")

            if "mobilize" in action.tags:
                state.mobilization_turns_left = 3
                state.mobilization_active = True

            state.submissions.setdefault(role_id, []).append(
                Submission(
                    role_id=role_id,
                    kind="action",
                    action_id=action_id,
                    region_id=region_id,
                    cost_paid=cost,
                )
            )

            return self._is_ready_locked(session)

    async def submit_research(self, user_id: int, role_id: str, tech_id: str) -> bool:
        async with self._lock:
            session, player, state = self._player_state_locked(user_id)
            self._require_role_owner(session, player, role_id)

            if state is None or session.pack is None:
                raise ActionError("Игра сейчас не запущена.")

            cost, error = validate_research_submit(
                session.pack, state, role_id, tech_id
            )
            if error:
                raise ActionError(error)

            state.budget -= cost
            state.submissions.setdefault(role_id, []).append(
                Submission(
                    role_id=role_id,
                    kind="research",
                    tech_id=tech_id,
                    cost_paid=cost,
                )
            )

            return self._is_ready_locked(session)

    async def pass_role(self, user_id: int, role_id: str) -> bool:
        async with self._lock:
            session, player, state = self._player_state_locked(user_id)
            self._require_role_owner(session, player, role_id)

            if state is None or session.pack is None:
                raise ActionError("Игра сейчас не запущена.")

            used = len(state.submissions.get(role_id, []))
            if used >= slots_for_role(session.pack, state):
                raise ActionError("У роли больше нет действий в этом ходу.")

            state.submissions.setdefault(role_id, []).append(
                Submission(role_id=role_id, kind="pass")
            )
            return self._is_ready_locked(session)

    async def reset_turn(self, user_id: int) -> None:
        async with self._lock:
            _session, player, state = self._player_state_locked(user_id)

            if state is None:
                return

            for role_id in player.role_ids:
                state.submissions.pop(role_id, None)

    async def set_priority(self, user_id: int, direction: str) -> None:
        async with self._lock:
            session, _player, state = self._player_state_locked(user_id)

            if state is None or session.pack is None:
                raise ActionError("Игра сейчас не запущена.")

            if session.role_owners.get("commander") != user_id:
                raise ActionError("Приоритет задаёт только Главнокомандующий.")

            if direction not in PRIORITY_DIRECTIONS:
                raise ActionError("Неизвестное направление.")

            state.priority = direction

    async def vote_event(self, user_id: int, option_id: str) -> bool:
        async with self._lock:
            session, _player, state = self._player_state_locked(user_id)

            if state is None or session.pack is None:
                raise ActionError("Игра сейчас не запущена.")

            if not state.event_id:
                raise ActionError("Сейчас нет активного события.")

            options = self._event_options(session, state)
            if option_id not in options:
                raise ActionError("Такого варианта нет.")

            state.event_votes[user_id] = option_id
            return self._is_ready_locked(session)

    async def confirm_next(self, user_id: int) -> bool:
        async with self._lock:
            code = self._user_to_code.get(user_id)
            if code is None:
                raise UserNotInSession("Вы не участвуете в операции.")

            session = self._sessions.get(code)
            if session is None:
                raise SessionNotFound("Операция не найдена.")

            if session.status != SessionStatus.IN_GAME or session.state is None:
                raise ActionError("Игра сейчас не запущена.")

            session.next_ready.add(user_id)
            return session.next_ready >= set(session.players.keys())

    async def pick_role(self, user_id: int, role_id: str) -> tuple[TarbinSession, bool]:
        """Выбор роли на этапе подготовки. Возвращает (сессия, выбрана?)."""
        async with self._lock:
            code = self._user_to_code.get(user_id)
            if code is None:
                raise UserNotInSession("Вы не участвуете в операции.")

            session = self._sessions.get(code)
            if session is None:
                raise SessionNotFound("Операция не найдена.")

            if session.status != SessionStatus.NEW:
                raise SessionAlreadyStarted("Роли выбираются до старта игры.")

            available = (
                [role.id for role in session.pack.roles]
                if session.pack is not None
                else list(FULL_STAFF)
            )
            if role_id not in available:
                raise ActionError("Такой роли нет.")

            player = session.players.get(user_id)
            if player is None:
                raise UserNotInSession("Вы не участвуете в операции.")

            for other in session.players.values():
                if other.user_id != user_id and role_id in other.role_ids:
                    raise ActionError("Роль уже занята.")

            if role_id in player.role_ids:
                player.role_ids.remove(role_id)
                return session, False

            player.role_ids.append(role_id)
            return session, True

    async def research_available(
        self, session: TarbinSession, role_id: str
    ) -> list[ResearchOption]:
        return [
            option
            for option in self.research_options(session, role_id)
            if not option.locked_reason
        ]

    async def resolve(self, chat_id: int) -> tuple[TarbinSession, TurnReport]:
        async with self._lock:
            session = self._session_by_chat_locked(chat_id)

            if session.status != SessionStatus.IN_GAME or session.state is None:
                raise ActionError("Игра сейчас не запущена.")

            if session.pack is None:
                raise ActionError("В операции нет пака.")

            if not self._is_ready_locked(session):
                raise ActionError(
                    "Ход не готов: нужны заявки всех ролей и голоса всех игроков."
                )

            report = self._resolve_locked(session)

            if report.result:
                self._finish_locked(session)

            return session, report

    async def advance_turn(self, chat_id: int) -> TarbinSession:
        async with self._lock:
            session = self._session_by_chat_locked(chat_id)

            if session.status != SessionStatus.IN_GAME or session.state is None:
                raise ActionError("Игра сейчас не запущена.")

            if session.pack is None:
                raise ActionError("В операции нет пака.")

            self._advance_locked(session)
            return session

    def _advance_locked(self, session: TarbinSession) -> None:
        assert session.pack is not None and session.state is not None
        session.state.turn += 1
        session.next_ready = set()
        pick_event_for_turn(session.pack, session.state, self._rng)

    # ----- данные для интерфейса -----

    def action_options(
        self, session: TarbinSession, role_id: str
    ) -> list[ActionOption]:
        if session.pack is None or session.state is None:
            return []

        state = session.state
        options: list[ActionOption] = []

        for action in session.pack.actions_for_role(role_id):
            probe_region = ""
            if action.target == "region" and state.regions:
                probe_region = next(iter(state.regions))
            cost, error = validate_action_submit(
                session.pack, state, role_id, action.id, probe_region
            )
            if error == "Укажите корректный регион.":
                error = ""
            if error and cost == 0:
                cost = effective_cost(session.pack, state, role_id, action.cost)

            options.append(
                ActionOption(
                    action_id=action.id,
                    name=action.name,
                    cost=cost,
                    locked_reason=error,
                )
            )

        return options

    def research_options(
        self, session: TarbinSession, role_id: str
    ) -> list[ResearchOption]:
        if session.pack is None or session.state is None:
            return []

        state = session.state
        options: list[ResearchOption] = []

        for tech in session.pack.tech_tree:
            cost, error = validate_research_submit(
                session.pack, state, role_id, tech.id
            )
            options.append(
                ResearchOption(
                    tech_id=tech.id,
                    name=tech.name,
                    branch=tech.branch,
                    cost=cost,
                    locked_reason=error,
                )
            )

        return options

    def intel_brief(self, session: TarbinSession) -> tuple[list[str], list[str], int]:
        if session.pack is None or session.state is None:
            return [], [], 0

        state = session.state
        intentions = [
            self._intention_name(session, intention_id)
            for intention_id in state.revealed_intentions
        ]
        regions = [
            state.regions[region_id].name
            for region_id in state.revealed_regions
            if region_id in state.regions
        ]
        hideouts = sum(1 for hideout in state.hideouts if hideout.revealed)
        return intentions, regions, hideouts

    # ----- внутреннее -----

    def _player_state_locked(
        self, user_id: int
    ) -> tuple[TarbinSession, TarbinPlayer, GameState | None]:
        code = self._user_to_code.get(user_id)
        if code is None:
            raise UserNotInSession("Вы не участвуете в операции.")

        session = self._sessions.get(code)
        if session is None:
            self._user_to_code.pop(user_id, None)
            raise SessionNotFound("Операция не найдена.")

        player = session.players.get(user_id)
        if player is None:
            raise UserNotInSession("Вы не участвуете в операции.")

        return session, player, session.state

    @staticmethod
    def _require_role_owner(
        session: TarbinSession, player: TarbinPlayer, role_id: str
    ) -> None:
        if role_id not in session.active_roles:
            raise ActionError("Эта роль неактивна.")
        if role_id not in player.role_ids:
            raise ActionError("Эта роль вам не принадлежит.")
        if session.state is not None and role_id in session.state.vacant_roles:
            raise ActionError("Роль вакантна.")

    def _is_ready_locked(self, session: TarbinSession) -> bool:
        if session.status != SessionStatus.IN_GAME or session.state is None:
            return False
        if session.pack is None:
            return False
        if not session.players:
            return False

        state = session.state
        for player in session.players.values():
            owned = [
                role
                for role in player.role_ids
                if role in session.active_roles and role not in state.vacant_roles
            ]
            if not owned:
                continue

            for role_id in owned:
                filled = len(state.submissions.get(role_id, []))
                if filled < slots_for_role(session.pack, state):
                    return False

        if state.event_id:
            for user_id in session.players:
                if user_id not in state.event_votes:
                    return False

        return True

    def _resolve_locked(self, session: TarbinSession) -> TurnReport:
        assert session.pack is not None and session.state is not None
        player_names = {
            user_id: player.public_name for user_id, player in session.players.items()
        }
        return resolve_turn(
            session.pack,
            session.state,
            dict(session.role_owners),
            self._rng,
            player_names,
        )

    def _session_by_chat_locked(self, chat_id: int) -> TarbinSession:
        code = self._chat_to_code.get(chat_id)
        if code is None:
            raise SessionNotFound("В этом чате нет операции.")

        session = self._sessions.get(code)
        if session is None:
            raise SessionNotFound("Операция не найдена.")

        return session

    def _event_options(
        self, session: TarbinSession, state: GameState
    ) -> dict[str, str]:
        if session.pack is None:
            return {}

        for event in session.pack.events:
            if event.id == state.event_id:
                return {option.id: option.title for option in event.options}

        return {}

    def _intention_name(self, session: TarbinSession, intention_id: str) -> str:
        if session.pack is None:
            return intention_id

        for intention in session.pack.al_nazra.intentions:
            if intention.id == intention_id:
                return intention.name

        return intention_id

    async def close_expired(self) -> list[TarbinSession]:
        async with self._lock:
            expired: list[TarbinSession] = []

            for session in list(self._sessions.values()):
                if self.is_expired(session, self._settings.session_ttl_hours):
                    expired.append(session)
                    self._close_locked(session)

            return expired

    async def set_lobby_message_id(self, chat_id: int, message_id: int) -> None:
        async with self._lock:
            session = self._chat_to_code.get(chat_id)
            if session is None:
                return

            target = self._sessions.get(session)
            if target is not None:
                target.lobby_message_id = message_id

    async def set_briefing_message_id(self, chat_id: int, message_id: int) -> None:
        async with self._lock:
            session = self._chat_to_code.get(chat_id)
            if session is None:
                return

            target = self._sessions.get(session)
            if target is not None:
                target.briefing_message_id = message_id

    def _generate_code(self) -> str:
        while True:
            code = "".join(secrets.choice(self._alphabet) for _ in range(4))
            if code not in self._sessions:
                return code

    def _close_locked(self, session: TarbinSession) -> None:
        for user_id in list(session.players.keys()):
            self._user_to_code.pop(user_id, None)

        self._chat_to_code.pop(session.chat_id, None)
        self._sessions.pop(session.code, None)
        session.status = SessionStatus.CLOSED

    def _finish_locked(self, session: TarbinSession) -> None:
        for user_id in list(session.players.keys()):
            self._user_to_code.pop(user_id, None)

        self._chat_to_code.pop(session.chat_id, None)
        self._sessions.pop(session.code, None)
        session.status = SessionStatus.FINISHED

    def is_expired(self, session: TarbinSession, ttl_hours: int) -> bool:
        if session.status == SessionStatus.CLOSED:
            return False

        if ttl_hours <= 0:
            return False

        from datetime import datetime, timedelta, timezone

        age = datetime.now(timezone.utc) - session.created_at
        return age > timedelta(hours=ttl_hours)
