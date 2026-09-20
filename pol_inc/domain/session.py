from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict

from pol_inc.domain.enums import FactionId, SessionStatus
from pol_inc.domain.errors import (
    GameNotRunning,
    PackMismatch,
    PartyValidationError,
    PlayerEliminated,
    PlayerNotFound,
    SessionAlreadyStarted,
    SessionCannotStart,
    SessionFull,
    UserAlreadyInSession,
    VoteChangeCooldown,
    VoteError,
)
from pol_inc.domain.packs import (
    EventOutcome,
    GameEvent,
    GamePack,
    GamePackMeta,
    ResourceDelta,
)

_rng = random.SystemRandom()


@dataclass(slots=True)
class Party:
    name: str
    slogan: str
    ideology: str
    line: str = ""
    photo_object: str | None = None

    @classmethod
    def create(
        cls,
        name: str,
        slogan: str,
        ideology: str,
        line: str = "",
        photo_object: str | None = None,
    ) -> "Party":
        name = name.strip()[:30]
        slogan = slogan.strip()[:50]
        ideology = ideology.strip()[:30]
        line = line.strip()[:600]

        if not name or not ideology:
            raise PartyValidationError("Название и идеология партии не могут быть пустыми.")

        return cls(
            name=name,
            slogan=slogan,
            ideology=ideology,
            line=line,
            photo_object=photo_object,
        )


class PartyRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: int
    name: str
    slogan: str = ""
    ideology: str
    line: str = ""
    photo_object: str | None = None

    def to_party(self) -> Party:
        return Party.create(
            name=self.name,
            slogan=self.slogan,
            ideology=self.ideology,
            line=self.line,
            photo_object=self.photo_object,
        )

    @classmethod
    def from_party(cls, user_id: int, party: Party) -> "PartyRecord":
        return cls(
            user_id=user_id,
            name=party.name,
            slogan=party.slogan,
            ideology=party.ideology,
            line=party.line,
            photo_object=party.photo_object,
        )


@dataclass(slots=True)
class Player:
    user_id: int
    username: str | None
    display_name: str | None = None
    party: Party | None = None

    percent: int = 0
    influence: int = 0

    vote: FactionId | None = None
    vote_changed_at: datetime | None = None

    eliminated: bool = False
    auto_vote: bool = False

    @property
    def public_name(self) -> str:
        if self.display_name:
            return self.display_name

        if self.username:
            return f"@{self.username}"

        return str(self.user_id)


@dataclass(slots=True)
class TurnResolution:
    event: GameEvent
    outcome: EventOutcome
    deltas: dict[int, ResourceDelta]
    turn_number: int
    overtime_started: bool = False
    game_finished: bool = False


@dataclass(slots=True)
class Session:
    code: str
    chat_id: int
    creator_id: int
    status: SessionStatus = SessionStatus.NEW
    players: dict[int, Player] = field(default_factory=dict)
    pack_meta: GamePackMeta | None = None
    pack: GamePack | None = None
    duration: int = 8
    max_players: int = 4
    min_players: int = 2
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    turn_number: int = 0
    total_turns: int = 0
    overtime_used: bool = False
    turn_plan: list[str] = field(default_factory=list)
    current_event_id: str | None = None

    lobby_message_id: int | None = None
    info_banner_message_id: int | None = None
    turn_message_id: int | None = None

    def add_player(
        self,
        user_id: int,
        username: str | None,
        display_name: str | None = None,
    ) -> None:
        if self.status != SessionStatus.NEW:
            raise SessionAlreadyStarted("Сессия уже запущена или закрыта.")

        if user_id in self.players:
            raise UserAlreadyInSession("Игрок уже состоит в этой сессии.")

        if len(self.players) >= self.max_players:
            raise SessionFull("В сессии уже максимальное количество игроков.")

        self.players[user_id] = Player(
            user_id=user_id,
            username=username,
            display_name=display_name,
        )

    def remove_player(self, user_id: int) -> None:
        self.players.pop(user_id, None)

    def drop_player(self, user_id: int) -> None:
        player = self.players.get(user_id)
        if player is None:
            raise PlayerNotFound("Игрок не найден в сессии.")

        if self.status == SessionStatus.NEW:
            self.remove_player(user_id)
            return

        if self.status == SessionStatus.IN_GAME:
            player.eliminated = True
            player.auto_vote = True
            player.vote = None
            player.vote_changed_at = None
            return

        raise SessionAlreadyStarted("Нельзя покинуть завершенную или закрытую сессию.")

    def set_pack(self, meta: GamePackMeta, pack: GamePack) -> None:
        if self.status != SessionStatus.NEW:
            raise SessionAlreadyStarted("Нельзя менять пак после старта сессии.")

        if pack.id != meta.id:
            raise PackMismatch("Идентификатор пака в файле не совпадает с индексом.")

        self.pack_meta = meta
        self.pack = pack

        if pack.durations:
            self.duration = pack.durations[0]

    def set_duration(self, turns: int) -> None:
        if self.status != SessionStatus.NEW:
            raise SessionAlreadyStarted("Нельзя менять длительность после старта сессии.")

        if self.pack is None:
            raise SessionCannotStart("Сначала выберите пак.")

        if turns not in self.pack.durations:
            available = ", ".join(str(duration) for duration in self.pack.durations)
            raise SessionCannotStart(
                f"Длительность {turns} недоступна для этого пака. Доступно: {available}."
            )

        self.duration = turns

    def register_party(self, user_id: int, party: Party) -> None:
        if self.status != SessionStatus.NEW:
            raise SessionAlreadyStarted("Нельзя регистрировать партию после старта сессии.")

        player = self.players.get(user_id)
        if player is None:
            raise PlayerNotFound("Игрок не найден в сессии.")

        player.party = party

    def is_expired(self, ttl_hours: int) -> bool:
        if self.status == SessionStatus.CLOSED:
            return False

        if ttl_hours <= 0:
            return False

        age = datetime.now(timezone.utc) - self.created_at
        return age > timedelta(hours=ttl_hours)

    @property
    def registered_parties_count(self) -> int:
        return sum(1 for player in self.players.values() if player.party is not None)

    def can_start(self) -> bool:
        return not self.start_blockers()

    def start_blockers(self) -> list[str]:
        blockers: list[str] = []

        if self.pack is None:
            blockers.append("не выбран пак (/ss pack id)")

        if len(self.players) < self.min_players:
            blockers.append(f"нужно минимум {self.min_players} игрока")

        missing = [player for player in self.players.values() if player.party is None]
        if missing:
            names = ", ".join(player.public_name for player in missing)
            blockers.append(f"не зарегистрированы партии: {names}")

        return blockers

    def start_game(self) -> None:
        if self.status != SessionStatus.NEW:
            raise SessionAlreadyStarted("Сессия уже запущена или закрыта.")

        blockers = self.start_blockers()
        if blockers:
            raise SessionCannotStart("Нельзя запустить игру: " + "; ".join(blockers) + ".")

        if self.pack is None:
            raise SessionCannotStart("Пак не выбран.")

        self.status = SessionStatus.IN_GAME
        self.total_turns = self.duration
        self.turn_plan = self._build_turn_plan(self.pack, self.total_turns)
        self.turn_number = 1
        self.current_event_id = self.turn_plan[0]

        for player in self.players.values():
            player.percent = 0
            player.influence = 0
            player.vote = None
            player.vote_changed_at = None
            player.eliminated = False
            player.auto_vote = False

    def get_current_event(self, pack: GamePack) -> GameEvent:
        if self.current_event_id is None:
            raise GameNotRunning("Текущий ход не задан.")

        for event in pack.events:
            if event.id == self.current_event_id:
                return event

        raise GameNotRunning("Текущее событие не найдено в паке.")

    def register_vote(self, user_id: int, faction_id: FactionId) -> bool:
        if self.status != SessionStatus.IN_GAME:
            raise GameNotRunning("Голосование доступно только в запущенной игре.")

        player = self.players.get(user_id)
        if player is None:
            raise PlayerNotFound("Игрок не найден в сессии.")

        if player.eliminated or player.auto_vote:
            raise PlayerEliminated("Вы покинули игру и не можете голосовать вручную.")

        if player.vote == faction_id:
            return False

        now = datetime.now(timezone.utc)

        if player.vote is not None and player.vote_changed_at is not None:
            if now - player.vote_changed_at < timedelta(minutes=1):
                raise VoteChangeCooldown("Изменить голос можно не чаще одного раза в минуту.")

        player.vote = faction_id
        player.vote_changed_at = now
        return True

    def ensure_auto_votes(self, pack: GamePack) -> None:
        if self.status != SessionStatus.IN_GAME:
            return

        faction_ids = [faction.id for faction in pack.factions]
        if not faction_ids:
            faction_ids = list(FactionId)

        for player in self.players.values():
            if player.auto_vote and player.vote is None:
                player.vote = _rng.choice(faction_ids)

    def all_votes_ready(self) -> bool:
        if self.status != SessionStatus.IN_GAME:
            return False

        if not self.players:
            return False

        return all(player.vote is not None for player in self.players.values())

    def resolve_turn(self, pack: GamePack) -> TurnResolution:
        if self.status != SessionStatus.IN_GAME:
            raise GameNotRunning("Игра сейчас не запущена.")

        if not self.all_votes_ready():
            raise VoteError("Не все игроки проголосовали.")

        event = self.get_current_event(pack)
        outcome = _rng.choice(event.outcomes)

        deltas: dict[int, ResourceDelta] = {}

        for player in self.players.values():
            if player.vote is None:
                delta = ResourceDelta()
            else:
                delta = outcome.effects.get(player.vote, ResourceDelta())

            player.percent = max(0, player.percent + delta.percent)
            player.influence = max(0, player.influence + delta.influence)
            deltas[player.user_id] = delta

        resolution = TurnResolution(
            event=event,
            outcome=outcome,
            deltas=deltas,
            turn_number=self.turn_number,
        )

        if self.turn_number >= self.total_turns:
            if not self.overtime_used and self._has_percent_tie_for_first():
                self.overtime_used = True
                self.total_turns += 3

                extra_plan = self._build_turn_plan(pack, 3)
                self.turn_plan.extend(extra_plan)

                self.turn_number += 1
                self.current_event_id = self.turn_plan[self.turn_number - 1]

                self._reset_votes()
                self.ensure_auto_votes(pack)

                resolution.overtime_started = True
            else:
                self.status = SessionStatus.FINISHED
                resolution.game_finished = True
        else:
            self.turn_number += 1
            self.current_event_id = self.turn_plan[self.turn_number - 1]

            self._reset_votes()
            self.ensure_auto_votes(pack)

        return resolution

    def _reset_votes(self) -> None:
        for player in self.players.values():
            player.vote = None
            player.vote_changed_at = None

    def _has_percent_tie_for_first(self) -> bool:
        if not self.players:
            return False

        max_percent = max(player.percent for player in self.players.values())
        top_count = sum(1 for player in self.players.values() if player.percent == max_percent)

        return top_count > 1

    @staticmethod
    def _build_turn_plan(pack: GamePack, turns: int) -> list[str]:
        if turns <= 0:
            raise SessionCannotStart("Количество ходов должно быть больше нуля.")

        event_ids = [event.id for event in pack.events]
        if not event_ids:
            raise SessionCannotStart("В паке нет событий.")

        if len(event_ids) >= turns:
            return _rng.sample(event_ids, turns)

        plan: list[str] = []

        while len(plan) < turns:
            shuffled = event_ids.copy()
            _rng.shuffle(shuffled)
            plan.extend(shuffled)

        return plan[:turns]