from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pol_inc.domain.enums import FactionId, SessionStatus
from pol_inc.domain.errors import (
    PackMismatch,
    PartyValidationError,
    PlayerNotFound,
    SessionAlreadyStarted,
    SessionFull,
    UserAlreadyInSession,
)
from pol_inc.domain.packs import GamePack, GamePackMeta


@dataclass(slots=True)
class Party:
    name: str
    slogan: str
    ideology: str

    @classmethod
    def create(cls, name: str, slogan: str, ideology: str) -> "Party":
        name = name.strip()[:30]
        slogan = slogan.strip()[:50]
        ideology = ideology.strip()[:30]

        if not name or not ideology:
            raise PartyValidationError("Название и идеология партии не могут быть пустыми.")

        return cls(name=name, slogan=slogan, ideology=ideology)


@dataclass(slots=True)
class Player:
    user_id: int
    username: str | None
    party: Party | None = None
    vote: FactionId | None = None
    eliminated: bool = False


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

    def add_player(self, user_id: int, username: str | None) -> None:
        if self.status != SessionStatus.NEW:
            raise SessionAlreadyStarted("Сессия уже запущена или закрыта.")

        if user_id in self.players:
            raise UserAlreadyInSession("Игрок уже состоит в этой сессии.")

        if len(self.players) >= self.max_players:
            raise SessionFull("В сессии уже максимальное количество игроков.")

        self.players[user_id] = Player(user_id=user_id, username=username)

    def remove_player(self, user_id: int) -> None:
        self.players.pop(user_id, None)

    def set_pack(self, meta: GamePackMeta, pack: GamePack) -> None:
        if self.status != SessionStatus.NEW:
            raise SessionAlreadyStarted("Нельзя менять пак после старта сессии.")

        if pack.id != meta.id:
            raise PackMismatch("Идентификатор пака в файле не совпадает с индексом.")

        self.pack_meta = meta
        self.pack = pack

        if pack.durations:
            self.duration = pack.durations[0]

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

    def can_start(self) -> bool:
        return (
            self.status == SessionStatus.NEW
            and self.pack is not None
            and len(self.players) >= self.min_players
            and all(player.party is not None for player in self.players.values())
        )