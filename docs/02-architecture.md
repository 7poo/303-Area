# 2. Kiến trúc hệ thống

## Luồng dữ liệu

```text
CSV Shopee
   │
   ▼
ETL / Validation / Deduplication
   │
   ▼
DuckDB warehouse
   │
   ├── Product matching
   ├── Market signals / alerts
   └── Recommendation engine
             │
             ▼
      Agent tools (read-only)
             │
             ▼
      DeepSeek route harness
             │
             ▼
      Agent API / UI
```

## Thành phần

### Data foundation

`src/etl.py` đọc file theo partition `country_code`, `dataset`, `shop_id`, chuẩn
hóa dữ liệu và nạp DuckDB. Data nguồn được mount read-only; database được ghi
ra `warehouse/`.

### Market signals / feature builder

Tạo các biến phục vụ phân tích:

- `price_gap_pct`: chênh lệch giá so với peer median.
- `discount_gap`: chênh lệch discount so với peer median.
- `sales_momentum`: thay đổi `monthly_sold_value`.
- `engagement_momentum`: thay đổi rating count/lượt thích.
- `competitor_pressure`: số đối thủ đang giảm giá hoặc tăng promotion.

Các biến sức bán và tương tác là proxy marketplace, không phải doanh số kế
toán.

### Product matching

Matching nên dùng hai tầng:

1. Lọc theo quốc gia, top-level category và điều kiện sản phẩm.
2. Xếp hạng bằng tên chuẩn hóa, embedding, brand, quy cách và khoảng giá.

Kết quả match phải lưu lại score, model version và nguồn tạo match để có thể
kiểm tra hoặc sửa thủ công.

### Market event detector

`src/signals.py` dùng `product_matches` để tạo `peer_groups`, aggregate timeline
`market_signals` và sinh `competitor_alerts`. Mọi signal giữ country/currency
riêng, có confidence/evidence; giá outlier được đánh dấu thay vì xóa.

`promotion_events` được tạo từ chênh lệch giữa các snapshot liên tiếp. Các event hiện có:

- `price_changed`
- `discount_changed`
- `promotion_changed`
- `voucher_changed`

### Recommendation engine

`src/recommendations.py` dùng rule/scorecard versioned, nhận cost và minimum
margin tùy chọn, tính price floor rồi sinh recommendation card có evidence.
Thiếu cost sẽ chuyển hành động thay đổi giá/voucher sang
`needs_cost_validation`. LLM chỉ giải thích kết quả và trả lời câu hỏi trên
dữ liệu đã tính; không tự sinh số liệu hoặc tự thay đổi giá.

### Agent layer

src/agent.py điều phối context, memory, route policy, tool budget và answer
validation. src/agent_tools.py chỉ expose read-only queries đã allow-list;
DeepSeek không được truy cập DuckDB trực tiếp. pipeline_runs là publication
manifest: agent chỉ đọc stage có run mới nhất ở trạng thái success, tránh đọc
output đang bị batch drop/recreate.

src/agent_server.py là HTTP server cho development; production cần đặt auth,
tenant scope, rate limit và audit middleware trước khi public.

## Đề xuất công nghệ

- Storage: DuckDB cho MVP.
- ETL: Python, `csv`, DuckDB SQL.
- Matching: sentence-transformers hoặc model embedding đa ngôn ngữ.
- API: HTTP wrapper hiện tại cho development; chuyển FastAPI/ASGI khi hardening production.
- Demo UI: Streamlit hoặc React.
- Vector index: FAISS/Chroma khi cần lưu embedding.
- Container: Docker Compose.
