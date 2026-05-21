# webhook-shield

Self-hosted платформа для webhook ingress: **n8n** (оркестрация) + **FastAPI gateway** (HMAC, idempotency, rate limit) + **observability** (Prometheus, Grafana, Loki).

Принимает внешние webhook'и, валидирует на edge, передаёт в n8n workflow для интеграций (Google Sheets, CRM, LLM, Telegram).

## Компоненты

- n8n self-hosted в Docker (queue mode, PostgreSQL, 3 worker'а).
- nginx — reverse proxy, единая точка входа.
- FastAPI gateway — HMAC, idempotency, rate limit, метрики.
- Redis — idempotency, dedup, DLQ, очередь n8n.
- Observability — Prometheus, Grafana, Loki, Promtail.

## Workflow

- **`Google Sheet`** — основной pipeline: webhook → dedup → LLM → Google Sheets → Telegram → amoCRM; ошибки → DLQ.
- **`Payment_bot_menu`** — генератор payment-событий (cron), подпись HMAC, отправка через gateway.
- **`Retry_runner`** — повторная обработка из DLQ (до 3 попыток), затем `final_failed:webhooks`.
- **`Agent_Router_Filter`** — LLM-классификация intent → IF → Bitrix (лид) / ответ / уточнение.
- **`Amo_lead_test`** / **`Bitrix_Lead_test`** — изолированные workflow для интеграции с CRM API.

## Архитектура

```text
Browser / curl / Payment_bot
    |
    v
nginx :80
    |
    +-- /webhook/* --> FastAPI gateway :8000  (HMAC, idempotency — один раз для всех)
    |                        |
    |                        v
    +-- /* (UI) ----> n8n main :5678  <--------+
             |         (бизнес-логика,          |
             |          без Crypto/IF на каждый webhook)
             +--> PostgreSQL                   |
             +--> Redis queue                   |
                      |                        |
                      +--> n8n-worker-1/2/3    |
                                               |
             observability (Prometheus/Grafana/Loki)
             redis-exporter (DLQ counter)
```

`n8n main` принимает UI, API и webhook'и. Workflow executions кладутся в Redis и выполняются worker'ами.

## Структура

```text
.
├── README.md
├── gateway/                 # FastAPI ingress
│   ├── app/
│   │   ├── main.py          # FastAPI app, подключение routers
│   │   ├── dependencies.py
│   │   ├── core/            # config, security, metrics, lifespan
│   │   ├── middleware/      # Prometheus HTTP metrics
│   │   ├── routers/         # HTTP endpoints (/health, /metrics, /webhook)
│   │   ├── services/        # бизнес-логика (оркестрация)
│   │   ├── clients/         # внешние клиенты (n8n, Redis)
│   │   └── schemas/         # DTO / response models
│   ├── Dockerfile
│   └── requirements.txt
└── infra
    ├── docker-compose.yml
    ├── nginx/
    │   ├── nginx.conf       # limit_req_zone для /webhook/
    │   └── conf.d/default.conf
    ├── .env.example
    ├── .htpasswd.example
    └── observability/
        ├── prometheus/prometheus.yml
        ├── loki/loki-config.yml
        ├── promtail/promtail-config.yml
        └── grafana/
```

Файлы `infra/.env` и `infra/.htpasswd` не должны попадать в GitHub.

## Требования

- Docker Desktop / Docker Engine
- Docker Compose v2
- Google account для Google Sheets OAuth2
- Telegram bot token, если нужен Telegram workflow

Проверка:

```bash
docker --version
docker compose version
```

## Быстрый запуск

Перейти в папку инфраструктуры:

```bash
cd infra
```

Создать локальный `.env`:

```bash
cp .env.example .env
```

В `.env` поменять пароль Postgres:

```env
POSTGRES_PASSWORD=change_me_postgres
```

Запустить стек:

```bash
docker compose up -d
```

Проверить контейнеры:

```bash
docker compose ps
```

Ожидаемые сервисы:

```text
postgres
redis
n8n
n8n-worker-1
n8n-worker-2
n8n-worker-3
nginx
gateway
prometheus
grafana
```

Открыть n8n:

```text
http://localhost
```

На первом запуске n8n попросит создать owner-аккаунт.

## Остановка

Остановить контейнеры:

```bash
docker compose down
```

Остановить и удалить volumes с данными:

```bash
docker compose down -v
```

Осторожно: `down -v` удалит PostgreSQL, Redis и данные n8n.

## Переменные окружения

Основные переменные находятся в `infra/.env.example`.

```env
POSTGRES_USER=n8n
POSTGRES_PASSWORD=change_me_postgres
POSTGRES_DB=n8n

N8N_HOST=localhost
N8N_PORT=5678
N8N_PROTOCOL=http
WEBHOOK_URL=http://localhost/
N8N_EDITOR_BASE_URL=http://localhost/
N8N_PROXY_HOPS=1
N8N_SECURE_COOKIE=false

GENERIC_TIMEZONE=Europe/Moscow
TZ=Europe/Moscow

NGINX_PORT=80
```

Важно:

- `N8N_PORT=5678` — внутренний порт n8n в Docker.
- `NGINX_PORT=80` — внешний порт на машине.
- `N8N_SECURE_COOKIE=false` нужен для локального HTTP, особенно в Safari.
- `WEBHOOK_URL=http://localhost/` нужен, чтобы production webhook URL были корректными.

## nginx

`infra/nginx/nginx.conf` + `infra/nginx/conf.d/default.conf`:

- `/webhook/*` → **FastAPI gateway** (rate limit 10 req/s, burst 20)
- `/` → n8n UI

Внешние webhook'и **не попадают** напрямую в n8n — только через gateway. Внутри Docker `Payment_bot` и `Retry_runner` тоже шлют в **gateway** (`http://gateway:8000/webhook/...`), а не в n8n напрямую — подпись проверяется в одном месте.

В конфиге увеличены лимиты headers:

```nginx
client_header_buffer_size 16k;
large_client_header_buffers 8 32k;
```

Это нужно для длинных OAuth URL при подключении Google.

Basic auth сейчас отключён для локальной разработки. Если нужно включить обратно, можно вернуть:

```nginx
auth_basic "n8n";
auth_basic_user_file /etc/nginx/.htpasswd;
```

и примонтировать `.htpasswd` в `docker-compose.yml`.

## Queue mode

В `docker-compose.yml` включён queue mode:

```env
EXECUTIONS_MODE=queue
QUEUE_BULL_REDIS_HOST=redis
QUEUE_BULL_REDIS_PORT=6379
OFFLOAD_MANUAL_EXECUTIONS_TO_WORKERS=true
```

Смысл:

- `n8n` main принимает UI, API и webhook'и.
- Redis хранит очередь jobs.
- `n8n-worker-1/2/3` выполняют workflow executions.

Проверить логи worker'ов:

```bash
docker compose logs -f n8n-worker-1 n8n-worker-2 n8n-worker-3
```

Запустить webhook несколько раз и посмотреть, что executions обрабатываются worker'ами.

## Observability (неделя 6)

Стек: **Prometheus + Grafana + Loki + Promtail + redis-exporter**. Всё поднимается тем же `docker compose up -d`.

### Что смотрим

| Источник | Что даёт |
|----------|----------|
| n8n `/metrics` | очередь Bull (`waiting` / `active`), uptime |
| gateway `/metrics` | HTTP requests, 401/502/429, duplicates, upstream errors |
| redis-exporter | счётчик `dlq:webhooks:count` |
| Redis (Grafana datasource) | последняя причина DLQ: `last_failed_node`, `last_reason` |
| Promtail → Loki | логи всех контейнеров compose |

### Запуск

1. В `infra/.env` добавь (или скопируй из `.env.example`):

```env
GRAFANA_PORT=3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=change_me
```

2. Пересоздай n8n-контейнеры, чтобы подхватили `N8N_METRICS=true`:

```bash
cd infra
docker compose up -d
docker compose up -d --force-recreate n8n n8n-worker-1 n8n-worker-2 n8n-worker-3
docker compose restart nginx
```

3. Открой Grafana: http://localhost:3000  
   Dashboard: **Webhook Shield — Overview** (provisioned автоматически).

4. Проверка метрик n8n изнутри контейнера:

```bash
docker compose exec -T n8n wget -qO- http://127.0.0.1:5678/metrics | head
```

5. Логи в Grafana: **Explore → Loki**, запрос `{service="n8n"}` или `{container=~".*n8n.*"}`.

### Алерты → Telegram

Правила уже в `infra/observability/grafana/provisioning/alerting/rules.yml`:

- n8n metrics down (30s)
- gateway metrics down (30s)
- queue waiting > 100 (5m)
- DLQ counter > 0 (2m)

Contact point Telegram настраивается **один раз в UI** — см. `infra/observability/grafana/provisioning/alerting/README.md`.

На дашборде также **Last DLQ failed node** и **Last DLQ reason** (Redis datasource) — причина последнего DLQ-события.

### Важно после рестарта n8n

nginx может отдавать 502, пока n8n не поднимется — после `docker compose restart n8n*` всегда:

```bash
docker compose restart nginx
```

## FastAPI gateway (неделя 7)

### Ключевая идея проекта

**Не навешивать на каждый n8n-workflow одни и те же проверки** (HMAC, idempotency, rate limit, метрики ingress).

Без gateway типичная схема «n8n как есть»:

```text
Webhook → Crypto → IF подпись → Redis idempotency → IF → ... бизнес-логика
```

Каждый новый workflow (payment_failed, refund, subscription_renewed…) — **копипаста** Crypto + IF + Redis. Secret в трёх местах, легко разъехаться, сложно мониторить ingress.

**С gateway** cross-cutting concerns вынесены на edge **один раз**:

```text
                    ┌─────────────────────────────┐
  любой отправитель │  gateway (FastAPI)          │
  ─────────────────►│  HMAC, idempotency, /metrics│──► n8n workflow
                    │  rate limit (nginx)         │    (только бизнес:
                    └─────────────────────────────┘     Sheets, LLM, CRM…)
```

| Где | Что проверяем |
|-----|----------------|
| **Gateway** | подпись, idempotency, rate limit, метрики ingress |
| **n8n workflow** | dedup, LLM, интеграции, DLQ — **только предметная логика** |

Добавляешь новый webhook-route в gateway → один endpoint → forward в новый n8n workflow **без** Crypto/IF в каждом графе.

На собесе: *«n8n — оркестратор; gateway — edge layer. Не дублирую security в каждом workflow.»*

---

Внешний ingress для webhook'ов: **rate limit (nginx) → HMAC → idempotency (Redis SET NX) → forward в n8n**.

```text
POST /webhook/google-sheet
  → nginx limit_req (10 r/s, burst 20) → 429 при флуде
  → verify X-Signature (SHA256 HMAC, secret в WEBHOOK_HMAC_SECRET)
  → Redis SET gateway:idempotency:{key} NX EX 86400
  → если duplicate → 200 {"status":"duplicate"}
  → иначе POST http://n8n:5678/webhook/google-sheet (shared httpx pool)
```

**Маршрутизация nginx:** `/webhook/*` → gateway, остальное → n8n UI.

**Prometheus:** `GET /metrics` на gateway (job `gateway` в Prometheus).

**Health:**

```bash
curl -s http://127.0.0.1/health          # через nginx → gateway liveness
curl -s http://127.0.0.1/health/ready    # Redis ping
```

Переменные: `WEBHOOK_HMAC_SECRET`, `N8N_WEBHOOK_URL`, `IDEMPOTENCY_TTL_SECONDS` в `infra/.env.example`.

Пересборка после изменений кода:

```bash
cd infra
docker compose up -d --build gateway
docker compose restart nginx prometheus
```

### Активировать workflow Google Sheet (обязательно)

Если gateway отдаёт **404** от n8n — workflow не опубликован:

1. Открыть n8n → workflow **Google Sheet**.
2. Переключить **Inactive → Active** (toggle справа вверху).
3. Production URL должен быть: `http://localhost/webhook/google-sheet` (через nginx/gateway).

### Проверка HMAC curl'ом

Секрет — `WEBHOOK_HMAC_SECRET` в `infra/.env` (`super_test_secret_123` по умолчанию). Payment_bot подписывает тем же secret перед отправкой в gateway.

```bash
SECRET="super_test_secret_123"
KEY="test_$(date +%s)"
BODY=$(printf '{"event":"payment_succeeded","amount":100,"idempotency_key":"%s"}' "$KEY")
SIG=$(BODY="$BODY" SECRET="$SECRET" python3 -c \
  'import hashlib,hmac,json,os; b=json.loads(os.environ["BODY"]); m=json.dumps(b,separators=(",",":")).encode(); print(hmac.new(os.environ["SECRET"].encode(),m,hashlib.sha256).hexdigest())')

curl -s -w "\nHTTP %{http_code}\n" -X POST "http://localhost/webhook/google-sheet" \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIG" \
  -d "$BODY"
```

Ожидаемо: **200** (или ответ n8n workflow). Повтор с тем же `idempotency_key` → `{"status":"duplicate"}`.

Неверная подпись → **401**. Без ключа → **400**. Флуд (>10 r/s) → **429** от nginx.

### Runbook

#### DLQ counter растёт

1. Grafana → **Last DLQ reason** / **Last DLQ failed node** (Redis panels).
2. n8n → **Executions** → failed run → какая нода упала (часто Google Sheets ID, amoCRM token, LLM quota).
3. Исправить credential / Sheet ID / активировать workflow.
4. **Retry_runner** подхватит из `dead_letter:webhooks` по cron; или вручную re-run execution.
5. Если счётчик `dlq:webhooks:count` не совпадает с `LLEN dead_letter:webhooks` — после отладки синхронизировать в Redis CLI.

#### Gateway 502 «Upstream n8n unavailable»

1. `docker compose ps n8n gateway redis` — все healthy?
2. `docker compose logs gateway --tail 50` — `n8n forward failed`.
3. Из gateway-контейнера: `wget -qO- http://n8n:5678/healthz` (n8n жив?).
4. Workflow **Active**? URL `N8N_WEBHOOK_URL` совпадает с production path в n8n?
5. Перезапуск: `docker compose restart n8n gateway`.

#### Gateway 401 Invalid signature

- Secret в `.env` ≠ secret в Payment_bot / Retry_runner Crypto node.
- Подпись считается от **compact JSON** (`{"a":1}` без пробелов) — см. curl выше.
- Header: `X-Signature` (hex SHA256 HMAC).

#### Gateway 429

- nginx rate limit: 10 req/s per IP, burst 20. Для load test — временно поднять в `infra/nginx/nginx.conf` (`rate=30r/s`) и `docker compose restart nginx`.

#### Метрики gateway не в Grafana

```bash
docker compose exec -T gateway python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read()[:500])"
docker compose exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=up{job=\"gateway\"}'
```

Если `up=0` — перезапустить gateway и prometheus.

## Workflow 1: Telegram smoke test

Цель: проверить ручной запуск workflow и Telegram integration.

Схема:

```text
Manual Trigger -> HTTP Request -> Telegram
```

Шаги:

1. Создать Telegram-бота через `@BotFather`.
2. Получить bot token.
3. Написать боту `/start`.
4. Получить `chat_id`:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
```

5. В n8n создать Telegram credential.
6. В Telegram node указать `chat_id`.
7. Запустить workflow вручную.

Ожидаемый результат: сообщение приходит в Telegram.

## Workflow 2: Webhook -> Google Sheets

Цель: принимать webhook и записывать payload в Google Sheets.

Схема:

```text
Webhook -> Google Sheets Append Row
```

### Google Sheet

Создать таблицу с колонками:

```text
timestamp | event | amount | raw_payload
```

Можно добавить больше колонок, например:

```text
timestamp | event | order_id | amount | currency | customer_id | source | raw_payload
```

### Google Cloud setup

В Google Cloud Console:

1. Создать проект.
2. Включить API:
   - Google Sheets API
   - Google Drive API
3. Создать OAuth Client.
4. Добавить redirect URI, который показывает n8n в credential setup.
5. Если приложение в testing mode, добавить свой Google account в Test users.

При ошибке `403 Google Drive API has not been used`, нужно включить Google Drive API в том же проекте.

### n8n Google Sheets node

Использовать action-ноду, не trigger:

```text
Google Sheets -> Append Row
```

Не использовать `Google Sheets Trigger` для этого workflow.

Настройки:

```text
Resource: Sheet Within Document
Operation: Append Row
Document: By URL
Sheet: Sheet1
Mapping Column Mode: Map Each Column Manually
```

Маппинг для 4 колонок:

```text
timestamp   = {{ String($json.body.timestamp || $now) }}
event       = {{ String($json.body.event) }}
amount      = {{ Number($json.body.amount) }}
raw_payload = {{ JSON.stringify($json.body) }}
```

Если Google Sheets интерпретирует JSON как формулу, можно писать `raw_payload` как текст:

```text
raw_payload = {{ "'" + JSON.stringify($json.body) }}
```

### Test URL

Для test webhook:

1. Нажать `Execute workflow` или `Listen for test event`.
2. Отправить запрос:

```bash
curl -X POST "http://localhost/webhook-test/google-sheet" \
  -H "Content-Type: application/json" \
  -d '{"event":"payment_succeeded","amount":100}'
```

Test URL работает только один раз после запуска ожидания test event.

### Production URL

После `Publish` использовать production URL:

```bash
curl -X POST "http://localhost/webhook/google-sheet" \
  -H "Content-Type: application/json" \
  -d '{"event":"payment_succeeded","amount":100}'
```

Ожидаемый результат: новая строка появляется в Google Sheet.

## Workflow 3: Schedule -> HTTP Request

Цель: проверить polling/schedule workflow.

Схема:

```text
Schedule Trigger -> HTTP Request
```

Настройки:

```text
Schedule Trigger: every 5 minutes
HTTP Request: GET https://httpbin.org/get
```

После `Publish` workflow должен запускаться автоматически по расписанию.

## Workflow 4: Payment provider simulator

Цель: автоматически генерировать payment-события, подписывать HMAC и отправлять в webhook.

Актуальное имя workflow:

```text
Payment_bot_menu
```

Схема:

```text
Schedule Trigger -> Code -> Crypto -> HTTP Request
```

### Schedule Trigger

Для теста:

```text
Every Minute
```

Позже можно поставить:

```text
Every 5 Minutes
```

### Code node

Language:

```text
JavaScript
```

Mode:

```text
Run Once for All Items
```

Код:

```javascript
const amount = Math.floor(Math.random() * 9900) + 100;
const orderId = `ord_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
const customerId = `cus_${Math.floor(Math.random() * 10000)}`;

const payload = {
  event: "payment_succeeded",
  idempotency_key: orderId,
  order_id: orderId,
  amount,
  currency: "RUB",
  customer_id: customerId,
  timestamp: new Date().toISOString(),
  source: "n8n_payment_simulator",
};

return [
  {
    json: {
      payload,
      raw_body: JSON.stringify(payload),
    },
  },
];
```

Python mode в текущем Docker-образе не используется, потому что контейнер n8n сообщает:

```text
Python runner unavailable: Python 3 is missing from this system
```

### Crypto node

Назначение: посчитать HMAC SHA256 от payload.

Настройки:

```text
Operation: HMAC
Algorithm: SHA256
Value/Data: {{ $json.raw_body }}
Secret/Key: super_test_secret_123
Encoding: Hex
```

Результат подписи n8n кладёт в поле:

```text
{{ $json.data }}
```

### HTTP Request node

Настройки:

```text
Method: POST
URL: http://gateway:8000/webhook/google-sheet
Authentication: None
Send Body: true
Body Content Type: JSON
Specify Body: Using JSON
JSON Body: {{ $json.payload }}
```

Headers:

```json
{
  "X-Signature": "{{ $json.data }}"
}
```

Важно: не использовать `Using Fields Below` с пустым `Name`, иначе payload уйдёт как:

```json
{
  "": {
    "event": "payment_succeeded"
  }
}
```

Правильный body должен быть:

```json
{
  "event": "payment_succeeded",
  "order_id": "ord_...",
  "amount": 1234,
  "currency": "RUB",
  "customer_id": "cus_...",
  "timestamp": "2026-...",
  "source": "n8n_payment_simulator"
}
```

### Проверка

1. Запустить simulator workflow вручную.
2. Проверить, что HTTP Request node зелёный.
3. Проверить, что новая строка появилась в Google Sheet.
4. Нажать `Publish`.
5. Убедиться, что строки появляются автоматически по расписанию.

## Актуальный workflow: Google Sheet

`Google Sheet` — основной workflow, который принимает webhook и решает, можно ли писать событие в таблицу.

Актуальная схема (после gateway — **без** Crypto/IF подписи в workflow):

```text
Webhook
-> Edit Fields
-> Redis idempotency INCR + TTL
-> IF idempotency count == 1
-> Build Dedup Fingerprint
-> Redis dedup INCR + TTL 60s
-> IF dedup count == 1
-> LLM HTTP Request (OpenRouter / OpenAI-compatible)
-> Extract AI Answer
-> Google Sheets Append Row
-> Telegram Send Message
-> Code Http to AmoCRM (POST /api/v4/leads)

Любая из downstream-нод при ошибке:
-> Build DLQ Record
-> Redis dead_letter:webhooks
```

> **HMAC и idempotency на ingress** — в FastAPI gateway (см. раздел «Ключевая идея»). В workflow `Google Sheet` ноды Crypto + IF подписи **убраны** — иначе дублирование и ломается цепочка (IF с `$json.data` без Crypto на входе).

### Webhook node

```text
Method: POST
Path: google-sheet
Production URL: http://localhost/webhook/google-sheet
```

Внутри Docker другие workflow (Payment_bot, Retry_runner) вызывают **gateway**, не n8n напрямую:

```text
http://gateway:8000/webhook/google-sheet
```

### Проверка подписи — только в gateway

Раньше в workflow стояли Crypto + IF (`$json.data` vs `x-signature`). После появления gateway это **избыточно**: подпись проверяется один раз на edge, до n8n доходят только валидные события.

Если IF подписи оставить — цепочка часто останавливается на False (нет `$json.data` от Crypto или потеряны headers).

**Не добавляй** Crypto/IF подписи в новые workflow — только в gateway (`WEBHOOK_HMAC_SECRET`).

### Idempotency (в workflow — второй слой, опционально)

После валидной подписи workflow проверяет `idempotency_key` через Redis.

Redis key:

```text
idempotency:{{ $json.body.idempotency_key }}
```

Операция:

```text
INCR
```

TTL:

```text
86400
```

Redis возвращает объект с динамическим ключом, например:

```json
{
  "idempotency:ord_1779111308071_324": 1
}
```

Поэтому IF после Redis проверяет первое значение объекта:

```text
Value 1: {{ Object.values($json)[0] }}
Operation: is equal to
Value 2: 1
```

Логика:

```text
1  -> первое событие, можно продолжать
2+ -> дубль, не писать в Google Sheets
```

### Dedup 60 секунд

Dedup защищает от похожих событий с разными `idempotency_key`.

Fingerprint строится через `Edit Fields` / `Build Dedup Fingerprint`:

```text
{{ 'dedup:' + $('Edit Fields').item.json.body.event + ':' + $('Edit Fields').item.json.body.amount + ':' + $('Edit Fields').item.json.body.customer_id + ':' + $('Edit Fields').item.json.body.currency }}
```

Redis dedup:

```text
Operation: INCR
Key: {{ $json.dedup_key }}
TTL: 60
```

IF после Redis dedup:

```text
Value 1: {{ Object.values($json)[0] }}
Operation: is equal to
Value 2: 1
```

Первое похожее событие за 60 секунд проходит, следующие похожие события блокируются.

### Dead-letter на реальных ошибках

DLQ срабатывает, когда падает любая downstream-нода:

```text
LLM Request Promt
Append row in sheet
Send a text message
Http to AmoCRM
```

У каждой из них:

```text
On Error: Continue (using error output)
```

Error output ведёт в:

```text
Build DLQ Record
  ├─> Redis SET dlq:webhooks:last_failed_node
  ├─> Redis SET dlq:webhooks:last_reason
  └─> Redis DLQ Push -> dead_letter:webhooks
```

Все три Redis-ноды подключены **параллельно** от `Build DLQ Record` (один output → три ноды).

**Redis SET `last_failed_node`**
- Operation: Set
- Key: `dlq:webhooks:last_failed_node`
- Value: `={{ $json.failed_node }}`

**Redis SET `last_reason`**
- Operation: Set
- Key: `dlq:webhooks:last_reason`
- Value: `={{ ($json.reason || 'unknown').slice(0, 240) }}`

**Redis DLQ Push** — без изменений, `$json` тот же DLQ record.

Grafana читает ключи через datasource **Redis** (панели «Last DLQ failed node» / «Last DLQ reason»).

Dead-letter payload:

```javascript
{
  payload: $('Edit Fields').item.json.body,
  reason: $json.error.message,      // например ECONNRESET от Google Sheets
  failed_at: new Date().toISOString(),
  attempt: 1,
  failed_node: 'Append row in sheet' // какая нода упала
}
```

Старый IF `Simulate Failure` (amount > 9000) **отключён** — retry привязан к реальным ошибкам downstream-нод.

Типичные реальные причины попадания в DLQ:

- `ECONNRESET` / timeout от Google Sheets API;
- 429 / 5xx от LLM API;
- ошибка Telegram или amoCRM.

### Google Sheets mapping

Так как Redis-ноды меняют текущий `$json`, Google Sheets берёт данные из сохранённой ноды `Edit Fields`:

```text
timestamp   = {{ String($('Edit Fields').item.json.body.timestamp || $now) }}
event       = {{ String($('Edit Fields').item.json.body.event) }}
amount      = {{ Number($('Edit Fields').item.json.body.amount) }}
raw_payload = {{ JSON.stringify($('Edit Fields').item.json.body) }}
```

### LLM-анализ и Telegram (неделя 9)

После dedup, **до** Google Sheets:

1. **HTTP Request** (`LLM Request Promt`) — POST в OpenAI-compatible API (например OpenRouter).
2. **Edit Fields / Set** (`Extract AI Answer`) — вытащить текст:

```text
ai_answer = {{ $json.choices[0].message.content }}
```

3. **Telegram** — текст сообщения ссылается на AI-ответ и payload:

```text
{{ $('Extract AI Answer').item.json.ai_answer }}
```

В prompt для LLM использовать сохранённый payload, а не текущий `$json` после Redis:

```text
{{ JSON.stringify($('Edit Fields').item.json.body) }}
```

Отдельный workflow `LLM_payment_analysis_test` (Manual → LLM → Telegram) — для отладки промптов; боевой путь — внутри `Google Sheet`.

### amoCRM: создание лида (Code node)

После Telegram в том же workflow стоит **Code**-нода (например `Http to AmoCRM`). Она создаёт сделку в воронке **«ВХОДЯЩИЕ С N8N»** через REST API v4.

Почему Code, а не HTTP Request node: на Raw/JSON body n8n иногда отправлял `price` как строку `"=5000"`; `this.helpers.httpRequest` с объектом `payload` отдаёт корректный JSON.

**Sandbox-аккаунт:**

```text
Subdomain: greenbeesy.amocrm.ru
Pipeline ID: 10930290
```

**Токен:** долгосрочный JWT из amoМаркет → интеграция → «Ключи и доступы». Хранить только в n8n (Code или Header Auth credential), **не** коммитить в git и не отправлять в чаты.

Пример кода ноды:

```javascript
const body = $('Edit Fields').item.json.body;

const token = 'Bearer <AMO_LONG_LIVED_TOKEN>';

const payload = [{
  name: `Платёж ${body.customer_id} — ${body.amount} ${body.currency || 'RUB'}`,
  price: parseInt(body.amount, 10),
  pipeline_id: 10930290,
}];

const response = await this.helpers.httpRequest({
  method: 'POST',
  url: 'https://greenbeesy.amocrm.ru/api/v4/leads',
  headers: {
    Authorization: token,
    'Content-Type': 'application/json',
  },
  body: payload,
  json: true,
});

return [{
  json: {
    ok: true,
    lead_id: response._embedded.leads[0].id,
  },
}];
```

`$('Edit Fields')` доступен из любой downstream-ноды в том же execution workflow.

**Проверка end-to-end:**

1. `Google Sheet` → **Publish**.
2. `Payment_bot_menu` → **Publish** (или Execute вручную).
3. Сгенерировать событие с `amount <= 9000`.
4. Ожидать: строка в Google Sheets, сообщение в Telegram с AI-текстом, новая сделка в amoCRM (колонка «ПЕРВИЧНЫЙ КОНТАКТ»).

`Payment_bot_menu` **не** вызывает amo напрямую — только подписанный POST в `/webhook/google-sheet`.

## Актуальный workflow: Amo_lead_test

Отдельный workflow для первого знакомства с API amoCRM без HMAC/Redis.

```text
Manual Trigger
-> Code (тестовые name, amount)
-> Code Build amo body (JSON.stringify, price как int)
-> Code httpRequest POST /api/v4/leads
```

Либо укороченный вариант: одна Code-нода с `httpRequest`, как в примере выше.

Успешный ответ:

```json
{
  "ok": true,
  "lead_id": 34696397
}
```

После отладки основной путь — только внутри `Google Sheet`.

## Актуальный workflow: Bitrix_Lead_test

Отдельный workflow для интеграции с Bitrix24. В `Google Sheet` используется amoCRM.

### Установка community-ноды

1. n8n → **Settings** → **Community nodes** → Install (например `n8n-nodes-bitrix`).
2. `docker compose restart n8n` в `infra/`.

### Credential (OAuth2)

1. Bitrix24 → **Разработчикам** → **Локальное приложение** → «Использует только API», права **CRM**.
2. Redirect URI в приложении (как в n8n credential):

```text
http://localhost/rest/oauth2-credential/callback
```

3. n8n → credential **Bitrix OAuth2 API**:
   - **Portal Domain:** `b24-xxxxx.bitrix24.ru` (без `https://` и без `/rest/...`)
   - **Client ID / Secret** — из локального приложения Bitrix (не Google OAuth).
4. **Connect to Bitrix** → разрешить доступ → Save.

Альтернатива без OAuth: **входящий webhook** Bitrix (`/rest/1/ключ/`) + Code/`httpRequest` — см. troubleshooting.

### Нода Bitrix в workflow

```text
Manual Trigger -> Bitrix24 (Create -> Lead)
```

| Поле | Значение |
|------|----------|
| Resource | **Lead** (не Company) |
| Operation | Create |
| TITLE | `Тест из n8n` |
| OPPORTUNITY | `5000` |
| CURRENCY_ID | `RUB` |

Успешный ответ Bitrix REST:

```json
{
  "result": 2,
  "time": { "duration": 0.97, ... }
}
```

`result` — ID созданного лида. Проверка: Bitrix24 → **CRM → Лиды**.

### Сравнение amo vs Bitrix в проекте

| | amoCRM | Bitrix24 |
|---|--------|----------|
| Где в проекте | `Google Sheet` (после Telegram) | `Bitrix_Lead_test`, `Agent_Router_Filter` |
| Auth | JWT / Bearer в Code | OAuth2 (community node) |
| API | `POST /api/v4/leads` | `crm.lead.add` через ноду |
| n8n | Code + `httpRequest` | Bitrix24 node |

## Актуальный workflow: Agent_Router_Filter

**Agent-router** — маршрутизатор **намерений** (intent), а не фильтр в смысле «отбросить запрос». Один текст → LLM решает сценарий → разные ветки.

```text
Manual Trigger (позже Telegram Trigger)
  -> Code (user_text, chat_id)
  -> HTTP Request (LLM classify, JSON intent)
  -> Parse intent (Code)
  -> If
      true  (create_lead)  -> Bitrix24 Lead -> Telegram
      false -> LLM Answer / уточнение
```

| Intent | Действие |
|--------|----------|
| `create_lead` | лид в Bitrix24 |
| `answer_question` | ответ LLM → Telegram |
| `need_clarification` | просьба уточнить |

**Частые ошибки IF/Switch:** лишний пробел в `{{ $json.intent }}`; `create_lead` с fx ON; Bitrix не сохранён в connections после перетаскивания провода.

Проверка connections в БД:

```bash
cd infra
docker compose exec -T postgres psql -U n8n -d n8n -c \
  "SELECT jsonb_pretty(connections) FROM workflow_entity WHERE name = 'Agent_Router_Filter';"
```

## Актуальный workflow: Retry_runner

`Retry_runner` достаёт события из Redis dead-letter list и пробует отправить их обратно в `Google Sheet`.

Схема:

```text
Schedule Trigger
-> Redis Pop dead_letter:webhooks
-> IF DLQ not empty
-> Prepare DLQ Retry
-> IF retry allowed (attempt <= 3)
   true  -> Crypto HMAC -> HTTP Request /webhook/google-sheet
   false -> Redis final_failed:webhooks
```

### Redis Pop

Redis action:

```text
Pop data from a Redis list
```

List/key:

```text
dead_letter:webhooks
```

В текущей версии n8n Redis Pop возвращает объект в поле:

```text
propertyName
```

Пример:

```json
{
  "propertyName": {
    "payload": {
      "event": "payment_succeeded",
      "amount": 2528
    },
    "reason": "The connection to the server was closed unexpectedly...",
    "failed_at": "2026-05-21T12:12:47.063+03:00",
    "attempt": 1,
    "failed_node": "Append row in sheet"
  }
}
```

### Prepare DLQ Retry (Code node)

Код помечает событие как retry из DLQ и сохраняет исходный payload без изменений.

```javascript
const deadLetter = $json.propertyName;

if (!deadLetter || !deadLetter.payload) {
  return [];
}

const payload = { ...deadLetter.payload };
const attempt = (deadLetter.attempt || 1) + 1;

payload.retry_from_dlq = true;
payload.retry_attempt = attempt;
payload.original_failure_reason = deadLetter.reason;
payload.original_failed_at = deadLetter.failed_at;

if (deadLetter.failed_node) {
  payload.original_failed_node = deadLetter.failed_node;
}

// Retry не должен блокироваться idempotency от первой попытки
payload.idempotency_key = `${payload.idempotency_key}:retry:${attempt}`;
payload.order_id = `${payload.order_id}:retry:${attempt}`;

return [
  {
    json: {
      payload,
      attempt,
      original_reason: deadLetter.reason,
      failed_at: deadLetter.failed_at,
    },
  },
];
```

Важно: изменение `idempotency_key` для retry — практичный обход текущей схемы idempotency. В production лучше хранить статусы `processing / failed / processed`, чтобы failed-событие не считалось окончательно обработанным.

### Max attempts

После Code стоит IF:

```text
{{ Number($json.attempt) }}
is less than or equal to
3
```

- `true` → Crypto → HTTP Request (повторная отправка в webhook);
- `false` → Redis Push в `final_failed:webhooks` (ручной разбор).

### Crypto node

Retry payload нужно подписать заново, потому что Code меняет тело запроса.

```text
Operation: HMAC
Algorithm: SHA256
Value/Data: {{ JSON.stringify($json.payload) }}
Secret/Key: super_test_secret_123
Encoding: Hex
```

### HTTP Request node

```text
Method: POST
URL: http://gateway:8000/webhook/google-sheet
Send Body: true
Body Content Type: JSON
Specify Body: Using JSON
JSON Body: {{ $json.payload }}
```

Headers:

```json
{
  "X-Signature": "{{ $json.data }}"
}
```

### Проверка DLQ retry

1. Опубликовать `Google Sheet` и `Retry_runner`.
2. Запустить `Payment_bot_menu` и дождаться реальной ошибки downstream-ноды (например `ECONNRESET` от Google Sheets) **или** временно сломать credential/URL одной из нод.
3. Проверить DLQ:

```bash
cd infra
docker compose exec -T redis redis-cli LLEN dead_letter:webhooks
docker compose exec -T redis redis-cli LRANGE dead_letter:webhooks 0 0
```

4. Дождаться `Retry_runner` (или запустить вручную).
5. Проверить, что в Google Sheets появилась строка с маркерами:

```json
{
  "retry_from_dlq": true,
  "retry_attempt": 2,
  "original_failure_reason": "The connection to the server was closed unexpectedly...",
  "original_failed_node": "Append row in sheet"
}
```

6. Если retry не помог 3 раза — событие уходит в `final_failed:webhooks`:

```bash
docker compose exec -T redis redis-cli LLEN final_failed:webhooks
```

## Частые ошибки

### 502 Bad Gateway

Проверить, что:

```env
N8N_PORT=5678
```

и nginx проксирует:

```nginx
proxy_pass http://n8n:5678;
```

### Safari secure cookie error

Для локального HTTP:

```env
N8N_SECURE_COOKIE=false
```

### OAuth 414 URI Too Long

В nginx должны быть:

```nginx
client_header_buffer_size 16k;
large_client_header_buffers 8 32k;
```

После изменения:

```bash
docker compose restart nginx
```

### Google Sheets `403 Forbidden`

Проверить:

- включён Google Drive API;
- включён Google Sheets API;
- выбран правильный Google Cloud project;
- текущий Google account добавлен в OAuth test users;
- credential в n8n подключён заново после изменения API.

### `webhook-test` возвращает 404

Test webhook работает только после:

```text
Execute workflow
```

или:

```text
Listen for test event
```

Для постоянного URL нужно:

```text
Publish
```

и использовать:

```text
/webhook/...
```

а не:

```text
/webhook-test/...
```

### amoCRM `401 Unauthorized`

- В заголовке: `Authorization: Bearer <JWT>` (один пробел после `Bearer`).
- Токен не просрочен и не отозван в amoМаркет.
- Проверка в терминале:

```bash
curl -s -H "Authorization: Bearer <TOKEN>" \
  "https://greenbeesy.amocrm.ru/api/v4/account"
```

Ожидается HTTP `200`.

### amoCRM `400` — `price should be of type int`

Тело запроса должно быть **массивом** `[{ ... }]`, поле `price` — **число**, не строка `"5000"` и не `"=5000"`.

Рабочий обход в n8n: Code + `JSON.stringify` или `httpRequest` с `body: [{ price: parseInt(amount, 10), ... }]`.

В HTTP Request node с Raw body: Content-Type **`application/json`**, не `text/html`.

### amoCRM / n8n: `access to env vars denied`

На стенде запрещён `$env` в Code. Не использовать `$env.AMO_TOKEN` без настройки Docker:

```env
N8N_BLOCK_ENV_ACCESS_IN_NODE=false
```

Для локальной разработки допустимо хранить токен в Code (как в примере) или в **Header Auth** credential на ноде **HTTP Request** (Code-нода credential UI не показывает).

### Bitrix24 OAuth: DNS / неверный домен

- **Portal Domain** — только `b24-xxxxx.bitrix24.ru`, не полный webhook URL `/rest/1/.../`.
- **Client ID** — из локального приложения Bitrix (`local.xxx`), не Google `googleusercontent.com`.
- Redirect URI в Bitrix = `http://localhost/rest/oauth2-credential/callback` (как в n8n).
- После **Connect to Bitrix** браузер должен вернуться на `http://localhost/rest/oauth2-credential/callback?code=...` — n8n должен быть запущен.

### Bitrix24: входящий webhook (без OAuth)

```text
POST https://ПОРТАЛ.bitrix24.ru/rest/1/КЛЮЧ/crm.lead.add
```

Body (fields): `TITLE`, `OPPORTUNITY`, `CURRENCY_ID`. Удобно через Code + `this.helpers.httpRequest`, аналогично amo.

### Google Sheet показывает `#ERROR!` или `#N/A`

Проверить маппинг в Google Sheets node.

Для текстового JSON можно использовать:

```text
{{ "'" + JSON.stringify($json.body) }}
```

### В таблицу попадает JSON с пустым ключом

Если строка выглядит так:

```json
{"":{"event":"payment_succeeded"}}
```

значит HTTP Request node настроен как `Using Fields Below` с пустым `Name`.

Нужно:

```text
Specify Body: Using JSON
JSON Body: {{ $json }}
```

## Проверка queue mode

Открыть логи worker'ов:

```bash
cd infra
docker compose logs -f n8n-worker-1 n8n-worker-2 n8n-worker-3
```

В другом терминале отправить несколько webhook'ов:

```bash
for i in {1..10}; do
  curl -X POST "http://localhost/webhook/google-sheet" \
    -H "Content-Type: application/json" \
    -d "{\"event\":\"payment_succeeded\",\"amount\":$i}"
done
```

В логах должно быть видно, что executions уходят в queue и выполняются worker'ами.

## Production n8n (self-hosted): как это устроено

Этот раздел — про production-развёртывание n8n на сервере и соответствие локальному стенду в `infra/`.

### n8n Cloud vs self-hosted

| | **n8n Cloud** | **Self-hosted** (наш случай) |
|---|----------------|------------------------------|
| Где крутится | серверы n8n.io | **ваш VPS / K8s / Docker** |
| UI | `*.app.n8n.cloud` | **ваш домен** (`n8n.company.ru`) |
| Данные | у провайдера | **ваш PostgreSQL** |
| Очереди / workers | managed | **настраиваете сами** (Redis + worker) |
| Стоимость | подписка | сервер + администрирование |

В вакансиях «n8n + интеграции» чаще имеют в виду **self-hosted** или cloud с теми же паттернами (webhook, credentials, Publish).

### Как открывается UI

n8n — **веб-приложение** (frontend + API). В браузере ты работаешь с **редактором workflow**; выполнение уходит в backend.

```text
Браузер  https://n8n.company.ru
    |
    v
nginx (TLS, basic auth, лимиты)
    |
    v
n8n main :5678   ← UI, REST API, приём webhook
    |
    +-- PostgreSQL  (workflow, credentials, executions)
    +-- Redis       (очередь jobs, если queue mode)
          |
          +-- n8n-worker × N   (выполнение workflow)
```

**Локально у нас то же самое**, только `https` заменён на `http://localhost` и nginx на порту 80 (`infra/nginx/`).

Важные переменные (`infra/.env`):

| Переменная | Зачем |
|------------|--------|
| `N8N_EDITOR_BASE_URL` | URL редактора в браузере (`http://localhost/` или `https://n8n.company.ru/`) |
| `WEBHOOK_URL` | базовый URL **production** webhook'ов для внешних систем |
| `N8N_HOST` / `N8N_PROTOCOL` | как n8n строит ссылки |
| `N8N_PROXY_HOPS=1` | n8n за reverse proxy (nginx) |
| `N8N_SECURE_COOKIE=true` | в проде с HTTPS обязательно |
| `N8N_ENCRYPTION_KEY` | шифрование credentials в БД (в проде **обязательно** задать и не менять) |

Без правильного `WEBHOOK_URL` после **Publish** внешние системы получат неверный адрес (`localhost` вместо публичного домена).

### Развёртывание на сервере (типовой VPS)

1. **Сервер:** Ubuntu 22.04+, 2–4 GB RAM для стартовой конфигурации; под нагрузкой — больше RAM и отдельные worker'ы.
2. **Docker Compose** — как в `infra/docker-compose.yml` (postgres + redis + n8n + workers + nginx).
3. **Домен:** `A`-запись на IP сервера.
4. **nginx + Let's Encrypt** (certbot) — HTTPS на 443.
5. **`.env` продакшена:**

```env
N8N_HOST=n8n.company.ru
N8N_PROTOCOL=https
N8N_EDITOR_BASE_URL=https://n8n.company.ru/
WEBHOOK_URL=https://n8n.company.ru/
N8N_SECURE_COOKIE=true
N8N_ENCRYPTION_KEY=<openssl rand -hex 32>
```

6. **Доступ к UI:** basic auth на nginx и/или встроенная авторизация n8n; VPN или IP allowlist для внутренних инсталляций.
7. **Firewall:** снаружи открыты 80/443; порты Postgres/Redis **не** торчат в интернет.

Альтернатива Compose — **Kubernetes** (Helm chart n8n): те же роли (main, worker, postgres, redis), но оркестрация через K8s. Паттерны те же.

### Роли контейнеров (queue mode)

Уже включено в нашем `docker-compose.yml`:

| Роль | Что делает |
|------|------------|
| **n8n main** | UI, API, регистрация webhook, постановка job в Redis |
| **n8n worker** | выполняет workflow (можно `docker compose scale n8n-worker-1=5`) |
| **PostgreSQL** | единственный source of truth: workflow, executions, users, credentials |
| **Redis** | очередь Bull для executions |
| **nginx** | единая входная точка, TLS, auth |

Зачем workers: долгие workflow (LLM, HTTP, CRM) не блокируют приём новых webhook'ов.

### Workflow: от разработки до production

| Этап | Где | Что происходит |
|------|-----|----------------|
| Разработка | UI на dev-стенде | Manual test, `webhook-test`, черновики |
| **Publish** / Active | тот же или prod-стенд | production webhook URL, schedule/cron активны |
| Выполнение | workers | executions пишутся в Postgres |

**Test vs Production webhook:**

```text
/webhook-test/...   — пока слушаешь в UI (Execute workflow)
/webhook/...        — после Publish, постоянный URL для провайдеров
```

Workflow в нашем репозитории **не в git** по умолчанию — они в `workflow_entity` в Postgres. Для продакшена обычно:

- экспорт JSON из UI или API;
- или [n8n source control](https://docs.n8n.io/source-control-environments/) (Enterprise);
- или CI, который деплоит workflow на staging/prod.

### Credentials и секреты

| Что | Где хранится | Практика |
|-----|--------------|----------|
| OAuth токены, API keys | Postgres (зашифровано `N8N_ENCRYPTION_KEY`) | не в теле workflow |
| Пароли интеграций | n8n Credentials UI | не в Code node строкой |
| `infra/.env` | сервер | не в git |

**Антипаттерн:** Bearer token в JSON HTTP Request node (попадает в экспорт и бэкапы БД). Использовать **Credentials**.

### Надёжность (что уже есть в проекте vs prod)

| Паттерн | В `webhook-shield` | В проде часто добавляют |
|---------|-------------------|-------------------------|
| HMAC webhook | ✅ gateway (edge) | не дублировать Crypto/IF в каждом workflow |
| Idempotency / dedup | ✅ Redis | защита от дублей провайдера |
| DLQ + retry | ✅ `Retry_runner` | алерты + ручной разбор |
| Queue mode | ✅ | масштабирование workers |
| Мониторинг | ✅ Prometheus, Grafana, Loki, алерты (Telegram в UI) | дашборды под SLA |
| Бэкапы Postgres | ⬜ | pg_dump / managed DB |
| Rate limit на nginx | ✅ 10 r/s на `/webhook/` | защита от флуда |

### Обновления и откат

- Образ `n8nio/n8n:latest` — для прода лучше **фиксировать тег** (`n8n@1.xx.x`), не `latest`.
- Перед обновлением: бэкап Postgres + volume `n8n_data`.
- Worker'ы и main должны быть **одной версии** n8n.

### Как это рассказывать на собесе

> «Поднимал self-hosted n8n в Docker: nginx как reverse proxy, PostgreSQL вместо SQLite, queue mode с Redis и отдельными worker'ами для выполнения. UI доступен по домену с HTTPS, production webhook'и отдают наружу через `WEBHOOK_URL`. Workflow публикуются после проверки; секреты — в credentials, не в коде нод.»

### Связь с `webhook-shield`

Целевая prod-схема проекта:

```text
Внешний провайдер / Payment_bot / Retry_runner
    -> nginx
    -> FastAPI gateway (HMAC, idempotency)
    -> n8n workflow (Sheets, LLM, CRM, agent-router — без security-нод на входе)
    -> алерты / DLQ при сбоях
```

Локальный стенд (`infra/`) — та же архитектура на `localhost` для разработки и демонстрации.

---

## Что не коммитить

Не добавлять в GitHub:

- `infra/.env`
- `infra/.htpasswd`
- Telegram bot token
- Google OAuth client secret
- экспортированные n8n credentials
- любые реальные пользовательские данные

Проверить перед коммитом:

```bash
git status
git diff
```

## Что можно коммитить

- `README.md`
- `gateway/` — исходный код FastAPI ingress
- `infra/docker-compose.yml`
- `infra/nginx/`
- `infra/observability/`
- `infra/.env.example`
- `infra/.htpasswd.example`

## Roadmap (идеи для развития)

- Telegram Trigger в `Agent_Router_Filter` (диалог вместо Manual)
- Экспорт workflow в git
- Contact point Telegram в Grafana для алертов
