# API v1 và Frontend MVP

## Mục tiêu

API là lớp duy nhất FE được phép dùng để đọc dữ liệu. React không mount
DuckDB, không import Python và không chứa `DEEPSEEK_API_KEY`.

## API contract

Base URL local: `http://localhost:8080`. Tất cả route dưới đây (trừ health)
nhận `Authorization: Bearer <AGENT_API_TOKEN>` khi backend chạy production.
Trong local development có thể để token trống.

`country_code` và `shop_id` là bắt buộc cho một SKU vì `item_id` không đủ để
định danh tenant. `{id}` trong URL là `item_id`.

| Method | Route | Ý nghĩa |
|---|---|---|
| GET | `/api/v1/products?country_code=vn&shop_id=...&query=...&limit=30` | Catalogue/latest snapshot |
| GET | `/api/v1/alerts?country_code=vn&shop_id=...&severity=high&limit=50` | Control-tower alert queue |
| GET | `/api/v1/recommendations?country_code=vn&shop_id=...&limit=50` | Recommendation review queue |
| GET | `/api/v1/products/{id}?country_code=vn&shop_id=...` | SKU snapshot |
| GET | `/api/v1/products/{id}/peers?...` | Peer đã matching |
| GET | `/api/v1/products/{id}/signals?...` | Market signal gần nhất |
| GET | `/api/v1/products/{id}/alerts?...` | Competitor alerts |
| GET | `/api/v1/products/{id}/recommendation?...` | Recommendation card |
| POST | `/api/v1/chat` | Copilot, body `{message,user_id?,session_id?,country_code,shop_id,item_id}` |

Response thành công dùng envelope thống nhất:

```json
{
  "ok": true,
  "data": [],
  "meta": {"count": 5, "total_count": 682, "published_run_id": "market_signals-..."}
}
```

`data` là object ở snapshot/signal/recommendation và là array ở products,
peers, alerts. Lỗi dùng `400 invalid_request`, `401 unauthorized`, `404
not_found`, `429 rate_limit_exceeded` hoặc `503 stage_not_published` /
`data_unavailable`. Mọi query đi qua allow-listed read-only registry; không
có endpoint SQL tùy ý.

## FE MVP

Chạy local:

```powershell
cd frontend
npm install
npm run dev
```

Mở `http://localhost:5173`. Có thể đặt `VITE_API_BASE_URL` và
`VITE_API_TOKEN` trong file `.env.local`; không đặt DeepSeek key ở đây.

Các vùng chính:

- **Market Overview:** country selector, catalogue, tracked SKU/discount/confidence metrics.
- **SKU 360:** offer hiện tại, price-vs-peer bars và market pressure.
- **Competitor Alerts:** alert severity, metric/threshold và evidence count.
- **Recommendation Card:** action, confidence, suggested price và constraint status.
- **Chat Copilot:** câu hỏi định lượng theo SKU, gọi `/api/v1/chat`, read-only.

Docker chạy cả hai lớp:

```powershell
docker compose up --build agent-api frontend
```

Frontend phục vụ tại `http://localhost:5173`, API tại `http://localhost:8080`.
