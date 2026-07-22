# Giai đoạn 3 — Market Signals

## Mục tiêu

Chuyển kết quả `product_matches` thành các tín hiệu có thể giải thích cho một
SKU theo từng ngày: vị trí giá, discount, mức hoạt động của peer, momentum và
áp lực cạnh tranh. Tín hiệu là quan sát mô tả thị trường; không được diễn giải
thành tác động nhân quả hay lợi nhuận khi chưa có order log, giá vốn và tồn kho.

## Pipeline

```text
product_matches + products + promotion_events
        │
        ├── peer_groups          (peer hợp lệ / not_enough_evidence)
        ├── market_signals       (giá, discount, sales/engagement momentum)
        ├── competitor_alerts    (ngưỡng + evidence JSON + peer định danh)
        └── market_signals_review.csv (20 dòng mẫu để nghiệp vụ gán nhãn)
```

### 1. Peer group

- Chỉ nhận `same_product`, `substitute`, `near_match` với `source_status =
  matchable` và `match_score >= 0.45`.
- Candidate vẫn phải cùng `country_code`, cùng category và khác shop vì các
  điều kiện đã được áp dụng ở Giai đoạn 2.
- Mỗi SKU không có peer tốt được ghi một dòng `not_enough_evidence`; không
  suy đoán peer từ khác quốc gia hoặc `not_comparable`.

### 2. Market signals

`market_signals` được tính cho tất cả snapshot của source SKU, nhưng peer group
lấy từ lần matching mới nhất. Các trường chính:

- `price_index = source_price / peer_median_price` và `price_gap_pct`.
- `discount_gap_pct = source_discount - peer_median_discount` (đơn vị điểm %).
- `source_sales_momentum_pct` và `peer_sales_momentum_pct` dựa trên thay đổi
  `monthly_sold_value` giữa hai snapshot liền kề.
- `source_engagement_momentum_pct` và `peer_engagement_momentum_pct` dùng proxy
  `rating_count + liked_count`.
- `price_down_peer_count`, `promotion_peer_count` lấy từ `promotion_events`.
- `competitive_pressure_score` (0–1) kết hợp price gap, tỷ lệ peer giảm giá,
  tỷ lệ peer bắt đầu promotion và peer sales momentum.
- `is_price_outlier` được bật khi `price_index < 0.25` hoặc `> 4.0`; dòng vẫn
  được giữ để audit và không bị âm thầm xóa.
- `signal_confidence`: high khi có ít nhất 3 peer, medium khi có 1–2 peer,
  low khi không có peer.

Giá trị chỉ được aggregate trong cùng quốc gia/currency; không quy đổi VND sang
IDR. Null được giữ nguyên khi thiếu evidence.

### 3. Alert rules v0.1

| Alert | Điều kiện |
|---|---|
| `our_price_above_market` | `price_gap_pct >= 10` |
| `our_discount_below_market` | `discount_gap_pct <= -10` |
| `competitor_price_down` | Có peer giảm giá trong ngày |
| `competitor_promotion_started` | Có peer đổi promotion trong ngày |
| `competitor_momentum_up` | `peer_sales_momentum_pct >= 20` |
| `high_competitive_pressure` | `competitive_pressure_score >= 0.55` |

Alert event có `target_shop_id/target_item_id` đại diện và `evidence` JSON để
truy ngược số peer, median giá, event count và model version. Alert không tự
động thay đổi giá.

## Chạy

```powershell
docker compose run --rm market-signals
```

Hoặc local:

```powershell
python -m src.signals --db-path ./warehouse/market.duckdb --min-peer-score 0.45
```

Batch này drop/recreate ba bảng Stage 3, nên chạy lại sau mỗi lần rebuild
`product_matches`. Đầu ra tổng hợp được in ra stdout để đưa vào log/monitoring;
đồng thời xuất 20 alert mẫu chưa gán nhãn tại
`warehouse/market_signals_review.csv`.

## Tiêu chí nghiệm thu

- Có peer group hoặc trạng thái `not_enough_evidence` cho mọi source SKU.
- Không có peer/currency cross-country.
- Mỗi signal có số peer, confidence, model version và evidence count.
- Mỗi alert event truy được về peer và `promotion_events` cùng ngày.
- Có timeline tối thiểu theo ba snapshot hiện có.
- Có review set tối thiểu 20 alert cho nghiệp vụ gán nhãn.
- Unit/integration tests kiểm tra peer, momentum, abstention và event traceability.
