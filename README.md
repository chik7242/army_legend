[README.md](https://github.com/user-attachments/files/34703489/README.md)
# ARMY LEGEND Mini App + Admin

## Возможности
- Mini App: каталог, поиск, фильтр Android/iOS/PC, карточка товара, выбор тарифов, профиль и список покупок.
- Бот: Telegram Web App кнопка, проверка подписи `initData`, Telegram Stars invoice (`XTR`), pre-checkout и подтверждение успешной оплаты.
- Админка: `/admin` (HTTP Basic Auth), остатки, список заказов, массовая загрузка ключей — один ключ на строку.
- Склад: SQLite. После успешной оплаты ключ атомарно резервируется и отправляется пользователю. Если ключей нет — заказ `paid_waiting_stock`; при загрузке новых ключей ожидающие заказы автоматически обрабатываются по FIFO.

## Критически важно
1. Для цифровых товаров внутри Telegram применяются Telegram Stars (`XTR`). Цены задаются целыми числами Stars в `bot.py` и отображаются символом ⭐ во фронтенде. Не путайте Stars с рублями.
2. Это starter-проект. Прежде чем принимать реальные деньги, протестируйте оплату, выдачу, повторные обновления, возвраты и сбои доставки. Обработчик подтверждает успешную оплату только после Telegram `successful_payment`.
3. В админке ключи отображаются при загрузке и хранятся в SQLite. Ограничьте доступ к `/admin`, используйте уникальный длинный пароль, HTTPS и постоянный диск для БД.
4. Если Telegram не сможет доставить сообщение пользователю (например, пользователь заблокировал бота), ключ останется назначенным заказу; понадобится ручная повторная отправка из резервной копии/БД. Не загружайте в магазин ключи, на распространение которых у вас нет прав.
5. Система рассчитана на один экземпляр polling-бота. Не запускайте два экземпляра с одним токеном.

## Файлы
- `index.html`, `styles.css`, `app.js` — frontend.
- `bot.py` — aiogram 3 + FastAPI API, платежи и склад.
- `admin.html` — закрытая админ-панель.
- `.env.example` — пример переменных окружения.

## Настройка
1. В `@BotFather` создайте бота `/newbot`, скопируйте токен.
2. Скопируйте `.env.example` в `.env` и заполните `BOT_TOKEN`, `BOT_USERNAME`, `WEBAPP_URL`, `SUPPORT_USERNAME`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `FRONTEND_ORIGIN`.
3. В `bot.py` измените `PRODUCTS`, а в `app.js` синхронно измените массив `products`. `id`, тарифы и цены должны совпадать. Цены — Stars.
4. В `app.js` поменяйте `API_BASE`, `CHANNEL_URL`, `SUPPORT_URL`.
5. Установите Python 3.10+: `pip install -r requirements.txt`, затем `python bot.py`.
6. Разместите frontend на Vercel / GitHub Pages / Render Static Site. Укажите его HTTPS URL в `WEBAPP_URL` и настройках Mini App в BotFather.
7. Разместите backend как Python Web Service. Build: `pip install -r requirements.txt`; Start: `python bot.py`. Настройте переменные окружения и постоянный диск для `store.db`. В `FRONTEND_ORIGIN` укажите точный URL фронтенда.
8. В Telegram откройте бота, отправьте `/start`, нажмите кнопку магазина.

## Админка и загрузка ключей
1. Откройте `https://ВАШ-BACKEND/admin`.
2. Введите `ADMIN_USERNAME` и `ADMIN_PASSWORD` из `.env`.
3. Выберите товар из списка.
4. Вставьте ключи: один ключ на строку. Нажмите «Загрузить ключи».
5. Дубликаты будут пропущены. Если есть оплаченные заказы без ключа, система выдаст добавленные ключи ожидающим покупателям автоматически.

`product_id` в админке берётся из ключей словаря `PRODUCTS` в `bot.py`, например `cry4me`, `jarvis`, `deadnight`.

## Локальный запуск
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```
Для теста Mini App backend должен быть доступен по HTTPS; используйте HTTPS tunnel. Для production обязательно проверьте поддержку polling, постоянное хранение файлов и доступность сервиса.

## Production checklist
- Использовать секреты только в переменных окружения, никогда не в `app.js`.
- HTTPS, сложный пароль админки, ограничение доступа к панели (например, IP allowlist/VPN).
- Резервное копирование SQLite и безопасное хранение ключей.
- Ограничить `/api/order-status` (в коде проверяется `initData` и владелец заказа).
- Реализовать процесс возврата Stars (`refundStarPayment`) и ручную повторную отправку назначенного ключа.
- Проверить политику конфиденциальности, налоги, правила Telegram и права на продаваемые товары.
