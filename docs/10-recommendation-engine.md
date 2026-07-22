# Giai đoạn 4 — Recommendation Engine

## Mục tiêu

Biến `market_signals` thành recommendation card có thể kiểm tra: hành động,
giá/voucher đề xuất, giá sàn, constraint, lý do và bằng chứng. Đây là rule
engine deterministic, không dùng causal wording và không tự động thay đổi giá.

## Contract

Bảng `recommendations` có một dòng cho mỗi source SKU ở snapshot mới nhất:

- `recommendation_status`: `recommended`, `needs_cost_validation`,
  `constraint_blocked`, hoặc `insufficient_evidence`.
- `action`: `hold_price`, `reduce_price`, `use_voucher`, `no_response`.
- `recommended_price` / `recommended_discount_percent` và
  `market_reference_price`.
- `cost_value`, `margin_min_pct`, `price_floor`, `estimated_margin_pct`.
- `reason_codes`, `recommendation_text`, `evidence`, `rule_version`.

## Input giá vốn

Giá vốn là CSV tùy chọn, cùng đơn vị tiền tệ với `products`:

```csv
country_code,shop_id,item_id,cost_value,margin_min_pct
vn,123456,987654321,45000,15
```

Nếu không có giá vốn, engine không phát hành hành động giảm giá/voucher; nó
chuyển thành `needs_cost_validation` và giữ giá hiện tại. Điều này tránh đề
xuất phá margin ngoài ý muốn.

## Rule v0.1

1. Không có peer, outlier hoặc thiếu market median → `insufficient_evidence` /
   `no_response`.
2. `price_gap_pct >= 10` → cân nhắc `reduce_price` về peer median nếu median
   vẫn cao hơn `price_floor`; ngược lại `constraint_blocked`.
3. `discount_gap_pct <= -10` → cân nhắc `use_voucher`, discount được cap để net
   price không thấp hơn `price_floor`.
4. Pressure `>= 0.55` hoặc peer vừa bắt đầu promotion → cân nhắc voucher trong
   cùng constraint.
5. Không có tín hiệu mạnh → `hold_price` và tiếp tục theo dõi.

`price_floor = cost_value * (1 + margin_min_pct / 100)`. Giá đề xuất được làm
tròn theo 100 đơn vị tiền tệ bản địa. `estimated_margin_pct` chỉ là phép tính
kiểm tra constraint, không phải dự báo lợi nhuận.

## Chạy

Sau Market Signals:

```powershell
docker compose run --rm recommendation-engine
```

Với cost file:

```powershell
python -m src.recommendations `
  --db-path ./warehouse/market.duckdb `
  --cost-file ./validation/cost_inputs.csv
```

Output thêm `warehouse/recommendations_review.csv` gồm 20 card để nghiệp vụ
duyệt action, lý do và mức phù hợp trước khi xây API/UI.

## Tiêu chí nghiệm thu

- Mọi SKU latest có một card hoặc `insufficient_evidence`.
- Không recommendation có giá/discount net dưới price floor khi đã có cost.
- Recommendation chứa evidence truy được về `market_signals`.
- Rule version và constraint status được lưu đầy đủ.
- Có review set 20 card và unit tests cho abstention, margin floor, voucher cap.
