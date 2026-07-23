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

- Peer benchmark chỉ nhận quan hệ hợp lệ với `source_status = matchable` và
  `match_score >= 0.60`. Dải 0,60–0,70 có độ tin cậy thấp và chỉ dùng để theo
  dõi/bối cảnh, không tự động tạo giá mục tiêu.
- Phép so giá chỉ nhận `same_product` và `same_product_variant` có quy cách
  chuẩn hóa được; `substitute` không làm giá mục tiêu trực tiếp.
- Sự kiện hoạt động như đối thủ giảm giá hoặc mở promotion được phép theo dõi
  trên `substitute` đạt ngưỡng. Evidence ghi `comparison_scope =
  qualified_substitute_activity` để phân biệt với so sánh giá tương đương.
- Candidate phải cùng quốc gia, cùng category hoặc product type, và khác
  `seller_entity_id`. Cùng hãng nhưng khác nhà phân phối là một trường hợp so
  sánh hợp lệ và được ưu tiên khi dòng/biến thể/quy cách trùng nhau.
- Mỗi SKU không có peer tốt được ghi một dòng `not_enough_evidence`; không
  suy đoán peer từ khác quốc gia hoặc `not_comparable`.

### 2. Market signals

`market_signals` được tính cho tất cả snapshot của source SKU, nhưng peer group
lấy từ lần matching mới nhất. Các trường chính:

- Giá được chuẩn hóa theo 100g, 100ml hoặc mỗi đơn vị trước khi tính
  `price_index` và `price_gap_pct`.
- Giá chỉ được chuẩn hóa khi cả source và peer có quy cách rõ ràng và listing
  không chứa nhiều lựa chọn (`price_variant_ambiguous = false`). Listing nhiều
  lựa chọn vẫn được theo dõi hoạt động nhưng không làm benchmark giá.
- Các listing peer được gom theo `seller_entity_id + snapshot_date` trước khi
  lấy trung vị. `peer_count` là số đơn vị bán độc lập, không phải số listing.
- Base giá được lưu bằng `price_baseline_value`, `price_baseline_type` và
  `price_baseline_actionable`. Thứ tự ưu tiên là trung vị peer cùng sản phẩm,
  trung vị lịch sử của chính SKU khi có ít nhất 3 quan sát, rồi giá niêm yết.
  Chỉ `peer_market_median` được coi là base thị trường đủ chuẩn cho hành động;
  `own_history_median` và `listed_reference` chỉ dùng để tham khảo.
- `discount_gap_pct = source_discount - peer_median_discount` (đơn vị điểm %).
- `source_sales_momentum_pct` và `peer_sales_momentum_pct` dùng log-return có
  chặn biên `[-100%, 100%]`; chỉ tính khi có ít nhất 7 quan sát và kỳ trước
  đạt tối thiểu 20 đơn vị. Lịch sử ngắn hơn trả về `NULL`.
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
| `our_price_above_market` | `price_gap_pct >= 10`, có peer giá hợp lệ, không phải ngoại lệ giá |
| `our_discount_below_market` | `discount_gap_pct <= -10`, có peer giá hợp lệ, không phải ngoại lệ giá |
| `competitor_price_down` | Có peer giảm giá trong ngày |
| `competitor_promotion_started` | Có peer đổi promotion trong ngày |
| `competitor_momentum_up` | `peer_sales_momentum_pct >= 20` |
| `high_competitive_pressure` | `competitive_pressure_score >= 0.55` |

Alert event có `target_shop_id/target_item_id` đại diện và `evidence` JSON để
truy ngược số peer, median giá, event count và model version. Alert không tự
động thay đổi giá.

Hai alert hoạt động đối thủ có thể dùng peer thay thế đủ chuẩn. Hai alert
`our_price_above_market` và `our_discount_below_market` vẫn bắt buộc peer giá
exact/variant đã chuẩn hóa quy cách.

## Chạy

```powershell
docker compose run --rm market-signals
```

Hoặc local:

```powershell
python -m src.signals --db-path ./warehouse/market.duckdb --min-peer-score 0.60
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
- API chỉ trình bày cảnh báo còn đúng tại snapshot mới nhất của từng SKU; lịch
  sử vẫn được giữ trong bảng để audit.
- Frontend cảnh báo dữ liệu cũ khi snapshot gần nhất quá 2 ngày.
- Có review set tối thiểu 20 alert cho nghiệp vụ gán nhãn.
- Unit/integration tests kiểm tra peer, momentum, abstention và event traceability.
