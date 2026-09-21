class PolIncError(Exception):
    """Базовая ошибка проекта."""


class PackError(PolIncError):
    """Базовая ошибка работы с паками."""


class PackNotFound(PackError):
    """Пак не найден."""


class PackLoadError(PackError):
    """Ошибка загрузки или парсинга пака."""


class PackMismatch(PackError):
    """ID пака в индексе и в файле не совпадают."""


class SessionError(PolIncError):
    """Базовая ошибка игровой сессии."""


class SessionNotFound(SessionError):
    """Сессия не найдена."""


class ChatAlreadyHasSession(SessionError):
    """В этом чате уже есть игровая сессия."""


class UserAlreadyInSession(SessionError):
    """Пользователь уже участвует в сессии."""


class SessionFull(SessionError):
    """Сессия заполнена."""


class SessionAlreadyStarted(SessionError):
    """Сессия уже запущена или закрыта."""


class SessionAttachedToAnotherChat(SessionError):
    """Сессия привязана к другому чату."""


class UserNotInSession(SessionError):
    """Пользователь не состоит в сессии."""


class NotSessionCreator(SessionError):
    """Действие доступно только создателю сессии."""


class PlayerNotFound(SessionError):
    """Игрок не найден внутри сессии."""


class PartyValidationError(SessionError):
    """Ошибка регистрации партии."""


class PartyError(SessionError):
    """Ошибка работы с партией."""


class PartyNotFound(PartyError):
    """Партия не найдена."""


class SessionCannotStart(SessionError):
    """Сессию нельзя запустить."""


class GameNotRunning(SessionError):
    """Игра сейчас не запущена."""


class VoteError(SessionError):
    """Ошибка голосования."""


class VoteChangeCooldown(VoteError):
    """Голос можно менять не чаще одного раза в минуту."""


class PlayerEliminated(SessionError):
    """Игрок покинул активную игру и не может голосовать вручную."""


class ActionError(SessionError):
    """Ошибка действия, исследования или голосования."""
