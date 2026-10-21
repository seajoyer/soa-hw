# Marketplace: OpenAPI + CRUD

Домашнее задание №2.

## Запуск

```bash
docker compose up --build
```

API доступно на `http://localhost:8000`, Swagger UI — `http://localhost:8000/docs`.

Все эндпоинты, кроме `/auth/*`, требуют заголовок `Authorization: Bearer <access_token>`. Пользователь регистрируется через `POST /auth/register` с ролью `USER`, `SELLER` или `ADMIN`, токены выдаёт `POST /auth/login`, новый access token — `POST /auth/refresh`.

Логи запросов в JSON:

```bash
docker compose logs -f app
```

Интервал между созданиями и между обновлениями заказа одного пользователя задаётся переменной `ORDER_RATE_LIMIT_MINUTES` в `docker-compose.yml`.

Просмотр таблиц:

```bash
docker compose exec postgres psql -U marketplace -c "SELECT * FROM products"
docker compose exec postgres psql -U marketplace -c "SELECT * FROM orders"
docker compose exec postgres psql -U marketplace -c "SELECT * FROM order_items"
docker compose exec postgres psql -U marketplace -c "SELECT * FROM promo_codes"
docker compose exec postgres psql -U marketplace -c "SELECT * FROM user_operations"
```

## Структура

| Путь | Содержимое |
|---|---|
| `openapi/openapi.yaml` | OpenAPI-спецификация |
| `codegen/main.jinja2` | шаблон кодогенерации роутера |
| `migrations/` | миграции Flyway |
| `app/` | реализация сервиса |
| `app/generated/` | сгенерированный код (в `.gitignore`) |

## Кодогенерация

Код генерируется из спецификации при сборке Docker-образа. Локально:

```bash
pip install fastapi-code-generator==0.8.1
fastapi-codegen -i openapi/openapi.yaml -o app/generated -t codegen -p 3.12 --strict-nullable --disable-timestamp --include-request-argument
```

Генерируются:
- `app/generated/models.py` — DTO и enum'ы из `components/schemas`;
- `app/generated/main.py` — по абстрактному классу на тег (`AuthApi`, `ProductsApi`, `OrdersApi`, `PromoCodesApi`) с методами операций и методом `router()`, создающим FastAPI-роутер с эндпоинтами из спецификации, которые вызывают эти методы.

`app/auth.py`, `app/products.py`, `app/orders.py`, `app/promo_codes.py` реализуют эти классы, `app/main.py` подключает роутеры.
