from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from pol_inc.domain.tarbin_pack import (
    GLOBAL_STATS,
    REGION_STATS,
    Effect,
    EventOptionDef,
    GameEventDef,
    TarbinGamePack,
)

# Направления приоритета командующего -> роли, которых касается бонус.
PRIORITY_ROLES = {
    "security": {"military_coordinator", "intel_chief"},
    "civil": {"civil_admin"},
    "info": {"liaison"},
    "economy": {"finance_director"},
    "intel": {"intel_chief"},
}

PRIORITY_DIRECTIONS = ["security", "civil", "info", "economy", "intel"]

# Порядок применения действий по ролям (раздел 15, фаза 5).
ROLE_ORDER = [
    "commander",
    "military_coordinator",
    "civil_admin",
    "liaison",
    "finance_director",
    "intel_chief",
]

STATUS_RANK = {"occupied": 0, "contested": 1, "unstable": 2, "stable": 3}

# Категории ролей для отображения: военные, гражданские, экономические, штаб.
ROLE_CATEGORY = {
    "commander": "🏛",
    "military_coordinator": "🔴",
    "intel_chief": "🔴",
    "civil_admin": "🟢",
    "liaison": "🟢",
    "finance_director": "🔵",
}

BRANCH_CATEGORY = {
    "security": "🔴",
    "intel": "🔴",
    "civil": "🟢",
    "civil_admin": "🟢",
    "info": "🟢",
    "economy": "🔵",
}

STAT_LABELS = {
    "trust": "доверие",
    "trust_global": "доверие",
    "initiative": "инициатива",
    "economy": "экономика",
    "security": "безопасность",
    "government": "управление",
    "al_nazra": "боевики",
    "al_nazra_support": "боевики",
    "corruption": "коррупция",
    "budget": "бюджет",
    "infrastructure": "инфраструктура",
}


def role_category(role_id: str) -> str:
    return ROLE_CATEGORY.get(role_id, "⚪")


def magnitude_label(delta: int) -> str:
    magnitude = abs(delta)
    if magnitude >= 6:
        marks = "+++"
    elif magnitude >= 3:
        marks = "++"
    else:
        marks = "+"
    return marks if delta > 0 else marks.replace("+", "-")


def action_summary(action) -> str:
    parts: list[str] = []

    for effect in action.effects:
        if effect.delta == 0:
            continue
        label = STAT_LABELS.get(effect.stat, effect.stat)
        parts.append(f"{magnitude_label(effect.delta)}{label}")

    return ", ".join(parts)


@dataclass(slots=True)
class RegionState:
    region_id: str
    name: str
    population: int = 0
    economy: int = 0
    trust: int = 0
    security: int = 0
    government: int = 0
    al_nazra: int = 0
    infrastructure: int = 0
    guard_until_turn: int = 0
    modifiers: list[dict] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.al_nazra >= 70 and self.government < 30:
            return "occupied"
        if self.al_nazra >= 45 or self.security < 25:
            return "contested"
        if self.security >= 60 and self.al_nazra <= 20:
            return "stable"
        return "unstable"


@dataclass(slots=True)
class Hideout:
    region_id: str
    revealed: bool = False


@dataclass(slots=True)
class UpkeepItem:
    name: str
    cost: int
    owner_role: str = ""


@dataclass(slots=True)
class Submission:
    role_id: str
    kind: str  # "action" | "research" | "pass"
    action_id: str = ""
    tech_id: str = ""
    region_id: str = ""
    cost_paid: int = 0


@dataclass(slots=True)
class TurnReport:
    turn: int = 0
    event_title: str = ""
    event_region: str = ""
    chosen_option: str = ""
    outcome_id: str = ""
    actions: list[str] = field(default_factory=list)
    action_cards: list[dict] = field(default_factory=list)
    spending: list[str] = field(default_factory=list)
    research_done: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    global_deltas: dict[str, int] = field(default_factory=dict)
    region_notes: list[str] = field(default_factory=list)
    synergies: list[str] = field(default_factory=list)
    al_nazra_operation: str = ""
    al_nazra_notes: list[str] = field(default_factory=list)
    income: int = 0
    upkeep_paid: int = 0
    income_parts: dict[str, int] = field(default_factory=dict)
    result: str = ""
    result_reason: str = ""


@dataclass(slots=True)
class GameState:
    turn: int = 1
    total_turns: int = 8
    event_turns: list[int] = field(default_factory=list)
    event_index: int = 0
    budget: int = 120
    initiative: int = 50
    corruption: int = 0
    regions: dict[str, RegionState] = field(default_factory=dict)
    researched: list[str] = field(default_factory=list)
    cooldowns: dict[str, int] = field(default_factory=dict)
    upkeep: list[UpkeepItem] = field(default_factory=list)
    pending_income: int = 0
    pending_income_bonus: int = 0
    cost_discount: int = 0
    pending_cost_discount: int = 0
    deficit_mult: float = 1.0
    info_streak: int = 0
    priority: str | None = None
    mobilization_used: bool = False
    mobilization_active: bool = False
    intentions: list[str] = field(default_factory=list)
    revealed_intentions: list[str] = field(default_factory=list)
    revealed_regions: list[str] = field(default_factory=list)
    recon_bonus: dict[str, int] = field(default_factory=dict)
    hideouts: list[Hideout] = field(default_factory=list)
    submissions: dict[str, list[Submission]] = field(default_factory=dict)
    active_roles: list[str] = field(default_factory=list)
    event_votes: dict[int, str] = field(default_factory=dict)
    event_id: str = ""
    event_region_id: str = ""
    vacant_roles: list[str] = field(default_factory=list)

    @property
    def trust(self) -> int:
        return round_half_up(mean_stat(self, "trust"))

    @property
    def al_support(self) -> int:
        return round_half_up(mean_stat(self, "al_nazra"))


def round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def mean_stat(state: GameState, stat: str) -> float:
    regions = list(state.regions.values())
    if not regions:
        return 0.0
    return sum(getattr(region, stat) for region in regions) / len(regions)


def spread_stat(state: GameState, stat: str, delta: int) -> int:
    """Распределяет delta по регионам (крупный остаток первым).

    Рост идёт сначала в самые низкие, падение — из самых высоких.
    Возвращает реально применённый итог.
    """
    regions = list(state.regions.values())
    if not regions or delta == 0:
        return 0

    sign = 1 if delta > 0 else -1
    ordered = sorted(
        regions, key=lambda region: getattr(region, stat), reverse=(delta < 0)
    )
    base, remainder = divmod(abs(delta), len(ordered))
    applied = 0

    for index, region in enumerate(ordered):
        share = sign * (base + (1 if index < remainder else 0))
        if share == 0:
            continue
        before = getattr(region, stat)
        setattr(region, stat, _clamp(before + share))
        applied += getattr(region, stat) - before

    return applied


def nudge_mean(state: GameState, stat: str, target: float) -> int:
    """Подтягивает среднее значение стата к цели. Возвращает применённый итог."""
    applied = 0

    for _ in range(10000):
        mean = mean_stat(state, stat)
        if abs(mean - target) < 1e-9:
            break

        if mean < target:
            candidates = [
                region
                for region in state.regions.values()
                if getattr(region, stat) < 100
            ]
            if not candidates:
                break
            region = min(candidates, key=lambda item: getattr(item, stat))
            step = 1
        else:
            candidates = [
                region for region in state.regions.values() if getattr(region, stat) > 0
            ]
            if not candidates:
                break
            region = max(candidates, key=lambda item: getattr(item, stat))
            step = -1

        before = getattr(region, stat)
        setattr(region, stat, _clamp(before + step))
        applied += getattr(region, stat) - before

    return applied


def new_game_state(
    pack: TarbinGamePack, duration: int, rng: random.Random
) -> GameState:
    settings = pack.settings
    state = GameState(
        turn=1,
        total_turns=duration,
        event_turns=pack.event_turns_for_duration(duration),
        budget=settings.start_budget,
        initiative=settings.start_initiative,
        corruption=settings.start_corruption,
    )

    for region_def in pack.regions:
        state.regions[region_def.id] = RegionState(
            region_id=region_def.id,
            name=region_def.name,
            population=region_def.population,
            economy=_clamp(region_def.economy),
            trust=_clamp(region_def.trust),
            security=_clamp(region_def.security),
            government=_clamp(region_def.government),
            al_nazra=_clamp(region_def.al_nazra),
            infrastructure=_clamp(region_def.infrastructure),
        )

    intention_ids = [intention.id for intention in pack.al_nazra.intentions]
    rng.shuffle(intention_ids)
    state.intentions = intention_ids[:2]

    return state


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def tech_flags(pack: TarbinGamePack, state: GameState) -> dict[str, int]:
    total: dict[str, int] = {}

    for tech_id in state.researched:
        tech = pack.tech_by_id(tech_id)
        if tech is None:
            continue

        for key, value in tech.flags.items():
            total[key] = total.get(key, 0) + value

    return total


def effective_cost(
    pack: TarbinGamePack,
    state: GameState,
    role_id: str,
    base_cost: int,
    role_discount: bool = True,
) -> int:
    flags = tech_flags(pack, state)
    discount = state.cost_discount

    if role_discount:
        if role_id == "military_coordinator":
            discount += flags.get("military_discount", 0)
        elif role_id == "civil_admin":
            discount += flags.get("civic_discount", 0)
        elif role_id == "liaison":
            discount += flags.get("info_discount", 0)

    mult = (1 + state.corruption / 200) * state.deficit_mult
    cost = math.ceil(base_cost * mult) - discount
    return max(0, cost)


def slots_for_role(pack: TarbinGamePack, state: GameState) -> int:
    slots = pack.settings.action_points_per_role
    if state.mobilization_active:
        slots += 1
    return slots


def validate_action_submit(
    pack: TarbinGamePack,
    state: GameState,
    role_id: str,
    action_id: str,
    region_id: str = "",
) -> tuple[int, str]:
    """Проверяет действие. Возвращает (стоимость, ошибка). Пустая ошибка = ок."""
    action = pack.action_by_id(action_id)
    if action is None:
        return 0, "Действие не найдено."
    if action.role_id != role_id:
        return 0, "Действие не принадлежит этой роли."

    used = len(state.submissions.get(role_id, []))
    if used >= slots_for_role(pack, state):
        return 0, "У роли больше нет действий в этом ходу."

    for submitted in state.submissions.get(role_id, []):
        if submitted.kind == "action" and submitted.action_id == action_id:
            available = state.cooldowns.get(action_id, 0)
            if state.turn < available:
                return 0, "Действие на перезарядке."

    for tech_id in action.requirements.get("techs", []):
        if tech_id not in state.researched:
            tech = pack.tech_by_id(tech_id)
            name = tech.name if tech else tech_id
            return 0, f"Требуется технология: {name}."

    if action.target == "region" and region_id not in state.regions:
        return 0, "Укажите корректный регион."

    if "mobilize" in action.tags and state.mobilization_used:
        return 0, "Мобилизация уже использовалась."

    cost = effective_cost(pack, state, role_id, action.cost)
    if state.budget < cost:
        return 0, f"Не хватает бюджета: нужно {cost} млн."

    return cost, ""


def validate_research_submit(
    pack: TarbinGamePack,
    state: GameState,
    role_id: str,
    tech_id: str,
) -> tuple[int, str]:
    tech = pack.tech_by_id(tech_id)
    if tech is None:
        return 0, "Технология не найдена."
    if tech_id in state.researched:
        return 0, "Технология уже исследована."

    for submissions in state.submissions.values():
        for submitted in submissions:
            if submitted.kind == "research" and submitted.tech_id == tech_id:
                return 0, "Технология уже исследуется в этом ходу."

    for prerequisite in tech.prerequisites:
        if prerequisite not in state.researched:
            required = pack.tech_by_id(prerequisite)
            name = required.name if required else prerequisite
            return 0, f"Сначала исследуйте: {name}."

    if tech.tier > 1:
        previous = [
            item
            for item in pack.techs_for_branch(tech.branch)
            if item.tier == tech.tier - 1
        ]
        if previous and previous[0].id not in state.researched:
            return 0, f"Сначала исследуйте: {previous[0].name}."

    used = len(state.submissions.get(role_id, []))
    if used >= slots_for_role(pack, state):
        return 0, "У роли больше нет действий в этом ходу."

    cost = effective_cost(pack, state, role_id, tech.cost, role_discount=False)
    if state.budget < cost:
        return 0, f"Не хватает бюджета: нужно {cost} млн."

    return cost, ""


def apply_effect(
    state: GameState,
    region: RegionState | None,
    effect: Effect,
    report: TurnReport,
) -> None:
    if effect.target == "region":
        if region is None:
            return

        if effect.stat not in REGION_STATS:
            return

        before = getattr(region, effect.stat)
        setattr(region, effect.stat, _clamp(before + effect.delta))
        return

    if effect.stat not in GLOBAL_STATS:
        return

    if effect.stat in {"trust_global", "al_nazra_support"}:
        region_stat = "trust" if effect.stat == "trust_global" else "al_nazra"
        applied = spread_stat(state, region_stat, effect.delta)
        report.global_deltas[effect.stat] = (
            report.global_deltas.get(effect.stat, 0) + applied
        )
        return

    if effect.stat == "initiative":
        state.initiative = _clamp(state.initiative + effect.delta)
    elif effect.stat == "budget":
        if effect.delta >= 0:
            state.pending_income += effect.delta
        else:
            state.budget += effect.delta
    elif effect.stat == "corruption":
        state.corruption = _clamp(state.corruption + effect.delta)

    report.global_deltas[effect.stat] = (
        report.global_deltas.get(effect.stat, 0) + effect.delta
    )


def main_positive_index(effects: list[Effect]) -> int:
    best = -1
    best_value = 0

    for index, effect in enumerate(effects):
        if effect.delta > best_value:
            best_value = effect.delta
            best = index

    return best


def pick_event_for_turn(
    pack: TarbinGamePack, state: GameState, rng: random.Random
) -> tuple[object | None, str]:
    if state.turn not in state.event_turns:
        return None, ""

    if state.event_index >= len(pack.events):
        return None, ""

    event = pack.events[state.event_index]
    state.event_index += 1

    region_id = ""
    if event.target_scope == "region":
        candidates = [
            region
            for region in state.regions.values()
            if region_matches(region, event.default_region_filter)
        ]
        if not candidates:
            candidates = list(state.regions.values())
        if candidates:
            region_id = rng.choice(candidates).region_id

    state.event_id = event.id
    state.event_region_id = region_id
    state.event_votes = {}
    return event, region_id


def region_matches(region: RegionState, filt: dict[str, int]) -> bool:
    for key, value in filt.items():
        if key.endswith("_min"):
            stat = key[: -len("_min")]
            if getattr(region, stat, 0) < value:
                return False
        elif key.endswith("_max"):
            stat = key[: -len("_max")]
            if getattr(region, stat, 0) > value:
                return False
    return True


def resolve_event_votes(
    pack: TarbinGamePack,
    event: GameEventDef,
    votes: dict[int, str],
    commander_user_id: int | None,
) -> tuple[EventOptionDef, bool]:
    """Возвращает (выбранный вариант, это провал)."""
    options = {option.id: option for option in event.options}

    if not votes:
        return with_fallback(event), True

    counts: dict[str, int] = {}
    for option_id in votes.values():
        if option_id in options:
            counts[option_id] = counts.get(option_id, 0) + 1

    if not counts:
        return with_fallback(event), True

    best = max(counts.values())
    leaders = [option_id for option_id, count in counts.items() if count == best]

    if len(leaders) == 1:
        chosen = options[leaders[0]]
    elif commander_user_id is not None and votes.get(commander_user_id) in leaders:
        chosen = options[votes[commander_user_id]]
    else:
        ranked = sorted(
            (options[option_id] for option_id in leaders),
            key=lambda opt: (risk_of_option(opt), event.options.index(opt)),
        )
        chosen = ranked[0]

    return chosen, is_do_nothing(chosen)


def find_do_nothing(event: GameEventDef) -> EventOptionDef | None:
    for option in event.options:
        if is_do_nothing(option):
            return option
    return None


def with_fallback(event: GameEventDef) -> EventOptionDef:
    fallback = find_do_nothing(event)
    if fallback is None:
        return least_risk_option(event)
    return fallback


def is_do_nothing(option: EventOptionDef) -> bool:
    if option.id.strip().upper() == "D":
        return True
    return "ничего не делать" in option.title.strip().lower()


def risk_of_option(option: EventOptionDef) -> int:
    return sum(-effect.delta for effect in option.effects if effect.delta < 0)


def least_risk_option(event: GameEventDef) -> EventOptionDef:
    return min(
        event.options, key=lambda opt: (risk_of_option(opt), event.options.index(opt))
    )


def resolve_turn(
    pack: TarbinGamePack,
    state: GameState,
    role_owners: dict[str, int],
    rng: random.Random,
    player_names: dict[int, str] | None = None,
) -> TurnReport:
    report = TurnReport(turn=state.turn)
    support_start = mean_stat(state, "al_nazra")
    names = player_names or {}

    commander_user_id = role_owners.get("commander")

    # Фаза 4: завершение исследований.
    for role_id in ROLE_ORDER:
        for submitted in state.submissions.get(role_id, []):
            if submitted.kind != "research":
                continue
            if submitted.tech_id in state.researched:
                continue
            state.researched.append(submitted.tech_id)
            tech = pack.tech_by_id(submitted.tech_id)
            name = tech.name if tech else submitted.tech_id
            report.research_done.append(f"{role_name(pack, role_id)}: {name}")
            if submitted.cost_paid:
                report.spending.append(
                    f"Исследование {name} — {submitted.cost_paid} млн"
                )
            report.action_cards.append(
                {
                    "player": names.get(role_owners.get(role_id, -1), ""),
                    "role": role_name(pack, role_id),
                    "action": f"Исследование: {name}",
                    "region": "",
                    "cost": submitted.cost_paid,
                    "desc": tech.description[:140] if tech and tech.description else "",
                }
            )

    # Фаза 5: действия игроков.
    info_used = False
    civil_used_roles: set[str] = set()
    emergency_used = False
    military_actions: list[tuple] = []

    ordered_submissions: list[tuple[str, Submission]] = []
    for role_id in ROLE_ORDER:
        for submitted in state.submissions.get(role_id, []):
            if submitted.kind == "action":
                ordered_submissions.append((role_id, submitted))

    for role_id, submitted in ordered_submissions:
        action = pack.action_by_id(submitted.action_id)
        if action is None:
            report.invalid.append(f"Неизвестное действие {submitted.action_id}.")
            continue

        if state.budget < submitted.cost_paid:
            report.invalid.append(
                f"{action.name}: бюджет изменился, действие отменено."
            )
            continue

        state.budget -= submitted.cost_paid
        region = state.regions.get(submitted.region_id) if submitted.region_id else None

        effects = [
            Effect(stat=item.stat, target=item.target, delta=item.delta)
            for item in action.effects
        ]

        # Бонус приоритета командующего: +1 к главному положительному эффекту.
        if state.priority and role_id in PRIORITY_ROLES.get(state.priority, set()):
            best = main_positive_index(effects)
            if best >= 0:
                effects[best].delta += 1

        # Синергии/конфликты, зависящие от набора действий.
        if "military" in action.tags:
            military_actions.append((role_id, submitted, action, region, effects))
            continue

        apply_action_effects(pack, state, report, role_id, action, region, effects)

        if "info" in action.tags:
            info_used = True
        if role_id == "civil_admin":
            civil_used_roles.add(role_id)
        if "emergency" in action.tags:
            emergency_used = True

        if submitted.cost_paid:
            report.spending.append(f"{action.name} — {submitted.cost_paid} млн")
        report.action_cards.append(
            _action_card(pack, role_owners, names, role_id, action, region, submitted)
        )

    has_info_turn = info_used

    for role_id, submitted, action, region, effects in military_actions:
        notes: list[str] = []

        if region is not None and submitted.region_id:
            for other_role, other_sub in ordered_submissions:
                other_action = pack.action_by_id(other_sub.action_id)
                if (
                    other_action is not None
                    and "recon" in other_action.tags
                    and other_sub.region_id == submitted.region_id
                ):
                    effects = boost_effects(effects, ["security", "al_nazra"], 2)
                    effects = soften_trust_penalty(effects, 1)
                    notes.append("разведка усилила удар +2 и смягчила штраф доверия")

        if has_info_turn:
            effects = soften_trust_penalty(effects, 1)
            notes.append("инфокампания смягчила штраф доверия")

        if region is not None:
            for other_role, other_sub in ordered_submissions:
                if (
                    other_role == "civil_admin"
                    and other_sub.region_id == submitted.region_id
                ):
                    effects = boost_trust(effects, 1)
                    effects = soften_trust_penalty(effects, 1)
                    notes.append("совместная операция с гражданскими: +1 доверие")

        if state.trust < 20:
            effects = add_trust_penalty(effects, 1)
            notes.append("низкое доверие: дополнительный штраф -1")

        apply_action_effects(pack, state, report, role_id, action, region, effects)

        if submitted.cost_paid:
            report.spending.append(f"{action.name} — {submitted.cost_paid} млн")
        report.action_cards.append(
            _action_card(pack, role_owners, names, role_id, action, region, submitted)
        )

        region_name = region.name if region else "штаб"
        line = f"{role_name(pack, role_id)}: {action.name} → {region_name}"
        if notes:
            line += " (" + "; ".join(notes) + ")"
        report.actions.append(line)

    if emergency_used and civil_used_roles:
        state.corruption = _clamp(state.corruption + 1)
        report.global_deltas["corruption"] = (
            report.global_deltas.get("corruption", 0) + 1
        )
        report.synergies.append(
            "Чрезвычайное финансирование + гражданские проекты: коррупция +1."
        )

    # Усталость от пропаганды.
    if info_used:
        if state.info_streak >= 1:
            report.synergies.append(
                "Население устало от пропаганды: эффект кампаний снижен."
            )
        state.info_streak += 1
    else:
        state.info_streak = 0

    # Фаза 6: событие.
    event = pack_event_by_id(pack, state.event_id)
    if event is not None:
        report.event_title = event.title
        if state.event_region_id:
            region = state.regions.get(state.event_region_id)
            report.event_region = region.name if region else ""

        chosen, failed = resolve_event_votes(
            pack, event, state.event_votes, commander_user_id
        )
        report.chosen_option = chosen.title
        state.budget -= chosen.cost
        if chosen.cost:
            report.spending.append(f"Событие: {chosen.title} — {chosen.cost} млн")

        for effect in chosen.effects:
            apply_effect(
                state, state.regions.get(state.event_region_id), effect, report
            )

        if chosen.outcomes:
            weights = [outcome.weight for outcome in chosen.outcomes]
            outcome = rng.choices(chosen.outcomes, weights=weights, k=1)[0]
            report.outcome_id = outcome.id
            for effect in outcome.effects:
                apply_effect(
                    state, state.regions.get(state.event_region_id), effect, report
                )

        if failed:
            state.initiative = _clamp(state.initiative - 2)
            report.global_deltas["initiative"] = (
                report.global_deltas.get("initiative", 0) - 2
            )
    else:
        applied = spread_stat(state, "al_nazra", 1)
        report.global_deltas["al_nazra_support"] = (
            report.global_deltas.get("al_nazra_support", 0) + applied
        )

    # Фаза 7: ход Al Nazra.
    run_al_nazra(pack, state, report, rng)

    # Фаза 8: пассивные эффекты регионов.
    run_region_passives(pack, state, report)

    # Фаза 9: глобальные пассивные эффекты.
    run_global_passives(pack, state, report, support_start)

    # Фаза 10: победа/поражение.
    check_endings(pack, state, report)

    # Сброс на следующий ход.
    state.submissions = {}
    state.event_votes = {}
    state.event_id = ""
    state.event_region_id = ""
    state.priority = None
    state.mobilization_active = False
    state.cost_discount = state.pending_cost_discount
    state.pending_cost_discount = 0

    return report


def role_name(pack: TarbinGamePack, role_id: str) -> str:
    role = pack.role_by_id(role_id)
    return role.short_name or role.name if role else role_id


def _action_card(
    pack: TarbinGamePack,
    role_owners: dict[str, int],
    player_names: dict[int, str],
    role_id: str,
    action,
    region,
    submitted: Submission,
) -> dict:
    desc = (action.description or "").strip()
    if len(desc) > 140:
        desc = desc[:137] + "..."
    if not desc:
        desc = action_summary(action)
    return {
        "player": player_names.get(role_owners.get(role_id, -1), ""),
        "role": role_name(pack, role_id),
        "action": action.name,
        "region": region.name if region else "",
        "cost": submitted.cost_paid,
        "desc": desc,
    }


def pack_event_by_id(pack: TarbinGamePack, event_id: str) -> GameEventDef | None:
    if not event_id:
        return None
    for event in pack.events:
        if event.id == event_id:
            return event
    return None


def apply_action_effects(pack, state, report, role_id, action, region, effects) -> None:
    flags = tech_flags(pack, state)

    if role_id == "military_coordinator" and flags.get("military_power"):
        effects = boost_effects(
            effects, ["security", "al_nazra"], flags["military_power"]
        )
    if role_id == "civil_admin" and flags.get("civic_trust"):
        effects = boost_trust_effects(effects, flags["civic_trust"])
    if "infra_project" in action.tags and flags.get("infra_econ"):
        effects = boost_effects(effects, ["economy"], flags["infra_econ"])
    if "statement" in action.tags and flags.get("statement_bonus"):
        state.initiative = _clamp(state.initiative + flags["statement_bonus"])
        report.global_deltas["initiative"] = (
            report.global_deltas.get("initiative", 0) + flags["statement_bonus"]
        )

    for effect in effects:
        apply_effect(state, region, effect, report)

    handle_action_tags(pack, state, report, role_id, action, region)

    if action.cooldown > 0:
        state.cooldowns[action.id] = state.turn + action.cooldown + 1

    if action.upkeep:
        state.upkeep.append(
            UpkeepItem(
                name=action.upkeep.get("name", action.name),
                cost=int(action.upkeep.get("cost", 1)),
                owner_role=role_id,
            )
        )

    if action.next_income_bonus:
        state.pending_income_bonus += action.next_income_bonus

    if action.next_cost_discount:
        state.pending_cost_discount += action.next_cost_discount

    if "mobilize" in action.tags:
        state.mobilization_used = True
        state.mobilization_active = True

    region_name = region.name if region else "штаб"
    if not any(
        line.startswith(f"{role_name(pack, role_id)}: {action.name}")
        for line in report.actions
    ):
        report.actions.append(
            f"{role_name(pack, role_id)}: {action.name} → {region_name}"
        )


def handle_action_tags(pack, state, report, role_id, action, region) -> None:
    tags = action.tags

    if "recon" in tags and region is not None:
        if region.region_id not in state.revealed_regions:
            state.revealed_regions.append(region.region_id)
        state.recon_bonus[region.region_id] = 2
        report.region_notes.append(f"Разведан регион {region.name}.")

    if "intel_reveal" in tags:
        hidden = [
            item for item in state.intentions if item not in state.revealed_intentions
        ]
        if hidden:
            state.revealed_intentions.append(hidden[0])
            intention = pack_intention(pack, hidden[0])
            report.region_notes.append(f"Разведка раскрыла намерение: {intention}.")

    if "hideout_buster" in tags and region is not None:
        before = len(state.hideouts)
        state.hideouts = [
            hideout
            for hideout in state.hideouts
            if hideout.region_id != region.region_id
        ]
        if len(state.hideouts) < before:
            report.region_notes.append(f"Логово в регионе {region.name} уничтожено.")

    if "guard" in tags and region is not None:
        region.guard_until_turn = state.turn + 1
        report.region_notes.append(f"Регион {region.name} под защитой.")

    if "debunk" in tags and region is not None:
        before = len(region.modifiers)
        region.modifiers = [
            modifier for modifier in region.modifiers if modifier.get("id") != "rumor"
        ]
        if len(region.modifiers) < before:
            report.region_notes.append(f"Слухи в регионе {region.name} развенчаны.")

    if "reveal_hideout" in tags and region is not None:
        for hideout in state.hideouts:
            if hideout.region_id == region.region_id and not hideout.revealed:
                hideout.revealed = True
                report.region_notes.append(
                    f"Подтверждено логово в регионе {region.name}."
                )


def pack_intention(pack: TarbinGamePack, intention_id: str) -> str:
    for intention in pack.al_nazra.intentions:
        if intention.id == intention_id:
            return intention.name
    return intention_id


def boost_trust_effects(effects: list[Effect], amount: int) -> list[Effect]:
    for effect in effects:
        if effect.stat in {"trust", "trust_global"} and effect.delta > 0:
            effect.delta += amount
    return effects


def boost_effects(effects: list[Effect], stats: list[str], bonus: int) -> list[Effect]:
    best = -1
    best_value = 0

    for index, effect in enumerate(effects):
        if effect.stat in stats and abs(effect.delta) > best_value:
            best_value = abs(effect.delta)
            best = index

    if best >= 0:
        effects[best].delta += bonus if effects[best].delta >= 0 else -bonus

    return effects


def soften_trust_penalty(effects: list[Effect], amount: int) -> list[Effect]:
    for effect in effects:
        if effect.stat == "trust_global" and effect.delta < 0:
            effect.delta = min(0, effect.delta + amount)
    return effects


def add_trust_penalty(effects: list[Effect], amount: int) -> list[Effect]:
    for effect in effects:
        if effect.stat == "trust_global" and effect.delta < 0:
            effect.delta -= amount
            return effects

    effects.append(Effect(stat="trust_global", target="global", delta=-amount))
    return effects


def boost_trust(effects: list[Effect], amount: int) -> list[Effect]:
    for effect in effects:
        if effect.stat in {"trust", "trust_global"} and effect.delta > 0:
            effect.delta += amount
            return effects
    return effects


def run_al_nazra(pack, state, report, rng) -> None:
    eligible = [
        operation
        for operation in pack.al_nazra.operations
        if state.al_support >= operation.min_support
    ]

    if not eligible:
        applied = spread_stat(state, "al_nazra", 1)
        report.global_deltas["al_nazra_support"] = (
            report.global_deltas.get("al_nazra_support", 0) + applied
        )
        report.al_nazra_operation = "Затишье"
        return

    operation = rng.choice(eligible)
    report.al_nazra_operation = operation.name

    for effect in operation.effects:
        apply_effect(state, None, effect, report)

    if operation.region_effects or operation.region_modifier:
        candidates = [
            region
            for region in state.regions.values()
            if region.guard_until_turn < state.turn
        ]
        if not candidates:
            report.al_nazra_notes.append("Атака отражена защитой регионов.")
        else:
            region = rng.choice(candidates)
            for effect in operation.region_effects:
                apply_effect(state, region, effect, report)
            if operation.region_modifier:
                region.modifiers.append(
                    {
                        "id": operation.region_modifier,
                        "turns_left": 2,
                        "trust_per_turn": -1,
                    }
                )
            report.al_nazra_notes.append(f"Удар по региону {region.name}.")

    # Появление логовов.
    for region in state.regions.values():
        if any(hideout.region_id == region.region_id for hideout in state.hideouts):
            continue
        if (
            region.al_nazra >= pack.al_nazra.hideout_threshold
            and region.security <= pack.al_nazra.hideout_security_max
            and rng.random() < 0.5
        ):
            state.hideouts.append(Hideout(region_id=region.region_id))
            report.al_nazra_notes.append(
                f"Разведка докладывает о подозрительной активности: {region.name}."
            )


def run_region_passives(pack, state, report) -> None:
    flags = tech_flags(pack, state)

    for region in state.regions.values():
        status = region.status

        if status == "stable":
            region.economy = _clamp(region.economy + 1)
            region.government = _clamp(region.government + 1)
            if flags.get("stable_trust"):
                region.trust = _clamp(region.trust + flags["stable_trust"])

        if region.al_nazra > region.security:
            region.al_nazra = _clamp(region.al_nazra + 1)
            region.government = _clamp(region.government - 1)
            region.trust = _clamp(region.trust - 1)
        elif region.al_nazra < region.security:
            region.al_nazra = _clamp(region.al_nazra - 1)

        if region.trust > 60:
            region.security = _clamp(region.security + 1)

        if state.corruption > 50:
            region.government = _clamp(region.government - 1)

        if any(hideout.region_id == region.region_id for hideout in state.hideouts):
            region.al_nazra = _clamp(region.al_nazra + 2)

        expired: list[dict] = []
        for modifier in region.modifiers:
            per_turn = modifier.get("trust_per_turn", 0)
            if per_turn:
                region.trust = _clamp(region.trust + per_turn)
            modifier["turns_left"] = modifier.get("turns_left", 1) - 1
            if modifier["turns_left"] <= 0:
                expired.append(modifier)

        for modifier in expired:
            region.modifiers.remove(modifier)


def run_global_passives(pack, state, report, support_start: float) -> None:
    settings = pack.settings
    flags = tech_flags(pack, state)

    decay = settings.initiative_decay + math.floor(state.al_support / 15)
    state.initiative = _clamp(state.initiative - decay)
    report.global_deltas["initiative"] = (
        report.global_deltas.get("initiative", 0) - decay
    )

    growth = 1 + flags.get("corruption_growth_delta", 0)
    if growth != 0:
        state.corruption = _clamp(state.corruption + growth)
        report.global_deltas["corruption"] = (
            report.global_deltas.get("corruption", 0) + growth
        )

    if state.vacant_roles:
        penalty = len(state.vacant_roles)
        state.initiative = _clamp(state.initiative - penalty)
        report.global_deltas["initiative"] = (
            report.global_deltas.get("initiative", 0) - penalty
        )
        report.al_nazra_notes.append(f"Вакантные роли: -{penalty} инициативы.")

    avg_security = average(region.security for region in state.regions.values())
    raw_drift = (
        math.floor((100 - avg_security) / 25)
        + math.floor((100 - mean_stat(state, "trust")) / 25)
        - 1
        - flags.get("intel_slow", 0)
    )
    drift = max(-2, min(5, raw_drift))
    mean_now = mean_stat(state, "al_nazra")
    target = max(support_start - 5, min(support_start + 6, mean_now + drift))
    nudge_mean(state, "al_nazra", target)
    report.global_deltas["al_nazra_support"] = round_half_up(
        mean_stat(state, "al_nazra")
    ) - round_half_up(support_start)

    avg_economy = average(region.economy for region in state.regions.values())
    eco_part = math.floor(avg_economy / 10)
    tech_part = flags.get("income_bonus", 0) + state.pending_income_bonus
    corr_part = math.floor(state.corruption / 20)
    income = settings.base_income + eco_part + tech_part - corr_part
    upkeep_total = sum(item.cost for item in state.upkeep)
    income += state.pending_income - upkeep_total
    state.budget += income
    report.income = income
    report.upkeep_paid = upkeep_total
    report.income_parts = {
        "base": settings.base_income,
        "economy": eco_part,
        "tech": tech_part,
        "corruption": -corr_part,
        "upkeep": -upkeep_total,
        "queued": state.pending_income,
    }
    state.pending_income = 0
    state.pending_income_bonus = 0

    civil_upkeep = sum(1 for item in state.upkeep if item.owner_role == "civil_admin")
    if civil_upkeep:
        applied = spread_stat(state, "trust", civil_upkeep)
        report.global_deltas["trust_global"] = (
            report.global_deltas.get("trust_global", 0) + applied
        )
        report.region_notes.append(f"Гражданские объекты: +{applied} доверия.")

    if upkeep_total > 0 and state.budget < 0:
        applied = spread_stat(state, "trust", -1)
        report.global_deltas["trust_global"] = (
            report.global_deltas.get("trust_global", 0) + applied
        )

    if state.budget < 0:
        state.initiative = _clamp(state.initiative - 3)
        report.global_deltas["initiative"] = (
            report.global_deltas.get("initiative", 0) - 3
        )
        state.deficit_mult = 1.1
    else:
        state.deficit_mult = 1.0

    for key in list(state.recon_bonus):
        state.recon_bonus[key] -= 1
        if state.recon_bonus[key] <= 0:
            del state.recon_bonus[key]


def average(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def check_endings(pack, state, report) -> None:
    if state.trust >= 100 and state.al_support <= 20:
        report.result = "victory_full"
        report.result_reason = "Полная победа: доверие 100%, Аль Назра подавлена."
        return

    if state.initiative <= 0:
        report.result = "defeat"
        report.result_reason = "Поражение: инициатива исчерпана."
        return

    if state.budget <= -20:
        report.result = "defeat"
        report.result_reason = "Поражение: финансовый коллапс."
        return

    if state.al_support >= 100:
        report.result = "defeat"
        report.result_reason = "Поражение: Аль Назра захватила страну."
        return

    occupied = [
        region for region in state.regions.values() if region.status == "occupied"
    ]
    if len(occupied) >= 4:
        report.result = "defeat"
        report.result_reason = "Поражение: 4 региона оккупированы."
        return

    central = state.regions.get("R4")
    if central is not None and central.status == "occupied":
        report.result = "defeat"
        report.result_reason = "Поражение: столица оккупирована."
        return

    active_count = len(state.active_roles)
    if active_count > 0 and len(state.vacant_roles) > active_count / 2:
        report.result = "defeat"
        report.result_reason = "Поражение: штаб развалился."
        return

    if state.turn >= state.total_turns:
        if (
            state.trust >= 70
            and state.al_support <= 10
            and not state.hideouts
            and all(
                STATUS_RANK[region.status] >= STATUS_RANK["unstable"]
                for region in state.regions.values()
            )
        ):
            report.result = "victory_campaign"
            report.result_reason = "Кампания завершена успешно."
        elif state.trust >= 50 and state.al_support <= 25:
            report.result = "victory_partial"
            report.result_reason = "Частичный успех операции."
        else:
            report.result = "defeat"
            report.result_reason = "Поражение: цели кампании не достигнуты."
