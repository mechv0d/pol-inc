from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Названия характеристик, которые могут упоминаться в эффектах.
REGION_STATS = {
    "economy",
    "trust",
    "security",
    "government",
    "al_nazra",
    "infrastructure",
}

GLOBAL_STATS = {
    "trust_global",
    "initiative",
    "budget",
    "corruption",
    "al_nazra_support",
}

# Флаги технологий, которые понимает движок (см. domain/tarbin_game.py).
KNOWN_TECH_FLAGS = {
    "military_power",
    "civic_trust",
    "military_discount",
    "civic_discount",
    "info_discount",
    "income_bonus",
    "intel_slow",
    "statement_bonus",
    "corruption_growth_delta",
    "stable_trust",
    "infra_econ",
}

# Роли штаба, активные при разном числе игроков (раздел 6.3 документа).
ROLE_SETS: dict[int, list[str]] = {
    2: [
        "commander",
        "military_coordinator",
        "civil_admin",
        "finance_director",
    ],
    3: [
        "commander",
        "military_coordinator",
        "civil_admin",
        "finance_director",
        "liaison",
    ],
}

FULL_STAFF = [
    "commander",
    "military_coordinator",
    "civil_admin",
    "liaison",
    "finance_director",
    "intel_chief",
]


def active_roles_for_players(player_count: int) -> list[str]:
    if player_count <= 2:
        return list(ROLE_SETS[2])
    if player_count == 3:
        return list(ROLE_SETS[3])
    return list(FULL_STAFF)


class Effect(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stat: str
    target: str = "global"
    delta: int = 0


class RegionDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    type: str = ""
    population: int = 0
    economy: int = 0
    trust: int = 0
    security: int = 0
    government: int = 0
    al_nazra: int = 0
    infrastructure: int = 0


class RoleDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    short_name: str = ""
    description: str = ""
    passive: str = ""
    available_actions: list[str] = Field(default_factory=list)


class TechDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    branch: str
    tier: int = 1
    name: str
    cost: int = 0
    prerequisites: list[str] = Field(default_factory=list)
    unlocks_actions: list[str] = Field(default_factory=list)
    flags: dict[str, int] = Field(default_factory=dict)


class ActionDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    role_id: str
    name: str
    description: str = ""
    type: str = "operation"
    cost: int = 0
    target: str = "none"
    cooldown: int = 0
    requirements: dict[str, list[str]] = Field(default_factory=dict)
    effects: list[Effect] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    upkeep: dict = Field(default_factory=dict)
    next_income_bonus: int = 0
    next_cost_discount: int = 0


class EventOutcomeDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    weight: int = 100
    banner: str | None = None
    effects: list[Effect] = Field(default_factory=list)


class EventOptionDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    cost: int = 0
    effects: list[Effect] = Field(default_factory=list)
    outcomes: list[EventOutcomeDef] = Field(default_factory=list)


class GameEventDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    description: str = ""
    banner: str | None = None
    target_scope: str = "global"
    default_region_filter: dict[str, int] = Field(default_factory=dict)
    options: list[EventOptionDef] = Field(default_factory=list)


class IntentionDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str = ""


class AlNazraOperationDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    min_support: int = 0
    tags: list[str] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    region_effects: list[Effect] = Field(default_factory=list)
    region_modifier: str = ""


class AlNazraDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intentions: list[IntentionDef] = Field(default_factory=list)
    operations: list[AlNazraOperationDef] = Field(default_factory=list)
    hideout_threshold: int = 40
    hideout_security_max: int = 30


class TarbinSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    min_players: int = 2
    max_players: int = 6
    action_points_per_role: int = 1
    event_turns: list[int] = Field(default_factory=list)
    start_budget: int = 120
    start_initiative: int = 50
    start_trust: int = 0
    start_corruption: int = 0
    start_al_nazra_support: int = 10
    initiative_decay: int = 4
    base_income: int = 10
    timeout_hours: int = 4


class TarbinAssets(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cover: str | None = None


class TarbinGamePack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.0"
    pack_type: str = "TARBIN"
    id: str
    name: str
    description: str = ""
    language: str = "ru"
    durations: list[int] = Field(default_factory=lambda: [8, 10, 12])
    settings: TarbinSettings = Field(default_factory=TarbinSettings)
    roles: list[RoleDef] = Field(default_factory=list)
    regions: list[RegionDef] = Field(default_factory=list)
    tech_tree: list[TechDef] = Field(default_factory=list)
    actions: list[ActionDef] = Field(default_factory=list)
    events: list[GameEventDef] = Field(default_factory=list)
    al_nazra: AlNazraDef = Field(default_factory=AlNazraDef)
    assets: TarbinAssets = Field(default_factory=TarbinAssets)

    @model_validator(mode="after")
    def validate_pack(self) -> TarbinGamePack:
        errors: list[str] = []

        if not self.durations or any(duration <= 0 for duration in self.durations):
            errors.append("durations должен содержать положительные числа.")

        if not self.roles:
            errors.append("Пак должен содержать роли.")
        if not self.regions:
            errors.append("Пак должен содержать регионы.")
        if not self.actions:
            errors.append("Пак должен содержать действия.")
        if not self.events:
            errors.append("Пак должен содержать события.")

        role_ids = {role.id for role in self.roles}
        tech_ids = {tech.id for tech in self.tech_tree}
        action_ids = {action.id for action in self.actions}

        for action in self.actions:
            if action.role_id not in role_ids:
                errors.append(
                    f"Действие {action.id}: неизвестная роль {action.role_id}."
                )
            if action.cost < 0:
                errors.append(f"Действие {action.id}: отрицательная стоимость.")
            if action.target not in {"region", "global", "none"}:
                errors.append(f"Действие {action.id}: неверный target {action.target}.")
            for tech_id in action.requirements.get("techs", []):
                if tech_id not in tech_ids:
                    errors.append(
                        f"Действие {action.id}: неизвестная технология {tech_id}."
                    )
            errors.extend(check_effects(action.effects, f"действие {action.id}"))

        for role in self.roles:
            for action_id in role.available_actions:
                if action_id not in action_ids:
                    errors.append(f"Роль {role.id}: неизвестное действие {action_id}.")

        for tech in self.tech_tree:
            if tech.cost < 0:
                errors.append(f"Технология {tech.id}: отрицательная стоимость.")
            for prerequisite in tech.prerequisites:
                if prerequisite not in tech_ids:
                    errors.append(
                        f"Технология {tech.id}: неизвестный prerequisite {prerequisite}."
                    )
            for action_id in tech.unlocks_actions:
                if action_id not in action_ids:
                    errors.append(
                        f"Технология {tech.id}: неизвестное действие {action_id}."
                    )
            unknown_flags = set(tech.flags) - KNOWN_TECH_FLAGS
            if unknown_flags:
                errors.append(
                    f"Технология {tech.id}: неизвестные флаги "
                    + ", ".join(sorted(unknown_flags))
                    + "."
                )

        for event in self.events:
            if not isinstance(event, GameEventDef):
                errors.append("Событие имеет неверный формат.")
                continue
            if not event.options:
                errors.append(f"Событие {event.id}: нет вариантов решения.")
            if event.target_scope not in {"region", "global"}:
                errors.append(f"Событие {event.id}: неверный target_scope.")
            for option in event.options:
                if option.cost < 0:
                    errors.append(
                        f"Событие {event.id}, вариант {option.id}: "
                        "отрицательная стоимость."
                    )
                errors.extend(
                    check_effects(
                        option.effects, f"событие {event.id}, вариант {option.id}"
                    )
                )
                total_weight = 0
                for outcome in option.outcomes:
                    if outcome.weight <= 0:
                        errors.append(
                            f"Событие {event.id}, исход {outcome.id}: "
                            "вес должен быть положительным."
                        )
                    total_weight += outcome.weight
                    errors.extend(
                        check_effects(
                            outcome.effects,
                            f"событие {event.id}, исход {outcome.id}",
                        )
                    )
                if option.outcomes and total_weight <= 0:
                    errors.append(
                        f"Событие {event.id}, вариант {option.id}: "
                        "суммарный вес исходов должен быть положительным."
                    )

        if errors:
            raise ValueError("Ошибки пака:\n" + "\n".join(f"- {err}" for err in errors))

        return self

    # ----- helpers -----

    def role_by_id(self, role_id: str) -> RoleDef | None:
        for role in self.roles:
            if role.id == role_id:
                return role
        return None

    def action_by_id(self, action_id: str) -> ActionDef | None:
        for action in self.actions:
            if action.id == action_id:
                return action
        return None

    def tech_by_id(self, tech_id: str) -> TechDef | None:
        for tech in self.tech_tree:
            if tech.id == tech_id:
                return tech
        return None

    def region_by_id(self, region_id: str) -> RegionDef | None:
        for region in self.regions:
            if region.id == region_id:
                return region
        return None

    def actions_for_role(self, role_id: str) -> list[ActionDef]:
        role = self.role_by_id(role_id)
        if role is None:
            return []

        known = {action.id: action for action in self.actions}
        return [
            known[action_id]
            for action_id in role.available_actions
            if action_id in known
        ]

    def techs_for_branch(self, branch: str) -> list[TechDef]:
        return sorted(
            [tech for tech in self.tech_tree if tech.branch == branch],
            key=lambda tech: tech.tier,
        )

    def event_turns_for_duration(self, duration: int) -> list[int]:
        configured = self.settings.event_turns
        if configured:
            return [turn for turn in configured if turn <= duration]
        return [turn for turn in range(2, duration + 1, 2)]


def check_effects(effects: list[Effect], where: str) -> list[str]:
    errors: list[str] = []

    for effect in effects:
        if effect.target == "region":
            if effect.stat not in REGION_STATS:
                errors.append(f"{where}: неверный региональный стат {effect.stat}.")
        elif effect.target == "global":
            if effect.stat not in GLOBAL_STATS:
                errors.append(f"{where}: неверный глобальный стат {effect.stat}.")
        else:
            errors.append(f"{where}: неверный target {effect.target}.")

    return errors
