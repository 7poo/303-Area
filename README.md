# Market Intelligence Copilot

Market Intelligence Copilot là MVP cho Đề 3 — **Market Intelligence**. Hệ thống
đọc snapshot sản phẩm Shopee, ghép các SKU tương đồng giữa các shop, theo dõi
thay đổi giá/khuyến mãi và chuẩn bị dữ liệu cho khuyến nghị cạnh tranh có giải
thích.

## Mục tiêu MVP

Với một SKU tham chiếu, người dùng có thể xem:

- Các sản phẩm đối thủ tương đồng.
- Vị trí giá và discount so với nhóm cạnh tranh.
- Đối thủ vừa thay đổi giá, promotion hoặc voucher.
- Khuyến nghị nên giữ giá, điều chỉnh giá hay dùng voucher, kèm bằng chứng.

MVP ưu tiên thị trường Việt Nam, ngành bánh kẹo/thực phẩm. Indonesia Beauty là
phạm vi mở rộng tiếp theo.

## Trạng thái hiện tại

Đã hoàn thành Ngày 1 — Data Foundation:

- ETL đọc toàn bộ CSV và chuẩn hóa dữ liệu.
- Loại 30 dòng `products` trùng theo khóa tự nhiên.
- Tạo database DuckDB tại `warehouse/market.duckdb`.
- Tạo 3.531 event thay đổi giá, discount, promotion và voucher.
- Có bảng `ingestion_quality` để kiểm tra chất lượng nạp dữ liệu.

Đã hoàn thành phần chạy tự động của Ngày 2 — Product Matching baseline:

- Chọn latest snapshot cho mỗi SKU.
- Chuẩn hóa tên, brand, product type, trọng lượng, dung tích, số lượng và bundle.
- Tạo `product_attributes`.
- Tạo candidate cùng quốc gia/category, khác shop.
- Tính hybrid score bằng TF-IDF text vector và structured features.
- Tạo `product_matches` top-K và `warehouse/matching_review.csv` gồm 100 cặp để gán nhãn thủ công.
- Initial adjudication đạt `peer_precision@1 = 1,00` và `peer_precision@5 = 0,90` trên 100 cặp.
- Multilingual semantic backend đã chạy thành công trên DB copy; tạo 503 source matchable ở threshold 0,70.

Đã hoàn thành Giai đoạn 3 — Market Signals:

- Tạo `peer_groups` với peer hợp lệ và trạng thái `not_enough_evidence`.
- Tạo timeline `market_signals` cho giá, discount, sales/engagement momentum
  và competitive pressure.
- Tạo `competitor_alerts` cho giá, promotion, momentum và áp lực cạnh tranh;
  alert event có peer định danh và evidence JSON.
- Chạy được bằng Docker và có integration test kiểm tra traceability.

Đã hoàn thành phần kỹ thuật của Giai đoạn 4 — Recommendation Engine:

- Rule engine version `recommendation-rules-v0.1` với các action giữ giá, giảm
  giá, voucher và không phản ứng.
- Nhận cost/margin tối thiểu tùy chọn, tính `price_floor` và chặn hành động
  khi thiếu cost hoặc vi phạm margin.
- Sinh bảng `recommendations` cùng evidence, reason codes, confidence và review
  set 20 card.

Đã scaffold Agent Layer — Market Intelligence Copilot:

- DeepSeek OpenAI-compatible adapter với tool-calling loop, retry/timeout và
  model config qua environment.
- Route harness, session/long-term memory, read-only market tools và trace.
- Safety gate chống prompt injection, argument validation, untrusted-data
  delimiters, secret redaction và tool/round budget.
- Production mode yêu cầu bearer token + shop scope; có publication manifest,
  audit trace và rate limiter cho HTTP wrapper.

## Chạy nhanh bằng Docker

```powershell
docker compose build
docker compose run --rm data-foundation
docker compose run --rm product-matching
docker compose run --rm market-signals
docker compose run --rm recommendation-engine
docker compose run --rm agent -- "market overview"
docker compose run --rm --service-ports agent-api
```

Database được mount ra `warehouse/market.duckdb` trên máy host.

Chạy local không cần Docker:

```powershell
python -m pip install -r requirements.txt
python -m src.etl --data-dir ./Data --db-path ./warehouse/market.duckdb --reset
```

## Cấu trúc repository

```text
Data/                  # CSV nguồn, phân vùng theo country/dataset/shop
src/etl.py             # Pipeline làm sạch và nạp DuckDB
src/matching.py        # Product matching và peer candidates
src/signals.py         # Peer groups, market signals và alerts
src/agent.py           # Agent harness, route, context và memory orchestration
src/agent_tools.py     # Read-only allow-listed tools
src/deepseek_client.py # DeepSeek API adapter
frontend/               # React + Vite + TypeScript MVP (API-only)
Dockerfile             # Image chạy ETL
docker-compose.yml     # Mount Data read-only và warehouse read-write
warehouse/             # Database sinh ra, không commit vào Git
validation/            # Nhãn kiểm định tách khỏi output model
docs/                  # Tài liệu sản phẩm, dữ liệu, kiến trúc và roadmap
```

## Tài liệu

- [Proposal — E-commerce Decision Intelligence](README_PROPOSAL.md)

- [Phạm vi sản phẩm](docs/01-product-scope.md)
- [Kiến trúc hệ thống](docs/02-architecture.md)
- [Data contract và data dictionary](docs/03-data-contract.md)
- [Roadmap và danh sách công việc](docs/04-implementation-roadmap.md)
- [Thiết kế Product Matching](docs/08-product-matching.md)
- [Thiết kế Market Signals](docs/09-market-signals.md)
- [Thiết kế Recommendation Engine](docs/10-recommendation-engine.md)
- [Kiến trúc Agent Copilot](docs/11-agent-architecture.md)
- [API v1 và Frontend MVP](docs/12-api-and-fe.md)

`requirements-embedding.txt` là dependency tùy chọn cho multilingual sentence
embedding; Docker mặc định dùng backend TF-IDF có thể tái lập ngay.
- [Kế hoạch kiểm thử và đánh giá](docs/05-evaluation.md)
- [Runbook vận hành](docs/06-runbook.md)
- [Rủi ro và giới hạn](docs/07-risks-and-limitations.md)

## Lưu ý quan trọng

Dataset có 3 ngày snapshot, không có order log, giá vốn, tồn kho thực tế hoặc
quảng cáo. Vì vậy phiên bản hiện tại là hệ thống **market intelligence và
competitive recommendation**, chưa phải bộ tối ưu causal cho lợi nhuận.
