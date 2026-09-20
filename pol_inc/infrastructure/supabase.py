from __future__ import annotations

from urllib.parse import quote

import httpx

from pol_inc.config import Settings
from pol_inc.domain.errors import PackLoadError, PackNotFound


class SupabaseStorageClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._headers = {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
        }
        self._client = httpx.AsyncClient(
            base_url=settings.supabase_url.rstrip("/"),
            headers=self._headers,
            timeout=httpx.Timeout(30.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_json(self, bucket: str, object_name: str):
        object_name = object_name.lstrip("/")

        if not object_name:
            raise PackLoadError("Имя объекта в Supabase Storage не указано.")

        path = f"/storage/v1/object/{quote(bucket, safe='')}/{quote(object_name, safe='/')}"

        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise PackLoadError("Не удалось подключиться к Supabase Storage.") from exc

        if response.status_code == 404:
            raise PackNotFound(f"Объект {object_name} не найден в бакете {bucket}.")

        if response.status_code >= 400:
            raise PackLoadError(f"Supabase Storage вернул статус {response.status_code}.")

        try:
            return response.json()
        except ValueError as exc:
            raise PackLoadError("Ответ Supabase Storage не является корректным JSON.") from exc

    async def upsert_json(self, bucket: str, object_name: str, data: dict) -> None:
        object_name = object_name.lstrip("/")

        if not object_name:
            raise PackLoadError("Имя объекта в Supabase Storage не указано.")

        path = f"/storage/v1/object/{quote(bucket, safe='')}/{quote(object_name, safe='/')}"

        try:
            response = await self._client.post(
                path,
                json=data,
                headers={
                    "x-upsert": "true",
                    **self._headers,
                },
            )
        except httpx.HTTPError as exc:
            raise PackLoadError("Не удалось сохранить данные в Supabase Storage.") from exc

        if response.status_code >= 400:
            raise PackLoadError(f"Supabase Storage вернул статус {response.status_code}.")

    async def get_party(self, user_id: int) -> dict | None:
        bucket = self._settings.party_bucket
        try:
            data = await self.get_json(bucket, f"{user_id}.json")
            return data
        except PackNotFound:
            return None

    async def upsert_party(self, user_id: int, data: dict) -> None:
        bucket = self._settings.party_bucket
        await self.upsert_json(bucket, f"{user_id}.json", data)

    async def delete_party(self, user_id: int) -> None:
        bucket = self._settings.party_bucket
        path = f"/storage/v1/object/{bucket}/{user_id}.json"
        try:
            response = await self._client.delete(
                path,
                headers=self._headers,
            )
            if response.status_code >= 400:
                raise PackLoadError(f"Supabase Storage вернул статус {response.status_code}.")
        except httpx.HTTPError as exc:
            raise PackLoadError("Не удалось удалить партию из Supabase Storage.") from exc

    def public_url(self, bucket: str, object_name: str | None) -> str | None:
        if not object_name:
            return None

        object_name = object_name.lstrip("/")
        base = self._settings.supabase_url.rstrip("/")

        return f"{base}/storage/v1/object/public/{quote(bucket, safe='')}/{quote(object_name, safe='/')}"