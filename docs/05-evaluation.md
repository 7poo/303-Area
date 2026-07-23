# 5. Kế hoạch kiểm thử và đánh giá

## Data pipeline

Mỗi lần chạy ETL phải kiểm tra:

- Số file và số dòng nguồn.
- Số dòng đã nạp theo từng dataset.
- Số dòng trùng.
- Null và outlier của giá.
- Tính duy nhất của khóa tự nhiên.
- Tính hợp lệ của JSON và timestamp.
- Số lượng `is_ad = TRUE` và `is_sold_out = TRUE`.

Pipeline phải fail rõ ràng khi thiếu partition bắt buộc, thiếu ngày hoặc lỗi
schema nghiêm trọng.

## Product matching

Tạo một tập đánh giá thủ công gồm các cặp:

- `match`: cùng sản phẩm hoặc sản phẩm thay thế trực tiếp.
- `near_match`: cùng loại nhưng khác quy cách/segment.
- `not_match`: không thể so sánh.

Chỉ số:

- Precision@1.
- Precision@5.
- Recall@5 khi có nhãn đầy đủ.
- Tỷ lệ kết quả bị đánh giá là “không đủ thông tin”.

Mục tiêu MVP đề xuất:

- Precision@1 ≥ 80% trên tập cặp đã xác nhận.
- Precision@5 ≥ 70%.
- Không tự động khuyến nghị nếu không có peer đủ tin cậy.

Với Market Intelligence, `near_match` vẫn là peer hợp lệ để so sánh ở mức thị
trường. Vì vậy báo cáo nên tách:

- `peer_precision`: `same_product`, `same_product_variant`, `substitute`, `near_match`.
- `strict_precision`: chỉ `same_product` cùng biến thể và quy cách.
- `coverage/abstention`: bao nhiêu source được đánh dấu `matchable` hay
  `not_enough_evidence`.

Kết quả của review set legacy chỉ dùng làm lịch sử và không được gán sang cặp
mới theo `review_id`. Với model v0.4 hiện tại:

```text
labeled_pairs = 0 / 200
label_join = none
metrics = pending independent adjudication
```

Chỉ công bố precision/recall/F1 và confusion matrix sau khi 200 cặp mới được
review độc lập bằng `pair_key`.

Bộ 200 cặp hiện là mẫu QA phân tầng, cố ý tăng tỷ trọng dự đoán identity và
abstention. Không dùng `coverage_on_review_sources` của mẫu này để suy rộng
coverage toàn danh mục; coverage vận hành phải tính trực tiếp trên toàn bộ
`product_matches`.

## Market event detection

Kiểm tra thủ công các event theo loại:

- Đúng ngày thay đổi.
- Đúng giá trị cũ/mới.
- Không phát sinh event giả do duplicate.

Mục tiêu:

- 100% event có thể truy ngược về hai snapshot.
- 0 khóa sản phẩm trùng trong bảng event.

Synthetic regression benchmark được mô tả tại
`docs/11-synthetic-benchmark.md`. Bộ này có canonical identity, latent demand,
stock và event truth để test edge case; không thay thế tập nhãn dữ liệu thật.

## Recommendation engine

Với dataset hiện tại chỉ đánh giá được tính hợp lý và nhất quán, không đánh giá
được causal uplift hay lợi nhuận thật.

Checklist:

- Có peer group hợp lệ.
- Có giá và currency hợp lệ.
- Tôn trọng giá sàn/margin nếu người dùng nhập.
- Có lý do rõ ràng.
- Có số lượng snapshot/bằng chứng.
- Có confidence.
- Trả về `insufficient_evidence` khi thiếu dữ liệu.

## UI acceptance test

Một người dùng mới phải hoàn thành được trong tối đa 3 phút:

1. Chọn một SKU.
2. Xem top sản phẩm tương đồng.
3. Xem thay đổi giá/promotion.
4. Nhập giá vốn và margin.
5. Nhận một recommendation có giải thích.

## Nguyên tắc chia tập dữ liệu

Không random split từng dòng vì cùng một sản phẩm xuất hiện nhiều ngày. Khi có
thêm dữ liệu lịch sử, phải split theo thời gian và kiểm tra riêng theo shop,
category và quốc gia.
