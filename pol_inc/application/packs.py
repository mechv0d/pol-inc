from __future__ import annotations

from pydantic import ValidationError

from pol_inc.config import Settings
from pol_inc.domain.errors import PackLoadError, PackMismatch, PackNotFound
from pol_inc.domain.packs import GamePack, GamePackMeta
from pol_inc.infrastructure.supabase import SupabaseStorageClient


class PackService:
    def __init__(self, storage: SupabaseStorageClient, settings: Settings) -> None:
        self._storage = storage
        self._settings = settings

    async def list_metas(self) -> list[GamePackMeta]:
        raw = await self._storage.get_json(
            self._settings.packs_bucket,
            self._settings.packs_index_object,
        )

        items = raw.get("packs") if isinstance(raw, dict) else raw

        if not isinstance(items, list):
            raise PackLoadError("index.json должен содержать список паков или ключ 'packs'.")

        try:
            return [GamePackMeta.model_validate(item) for item in items]
        except ValidationError as exc:
            raise PackLoadError("index.json содержит некорректные метаданные пака.") from exc

    async def get_meta(self, pack_id: str) -> GamePackMeta:
        metas = await self.list_metas()
        pack_id_normalized = pack_id.strip().lower()

        for meta in metas:
            if meta.id.lower() == pack_id_normalized:
                return meta

        raise PackNotFound(f"Пак с id '{pack_id}' не найден.")

    async def load_pack(self, meta: GamePackMeta) -> GamePack:
        object_name = meta.file or f"{meta.id}.json"
        raw = await self._storage.get_json(self._settings.packs_bucket, object_name)

        try:
            pack = GamePack.model_validate(raw)
        except ValidationError as exc:
            raise PackLoadError(f"Файл пака {object_name} некорректен.") from exc

        if pack.id != meta.id:
            raise PackMismatch(f"В файле указан id '{pack.id}', но в индексе '{meta.id}'.")

        return pack

    def image_url(self, object_name: str | None) -> str | None:
        return self._storage.public_url(self._settings.images_bucket, object_name)