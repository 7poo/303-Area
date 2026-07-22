# 3. Data contract và data dictionary

## Nguồn dữ liệu

| Dataset | Ý nghĩa | Khóa nạp |
|---|---|---|
| `products` | Snapshot sản phẩm theo ngày | `country_code, shop_id, item_id, snapshot_date` |
| `shop_info` | Snapshot thông tin shop | `country_code, shop_id, snapshot_date` |
| `category_list` | Danh mục riêng của shop | `country_code, shop_id, shop_category_id, snapshot_date` |
| `product_categories` | Liên kết sản phẩm và danh mục shop | `country_code, shop_id, item_id, category_id, snapshot_date` |
| `category_platform` | Taxonomy Shopee | `country_code, category_id` |
| `product_attributes` | Thuộc tính đã parse để matching | `country_code, shop_id, item_id` |
| `product_matches` | Top-K candidate và score ghép SKU | `country_code, snapshot_date, source_item_id, target_item_id, model_version` |
| `peer_groups` | Peer hợp lệ được dùng cho tín hiệu | `country_code, source_snapshot_date, source_item_id, target_item_id` |
| `market_signals` | Timeline chỉ số giá, discount, momentum và pressure | `country_code, snapshot_date, source_item_id` |
| `competitor_alerts` | Alert có ngưỡng và bằng chứng truy vết | `country_code, snapshot_date, source_item_id, alert_type` |
| `recommendations` | Recommendation card có constraint và evidence | `country_code, snapshot_date, source_item_id, rule_version` |
| `pipeline_runs` | Manifest publish thành công/thất bại của từng stage | `run_id, stage, status` |

## Bảng `products`

Các trường nghiệp vụ chính:

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `country_code` | VARCHAR | `vn` hoặc `id` |
| `currency` | VARCHAR | `VND` hoặc `IDR`, suy ra từ quốc gia |
| `snapshot_date` | DATE | Ngày thu thập |
| `shop_id` | BIGINT | Shop sở hữu sản phẩm |
| `item_id` | BIGINT | ID sản phẩm Shopee |
| `product_name` | VARCHAR | Tên hiển thị gốc |
| `product_name_normalized` | VARCHAR | Tên lowercase, bỏ ký tự thừa, phục vụ matching |
| `price` | BIGINT | Giá hiện tại theo đơn vị bản địa |
| `price_original` | BIGINT | Giá niêm yết gốc |
| `price_before_promo` | BIGINT | Giá trước promotion |
| `discount_percent` | DOUBLE | Phần trăm giảm giá |
| `promotion_id` | VARCHAR | ID promotion, giữ dạng text để không mất giá trị `0` |
| `voucher_code` | VARCHAR | Mã voucher nếu có |
| `voucher_discount` | DOUBLE | Mức giảm voucher |
| `history_sold_value` | DOUBLE | Proxy lượng bán lịch sử |
| `monthly_sold_value` | DOUBLE | Proxy lượng bán tháng |
| `rating`, `rating_count` | DOUBLE/BIGINT | Điểm và số lượng đánh giá |
| `liked_count` | BIGINT | Lượt thích |
| `brand`, `brand_id` | VARCHAR | Thương hiệu |
| `catid` | BIGINT | Category platform |
| `is_ad`, `is_sold_out` | BOOLEAN | Cờ quảng cáo và hết hàng quan sát được |

## Bảng `promotion_events`

Mỗi dòng là một thay đổi của một trường giữa hai snapshot:

- `country_code`, `shop_id`, `item_id`
- `snapshot_date`, `previous_date`
- `event_type`
- `old_value`, `new_value`

## Bảng `product_attributes`

Được tạo từ latest snapshot của từng SKU. Các trường chính gồm:

- `product_name_clean`: tên đã bỏ marketing noise.
- `brand_clean`: brand lowercase, bỏ hậu tố store/shop.
- `product_type`: loại sản phẩm từ dictionary theo quốc gia.
- `weight_g`, `volume_ml`, `quantity`, `bundle_count`.
- `is_bundle`, `is_gift`.
- `embedding_text`: chuỗi có cấu trúc dùng cho vector hóa.
- `parser_version`: version của bộ parser thuộc tính.

## Bảng `product_matches`

Mỗi source SKU có tối đa `top_k` target candidate:

- `match_score`, `match_type`, `confidence`.
- `source_status`: `matchable` hoặc `not_enough_evidence`.
- `matching_features`: JSON lưu text score, type, attribute, pack size, price và các gate.
- `model_version`, `created_at` để tái lập kết quả.

## Các bảng Giai đoạn 3

`peer_groups` chỉ chứa `same_product`, `substitute`, `near_match` vượt ngưỡng
score; source không có peer được ghi rõ `not_enough_evidence`. `market_signals`
giữ nguyên đơn vị giá bản địa, có `peer_count`, `signal_confidence`,
`evidence_count` và version. `competitor_alerts` lưu loại cảnh báo, severity,
metric/threshold, target peer (đối với event alert) và `evidence` JSON. Các bảng
này là output batch, được drop/recreate khi chạy lại `src.signals`; giá bất
thường được giữ lại và đánh dấu qua `is_price_outlier/outlier_reason`.

`recommendations` là output của `src.recommendations`, lấy snapshot mới nhất
của `market_signals`. Các action chỉ là candidate để người dùng duyệt; cost,
margin floor và trạng thái constraint phải được hiển thị cùng card.

`pipeline_runs` là publication boundary. Agent chỉ đọc output khi run mới nhất
của stage có `status = success`; run đang chạy hoặc thất bại bị coi là chưa
publish.

## Quy tắc chuẩn hóa

- Encoding CSV: UTF-8 with BOM được đọc bằng `utf-8-sig`.
- Giá không quy đổi giữa VND và IDR; chỉ gắn thêm `currency`.
- Epoch timestamp được chuyển thành UTC, lưu không timezone trong DuckDB.
- Chuỗi rỗng được đổi thành `NULL`.
- Các trường array được lưu dưới dạng JSON.
- Khóa tự nhiên được deduplicate trước khi insert.
- Giá từ `10.000.000` trở lên được gắn vào báo cáo outlier để loại khi tạo feature.

## Data quality hiện tại

- Raw product rows: 3.371.
- Loaded product rows: 3.341.
- Duplicate product rows: 30.
- Null price: 0.
- Price outliers: 3.
- `is_ad = TRUE`: 0.
- `is_sold_out = TRUE`: 0.

## Giả định cần xác nhận ở các ngày tiếp theo

- `history_sold_value` có thể đã được Shopee làm tròn/cắt ngưỡng.
- `monthly_sold_value` là cửa sổ trượt, không phải doanh số trong ngày.
- `NULL` voucher hiện đang được hiểu là không có voucher, cần xác nhận với data owner.
- Shop nội bộ chưa có cờ trong nguồn và phải cấu hình thủ công.
