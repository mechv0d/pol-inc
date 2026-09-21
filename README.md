# TARBIN: Миротворческая миссия — Telegram-бот

Кооперативная нарративно-стратегическая игра. Игроки — штаб миротворческой
операции в вымышленной стране Тарбин: 6 ролей, 8 регионов, технологии,
бюджет и скрытый противник Al Nazra. Победа и поражение — общие.

Дизайн-документ: `docs/TARBIN_DD.md`.
Базовый пак: `docs/tarbin_classic_v1.json` (загрузить в Supabase Storage
в бакет `game-packs` вместе с `docs/index.json` как `index.json`,
баннеры — в публичный бакет `pack-images`).

## Команды (групповой чат)

`/newgame`, `/join`, `/leavegame`, `/operation`, `/startgame`,
`/closegame`, `/game`, `/ss`, `/status`, `/help`

## Команды (личные сообщения)

`/menu`, `/actions`, `/research`, `/regions`, `/event`,
`/confirm`, `/cancel`, `/loy`, `/help`

## Редактор паков

Графический редактор GamePack: `tools/pack_editor`
(`.venv\Scripts\python tools\pack_editor\editor.py` из корня репозитория).
