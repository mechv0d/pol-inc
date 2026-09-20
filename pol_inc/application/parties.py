from __future__ import annotations

from pol_inc.domain.errors import PartyError
from pol_inc.domain.packs import PartyRecord
from pol_inc.infrastructure.supabase import SupabaseStorageClient


class PartyRepository:
    def __init__(self, storage: SupabaseStorageClient) -> None:
        self._storage = storage

    async def get(self, user_id: int) -> PartyRecord | None:
        data = await self._storage.get_party(user_id)
        if data is None:
            return None
        try:
            return PartyRecord.model_validate(data)
        except Exception as exc:
            raise PartyError(f"Не удалось загрузить партию для пользователя {user_id}: {exc}")

    async def upsert(self, record: PartyRecord) -> None:
        try:
            await self._storage.upsert_party(record.user_id, record.model_dump())
        except Exception as exc:
            raise PartyError(f"Не удалось сохранить партию для пользователя {record.user_id}: {exc}")

    async def delete(self, user_id: int) -> None:
        try:
            await self._storage.delete_party(user_id)
        except Exception as exc:
            raise PartyError(f"Не удалось удалить партию для пользователя {user_id}: {exc}")