from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResourceDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    percent: int = 0
    influence: int = 0


class AbilityCost(BaseModel):
    model_config = ConfigDict(extra="ignore")

    percent: int = 0
    influence: int = 0


class Ability(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str = ""
    cost: AbilityCost = Field(default_factory=AbilityCost)
    targeted: bool = False
    faction: str | None = None


class FactionInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    color: str = ""
    emoji: str = ""
    feature: str = ""


class Alliance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    factions: list[str]


class EventOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    description: str = ""
    banner: str | None = None
    effects: dict[str, ResourceDelta] = Field(default_factory=dict)


class GameEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    description: str = ""
    banner: str | None = None
    outcomes: list[EventOutcome] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcomes(self) -> "GameEvent":
        if not self.outcomes:
            raise ValueError("Событие должно содержать хотя бы один исход.")
        return self


class GamePack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str = ""
    durations: list[int] = Field(default_factory=lambda: [8, 10, 12])
    alliances: list[Alliance] = Field(default_factory=list)
    factions: list[FactionInfo] = Field(default_factory=list)
    abilities: list[Ability] = Field(default_factory=list)
    events: list[GameEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pack(self) -> "GamePack":
        if not self.durations:
            raise ValueError("Пак должен содержать хотя бы одну длительность.")

        if any(duration <= 0 for duration in self.durations):
            raise ValueError("Длительность игры должна быть положительным числом.")

        if not self.events:
            raise ValueError("Пак должен содержать хотя бы одно событие.")

        return self


class GamePackMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str = ""
    file: str | None = None