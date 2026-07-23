# 6. Runbook vận hành

## Yêu cầu

- Docker Desktop đang chạy.
- Docker Compose v2.
- Thư mục `Data/` tồn tại ở root project.

## Build image

```powershell
docker compose build
```

## Chạy ETL và reset database

```powershell
docker compose run --rm data-foundation
```

Compose mặc định chạy với `--reset`, nên database cũ trong `warehouse/` sẽ được
tạo lại.

## Chạy Product Matching

Sau khi Data Foundation hoàn tất:

```powershell
docker compose run --rm product-matching
```

Lệnh này tạo/cập nhật:

- `product_attributes` trong DuckDB.
- `product_matches` top-10 cho mỗi SKU latest snapshot.
- `warehouse/matching_review.csv` gồm tối đa 200 cặp chưa gán nhãn.

Chạy local:

```powershell
python -m src.matching --db-path ./warehouse/market.duckdb --backend tfidf --top-k 10 --review-size 200
```

## Chạy Market Signals (Giai đoạn 3)

Sau Product Matching:

```powershell
docker compose run --rm market-signals
```

Lệnh tạo lại ba bảng:

- `peer_groups`: peer hợp lệ hoặc `not_enough_evidence` theo source SKU.
- `market_signals`: timeline giá, discount, sales/engagement momentum và áp lực
  cạnh tranh.
- `competitor_alerts`: cảnh báo có ngưỡng, evidence JSON và peer định danh cho
  event alert.
- `warehouse/market_signals_review.csv`: 20 dòng alert mẫu để nghiệp vụ gán
  `review_label`, ghi chú và annotator.

Chạy local:

```powershell
python -m src.signals --db-path ./warehouse/market.duckdb --min-peer-score 0.60
```

## Chạy Recommendation Engine (Giai đoạn 4)

Sau Market Signals:

```powershell
docker compose run --rm recommendation-engine
```

Không có cost input, engine chỉ phát hành card giữ giá hoặc yêu cầu xác nhận
giá vốn trước khi giảm giá/voucher. Khi có file giá vốn:

```powershell
python -m src.recommendations `
  --db-path ./warehouse/market.duckdb `
  --cost-file ./validation/cost_inputs.csv
```

Cost CSV cần các cột `country_code,shop_id,item_id,cost_value` và tùy chọn
`margin_min_pct`. Output là bảng `recommendations` và
`warehouse/recommendations_review.csv` (20 card chưa gán nhãn).

Để chạy thử khi chưa có giá vốn ERP, tạo kịch bản seed cho Richy:

```powershell
python -m src.seed_costs --db-path ./warehouse/market.duckdb `
  --output ./validation/cost_inputs.seeded.csv `
  --company-id richy_vietnam --margin-min-pct 15
python -m src.recommendations --db-path ./warehouse/market.duckdb `
  --cost-file ./validation/cost_inputs.seeded.csv
```

Kết quả seed luôn mang trạng thái mô phỏng, không phải khuyến nghị thực thi.

## Chạy synthetic benchmark

```powershell
python -m src.synthetic_benchmark `
  --output-dir ./synthetic/market_benchmark_v1 `
  --canonical-count 250 --sellers-per-product 3 `
  --days 120 --seed 303
```

Kiểm tra `manifest.json` trước, sau đó đọc `matching_benchmark.json`. Không nạp
các CSV có `is_synthetic=true` vào warehouse production.

## Chạy Agent API

Chạy development API ở port 8080:

```powershell
docker compose run --rm --service-ports agent-api
```

Kiểm tra:

```powershell
Invoke-RestMethod http://localhost:8080/health
Invoke-RestMethod -Uri http://localhost:8080/chat -Method Post `
  -ContentType 'application/json' `
  -Body '{"message":"đề xuất cho vn shop_id=173513432 item_id=40662233042"}'
```

Production phải đặt `AGENT_API_TOKEN`, auth/tenant isolation và rate limit;
không chạy public API khi chưa cấu hình các lớp này.

`AGENT_RATE_LIMIT` mặc định là 600 request/phút ở development để đáp ứng các
request song song của dashboard, và 60 request/phút ở production. Có thể ghi
đè biến môi trường này theo tải và chính sách triển khai thực tế.

## Chạy Frontend MVP

Sau khi các batch stage đã publish dữ liệu, chạy API và UI:

```powershell
docker compose up --build agent-api frontend
```

Mở `http://localhost:5173`; UI gọi API tại `http://localhost:8080` và không
truy cập trực tiếp DuckDB. Khi chạy local không dùng Docker:

```powershell
cd frontend
npm install
npm run dev
```

Nếu API production bật bearer token, đặt `VITE_API_TOKEN` trong
`frontend/.env.local` (không đặt DeepSeek key ở frontend).

Chuỗi chạy đầy đủ từ dữ liệu nguồn:

```powershell
docker compose run --rm data-foundation
docker compose run --rm product-matching
docker compose run --rm market-signals
docker compose run --rm recommendation-engine
```

Có thể chỉ định review output riêng khi so sánh nhiều backend:

```powershell
python -m src.matching `
  --db-path ./warehouse/semantic_market.duckdb `
  --backend sentence-transformers `
  --review-file ./warehouse/semantic_matching_review.csv
```

Backend multilingual tùy chọn yêu cầu cài thêm `sentence-transformers` và sẽ
tải model `paraphrase-multilingual-MiniLM-L12-v2` lần đầu chạy.

```powershell
python -m pip install -r requirements-embedding.txt
python -m src.matching --db-path ./warehouse/market.duckdb --backend sentence-transformers
```

## Chạy local

```powershell
python -m pip install -r requirements.txt
python -m src.etl --data-dir ./Data --db-path ./warehouse/market.duckdb --reset
```

## Kiểm tra database

Có thể dùng Python với DuckDB:

```powershell
python -c "import duckdb; c=duckdb.connect('warehouse/market.duckdb', read_only=True); print(c.sql('show tables')); print(c.sql('select * from ingestion_quality'))"
```

## Thay đổi thư mục dữ liệu/database

```powershell
docker compose run --rm `
  -e DATA_DIR=/data `
  -e DB_PATH=/warehouse/custom.duckdb `
  data-foundation
```

## Lỗi thường gặp

### Docker daemon chưa chạy

Mở Docker Desktop rồi kiểm tra:

```powershell
docker info
```

### Không tìm thấy dữ liệu

Kiểm tra `Data/` có đúng partition dạng:

```text
Data/country_code=vn/dataset=products/shop_id=.../*.csv
```

### Database bị khóa

Đảm bảo không có process khác đang mở DuckDB. Vì ETL là batch job, nên dùng:

```powershell
docker compose run --rm data-foundation
```

## Artefact không commit

`warehouse/`, `__pycache__/` và file `.pyc` đã được thêm vào `.gitignore`.
