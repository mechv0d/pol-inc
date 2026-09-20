from enum import Enum


class SessionStatus(str, Enum):
    NEW = "new"
    IN_GAME = "in_game"
    FINISHED = "finished"
    CLOSED = "closed"


class FactionId(str, Enum):
    ARMY = "army"
    PEOPLE = "people"
    BUSINESS = "business"
    WEST = "west"
    POPULISM = "populism"

    @property
    def label(self) -> str:
        return {
            self.ARMY: "Армия",
            self.PEOPLE: "Народ",
            self.BUSINESS: "Бизнес",
            self.WEST: "Запад",
            self.POPULISM: "Популизм",
        }[self]

    @property
    def emoji(self) -> str:
        return {
            self.ARMY: "🔴",
            self.PEOPLE: "🟢",
            self.BUSINESS: "🟡",
            self.WEST: "🔵",
            self.POPULISM: "🔘",
        }[self]