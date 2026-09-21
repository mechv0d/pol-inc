from __future__ import annotations

from pydantic import ValidationError

from pol_inc.config import Settings
from pol_inc.domain.errors import PackLoadError, PackMismatch, PackNotFound
from pol_inc.domain.tarbin_pack import TarbinGamePack
from pol_inc.infrastructure.supabase import SupabaseStorageClient


class TarbinPackMeta:
    def __init__(self, id: str, name: str, description: str = "") -> None:
        self.id = id
        self.name = name
        self.description = description


class TarbinPackService:
    def __init__(self, storage: SupabaseStorageClient, settings: Settings) -> None:
        self._storage = storage
        self._settings = settings

    async def list_metas(self) -> list[TarbinPackMeta]:
        raw = await self._storage.get_json(
            self._settings.packs_bucket,
            self._settings.packs_index_object,
        )

        items = raw.get("packs") if isinstance(raw, dict) else raw

        if not isinstance(items, list):
            raise PackLoadError(
                "index.json должен содержать список паков или ключ 'packs'."
            )

        metas: list[TarbinPackMeta] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            metas.append(
                TarbinPackMeta(
                    id=str(item.get("id", "")),
                    name=str(item.get("name", "")),
                    description=str(item.get("description", "")),
                )
            )

        return metas

    async def get_meta(self, pack_id: str) -> TarbinPackMeta:
        metas = await self.list_metas()
        pack_id_normalized = pack_id.strip().lower()

        for meta in metas:
            if meta.id.lower() == pack_id_normalized:
                return meta

        raise PackNotFound(f"Пак с id '{pack_id}' не найден.")

    async def load_pack(self, meta: TarbinPackMeta) -> TarbinGamePack:
        object_name = f"{meta.id}.json"
        raw = await self._storage.get_json(self._settings.packs_bucket, object_name)

        try:
            pack = TarbinGamePack.model_validate(raw)
        except ValidationError as exc:
            raise PackLoadError(f"Файл пака {object_name} некорректен.") from exc

        if pack.id != meta.id:
            raise PackMismatch(
                f"В файле указан id '{pack.id}', но в индексе '{meta.id}'."
            )

        return pack

    def image_url(self, object_name: str | None) -> str | None:
        return self._storage.public_url(self._settings.images_bucket, object_name)

    async def get_image_bytes(self, object_name: str | None) -> bytes | None:
        if not object_name:
            return None

        try:
            return await self._storage.download_bytes(
                self._settings.images_bucket, object_name
            )
        except (PackNotFound, PackLoadError):
            return None
