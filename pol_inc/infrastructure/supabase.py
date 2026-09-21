from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from pol_inc.config import Settings
from pol_inc.domain.errors import PackLoadError, PackNotFound

logger = logging.getLogger(__name__)


def _response_detail(response: httpx.Response, limit: int = 500) -> str:
    try:
        text = response.text
    except Exception:  # noqa: BLE001
        return ""

    return text[:limit]


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
        self._ensured_buckets: set[str] = set()

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
            detail = _response_detail(response)
            logger.warning(
                "Supabase Storage GET %s вернул статус %s: %s",
                path,
                response.status_code,
                detail,
            )
            raise PackLoadError(
                f"Supabase Storage вернул статус {response.status_code}: {detail}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise PackLoadError(
                "Ответ Supabase Storage не является корректным JSON."
            ) from exc

    async def ensure_bucket(self, bucket: str, public: bool = False) -> None:
        if bucket in self._ensured_buckets:
            return

        path = f"/storage/v1/bucket/{quote(bucket, safe='')}"

        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise PackLoadError(
                "Не удалось проверить бакет в Supabase Storage."
            ) from exc

        if response.status_code == 404:
            try:
                created = await self._client.post(
                    "/storage/v1/bucket",
                    json={"id": bucket, "name": bucket, "public": public},
                )
            except httpx.HTTPError as exc:
                raise PackLoadError(
                    "Не удалось создать бакет в Supabase Storage."
                ) from exc

            if created.status_code == 409:
                logger.info("Бакет %s уже существует.", bucket)
            elif created.status_code >= 400:
                detail = _response_detail(created)
                logger.warning(
                    "Supabase Storage не смог создать бакет %s: %s %s",
                    bucket,
                    created.status_code,
                    detail,
                )
                raise PackLoadError(
                    f"Не удалось создать бакет {bucket}: "
                    f"статус {created.status_code}: {detail}"
                )
            else:
                logger.info("Создан бакет %s в Supabase Storage.", bucket)
        elif response.status_code >= 400:
            detail = _response_detail(response)
            logger.warning(
                "Supabase Storage GET %s вернул статус %s: %s",
                path,
                response.status_code,
                detail,
            )
            raise PackLoadError(
                f"Supabase Storage вернул статус {response.status_code}: {detail}"
            )

        self._ensured_buckets.add(bucket)

    async def upsert_json(self, bucket: str, object_name: str, data: dict) -> None:
        object_name = object_name.lstrip("/")

        if not object_name:
            raise PackLoadError("Имя объекта в Supabase Storage не указано.")

        await self.ensure_bucket(bucket)

        path = f"/storage/v1/object/{quote(bucket, safe='')}/{quote(object_name, safe='/')}"

        try:
            response = await self._client.post(
                path,
                json=data,
                headers={
                    "Content-Type": "application/json",
                    "x-upsert": "true",
                    **self._headers,
                },
            )
        except httpx.HTTPError as exc:
            raise PackLoadError(
                "Не удалось сохранить данные в Supabase Storage."
            ) from exc

        if response.status_code >= 400:
            detail = _response_detail(response)
            logger.warning(
                "Supabase Storage POST %s вернул статус %s: %s",
                path,
                response.status_code,
                detail,
            )
            raise PackLoadError(
                f"Supabase Storage вернул статус {response.status_code}: {detail}"
            )

    async def upload_bytes(
        self,
        bucket: str,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        object_name = object_name.lstrip("/")

        if not object_name:
            raise PackLoadError("Имя объекта в Supabase Storage не указано.")

        if not data:
            raise PackLoadError("Пустой файл нельзя загрузить в Supabase Storage.")

        await self.ensure_bucket(bucket)

        path = f"/storage/v1/object/{quote(bucket, safe='')}/{quote(object_name, safe='/')}"

        try:
            response = await self._client.post(
                path,
                content=data,
                headers={
                    "Content-Type": content_type,
                    "x-upsert": "true",
                    **self._headers,
                },
            )
        except httpx.HTTPError as exc:
            raise PackLoadError(
                "Не удалось загрузить файл в Supabase Storage."
            ) from exc

        if response.status_code >= 400:
            detail = _response_detail(response)
            logger.warning(
                "Supabase Storage POST %s вернул статус %s: %s",
                path,
                response.status_code,
                detail,
            )
            raise PackLoadError(
                f"Supabase Storage вернул статус {response.status_code}: {detail}"
            )

    async def download_bytes(self, bucket: str, object_name: str) -> bytes:
        object_name = object_name.lstrip("/")

        if not object_name:
            raise PackLoadError("Имя объекта в Supabase Storage не указано.")

        path = f"/storage/v1/object/{quote(bucket, safe='')}/{quote(object_name, safe='/')}"

        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise PackLoadError("Не удалось скачать файл из Supabase Storage.") from exc

        if response.status_code == 404:
            raise PackNotFound(f"Объект {object_name} не найден в бакете {bucket}.")

        if response.status_code >= 400:
            detail = _response_detail(response)
            logger.warning(
                "Supabase Storage GET %s вернул статус %s: %s",
                path,
                response.status_code,
                detail,
            )
            raise PackLoadError(
                f"Supabase Storage вернул статус {response.status_code}: {detail}"
            )

        return response.content

    def public_url(self, bucket: str, object_name: str | None) -> str | None:
        if not object_name:
            return None

        object_name = object_name.lstrip("/")
        base = self._settings.supabase_url.rstrip("/")

        return f"{base}/storage/v1/object/public/{quote(bucket, safe='')}/{quote(object_name, safe='/')}"
