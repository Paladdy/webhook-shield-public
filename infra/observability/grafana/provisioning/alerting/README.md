# Grafana alerting → Telegram (один раз)

1. Открой Grafana: http://localhost:3000 (логин из `.env`: `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`).
2. **Alerting → Contact points → New contact point**.
3. Name: `Telegram`
4. Integration: **Telegram**
5. Bot Token: тот же, что в n8n credential для Telegram node.
6. Chat ID: твой chat id (см. README — getUpdates).
7. **Alerting → Notification policies** — default policy → contact point `Telegram`.

Правила алертов уже provisioned из `rules.yml`:
- n8n metrics down (30s)
- queue waiting > 100 (5m)
- DLQ counter > 0 (2m)

Проверка: **Alerting → Alert rules** — должны быть в folder `webhook-shield`.
