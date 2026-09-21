from enum import Enum


class SessionStatus(str, Enum):
    NEW = "new"
    IN_GAME = "in_game"
    FINISHED = "finished"
    CLOSED = "closed"
