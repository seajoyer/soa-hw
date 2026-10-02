# Маркетплейс — архитектурное проектирование

Домашнее задание №1: архитектура маркетплейса (C4) и инициализация сервиса.

## C4 Container diagram

![C4 Container diagram](docs/c4-container.svg)

Исходник диаграммы: [`docs/c4-container.puml`](docs/c4-container.puml) (C4-PlantUML).

### Контейнеры

| Контейнер | Технология | Назначение |
|---|---|---|
| Web App | SPA | Веб-интерфейс для покупателей и продавцов |
| Mobile App | iOS / Android | Мобильное приложение для покупателей |
| API Gateway | Reverse proxy | Единая точка входа: маршрутизация, проверка JWT, rate limiting |
| User Service | Python, FastAPI | Регистрация, аутентификация, профили и роли |
| Catalog Service | Python, FastAPI | Товары, категории, цены, остатки; управление каталогом продавцами |
| Feed Service | Python, FastAPI | Персонализированная лента товаров |
| Order Service | Python, FastAPI | Оформление заказов и их жизненный цикл |
| Payment Service | Python, FastAPI | Проведение платежей, возвраты, учёт транзакций |
| Notification Service | Python, FastAPI | Уведомления о статусах заказов |
| User / Catalog / Order / Payment / Notification DB | PostgreSQL | Собственная БД каждого сервиса |
| Feed DB | Redis | Предрассчитанные ленты и read-модель товаров |
| Message Broker | Kafka | Асинхронный обмен доменными событиями |

Внешние системы: платёжный провайдер (эквайринг), провайдер Email/SMS/Push.

## Реализованный сервис: Order Service

В репозитории поднят `order-service` (`services/order-service`). Бизнес-логики нет — только health-check:

- `GET /health` → `200 OK`, `{"status": "ok", "service": "order-service"}`

## Запуск

Требования: Docker с плагином Docker Compose.

```sh
docker compose up --build -d
curl -i http://localhost:8000/health
```

Ожидаемый ответ:

```
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","service":"order-service"}
```

Статус health-check контейнера (через ~10 секунд после старта должен быть `healthy`):

```sh
docker inspect -f '{{.State.Health.Status}}' order-service
```

Остановка:

```sh
docker compose down
```

## Перегенерация диаграммы

```sh
plantuml -tsvg docs/c4-container.puml
plantuml -tpng docs/c4-container.puml
```

## Структура репозитория

```
.
├── README.md
├── docker-compose.yml
├── docs/
│   ├── c4-container.puml   # исходник C4 Container диаграммы
│   ├── c4-container.svg
│   └── c4-container.png
└── services/
    └── order-service/
        ├── Dockerfile
        ├── requirements.txt
        └── app/main.py
```
