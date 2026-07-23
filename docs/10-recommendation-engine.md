# Giai đoạn 4 — Recommendation Engine

## Mục tiêu

Biến `market_signals` thành recommendation card có thể kiểm tra: hành động,
giá/voucher đề xuất, giá sàn, constraint, lý do và bằng chứng. Đây là rule
engine deterministic, không dùng causal wording và không tự động thay đổi giá.

## Contract

Bảng `recommendations` có một dòng cho mỗi source SKU ở snapshot mới nhất:

- `recommendation_status`: `recommended`, `monitoring_only`,
  `needs_cost_validation`, `needs_promotion_validation`, `constraint_blocked`,
  hoặc `insufficient_evidence`.
- `action`: `hold_price`, `reduce_price`, `use_voucher`, `no_response`.
- `recommended_price` / `recommended_discount_percent` và
  `market_reference_price`.
- `cost_value`, `margin_min_pct`, `price_floor`, `estimated_margin_pct`.
- `reason_codes`, `recommendation_text`, `evidence`, `rule_version`.

Recommendation lưu cả loại base giá trong `evidence`. Giá niêm yết và trung vị
lịch sử không thay thế giá vốn, cũng không tự tạo đề xuất thay đổi giá. Một
hành động giá vẫn cần base `peer_market_median` và giá vốn đã xác minh.

## Input giá vốn

Giá vốn là CSV tùy chọn, cùng đơn vị tiền tệ với `products`:

```csv
country_code,shop_id,item_id,cost_value,margin_min_pct
vn,123456,987654321,45000,15
```

Nếu không có giá vốn, engine không phát hành hành động giảm giá/voucher; nó
chuyển thành `needs_cost_validation` và giữ giá hiện tại. Điều này tránh đề
xuất phá margin ngoài ý muốn.

Sản phẩm thay thế chỉ tạo trạng thái `monitoring_only`. Trạng thái này không
được tính vào số khuyến nghị hành động và không tạo giá/voucher mục tiêu.

`discount_percent` quan sát trên sàn không chứng minh voucher thực sự áp dụng
được. Nếu chưa có `promotion_terms_verified=true`, engine trả về
`needs_promotion_validation` và không phát hành voucher, kể cả đã có giá vốn.

## Giá gốc seed để chạy kịch bản

Khi chưa có giá vốn ERP, có thể tạo file `cost_inputs.seeded.csv`. Đây là dữ
liệu mô phỏng, không phải giá vốn đã xác minh:

- Base peer trực tiếp: dải 65–78%, seed 72%.
- Base lịch sử SKU: dải 60–80%, seed 70%.
- Chỉ có giá hiện tại/niêm yết: dải 55–85%, seed 70%.
- Listing nhiều lựa chọn: dải 50–90%, seed 70% và confidence rất thấp.

Recommendation dùng dữ liệu này mang trạng thái `scenario_only`, constraint
`seeded_cost_not_verified` và không được phê duyệt thực thi.

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

`margin_min_pct` là biên lợi nhuận gộp trên doanh thu, không phải tỷ lệ cộng
trên giá vốn. Vì vậy `price_floor = cost_value / (1 - margin_min_pct / 100)` và
`estimated_margin_pct = (effective_price - cost_value) / effective_price * 100`.
Giá đề xuất được làm tròn lên theo 100 đơn vị tiền tệ bản địa; trần voucher
được làm tròn xuống để không xuyên giá sàn. Đây là phép kiểm tra constraint,
không phải dự báo lợi nhuận.

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
