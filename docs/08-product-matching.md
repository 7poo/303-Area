# 8. Thiết kế Product Matching

## Mục tiêu

Ghép một SKU tham chiếu với các sản phẩm ở shop khác để phân biệt:

- `same_product`: cùng sản phẩm/dòng sản phẩm.
- `substitute`: sản phẩm thay thế trực tiếp.
- `near_match`: gần giống nhưng khác quy cách hoặc segment.
- `not_comparable`: không nên dùng để so sánh.
- `not_enough_evidence`: không có candidate đủ tin cậy.

## Vì sao không dùng category + tên đơn giản?

Dataset Việt Nam tập trung ở top-level category `Food & Beverages`, còn Indonesia
tập trung ở `Beauty`. Tên sản phẩm chứa nhiều promotion noise như quà tặng,
flash sale, combo và tên shop. Vì vậy category chỉ là candidate gate; quyết định
match phải dùng product type, quy cách và text similarity.

## Pipeline hiện tại

```text
Latest snapshot
    ↓
clean_product_name / normalize_brand
    ↓
parse product_type, weight, volume, quantity, bundle, gift
    ↓
same country + same catid + different shop
    ↓
TF-IDF char embedding hoặc multilingual embedding tùy chọn
    ↓
hybrid score
    ↓
match_type + confidence + source_status
    ↓
product_matches / matching_review.csv
```

## Thuộc tính được parse

- `product_type`: dictionary theo quốc gia, ví dụ `banh_quy`, `ca_phe`,
  `moisturizer`, `serum`.
- `weight_g`, `volume_ml`.
- `quantity`, `bundle_count`.
- `is_bundle` cho combo/set/bộ/thùng.
- `is_gift` cho quà tặng/free gift/sản phẩm không bán.
- `brand_clean` để quy về một dạng brand.

## Hybrid score

Phiên bản baseline dùng:

```text
0.35 × text similarity
0.25 × product type
0.20 × attributes
0.10 × pack size
0.05 × price similarity
0.05 × brand relation
```

Text backend mặc định là TF-IDF character n-gram vì chạy được ngay trong Docker
và dễ tái lập. Backend `sentence-transformers` là tùy chọn, dùng model
`paraphrase-multilingual-MiniLM-L12-v2` cho tiếng Việt/Indonesia.

Đã chạy một pass semantic trên DB copy: `503/1.157` source được đánh dấu
`matchable`, so với `140/1.157` của TF-IDF baseline. Đây là so sánh độ phủ,
chưa phải kết luận chất lượng vì cần một review set riêng cho ranking semantic.

## Ngưỡng và confidence

| Score | Confidence | Ý nghĩa |
|---:|---|---|
| ≥ 0,80 | high | Có thể dùng cho recommendation |
| 0,70–0,80 | medium | Có thể hiển thị, cần kiểm tra evidence |
| 0,60–0,70 | low | Chỉ dùng để review |
| < 0,60 | not_enough_evidence | Không khuyến nghị |

Một source chỉ có `source_status=matchable` khi có `same_product` hoặc
`substitute` đạt ngưỡng tối thiểu. Top candidate yếu vẫn được lưu để debug,
nhưng không được dùng làm recommendation.

## Cách tạo bộ review 100 cặp

`warehouse/matching_review.csv` được lấy mẫu cố định seed 42. Baseline chọn 20
source SKU, phân bổ qua quốc gia và product type, rồi giữ đủ top-5 candidate
của mỗi source để metric ranking có ý nghĩa.

Người review điền:

```text
review_label = same_product | substitute | near_match | not_comparable
review_notes  = lý do ngắn
```

Người review phải gán nhãn cho đủ 5 candidate của từng source. Nhãn initial
adjudication hiện được lưu tách tại `validation/matching_review_labels.csv`;
benchmark chính thức vẫn nên được một reviewer độc lập xác nhận.

## Cách đánh giá

Với mỗi source SKU:

```text
peer_relevant = same_product hoặc substitute hoặc near_match
strict_relevant = same_product hoặc substitute
```

- `peer_precision@1`: top 1 có phải peer hợp lệ hay không.
- `peer_precision@5`: số peer hợp lệ trong top 5 chia cho 5.
- `strict_precision@1/@5`: chỉ tính same product/substitute.
- Coverage: tỷ lệ source được hệ thống tự tin cho là `matchable`.

Mục tiêu:

- `peer_precision@1` ≥ 80%.
- `peer_precision@5` ≥ 70%.
- Theo dõi thêm strict precision để biết mức exact/substitute riêng.

Nếu không đạt, ưu tiên sửa parser product type/quy cách và candidate gate trước
khi tăng độ phức tạp của embedding model.

## Lệnh chạy

```powershell
python -m src.matching `
  --db-path ./warehouse/market.duckdb `
  --backend tfidf `
  --top-k 5 `
  --review-size 100
```

Sau khi điền `review_label`, tính metric:

```powershell
python -m src.evaluate_matching `
  --review-file ./warehouse/matching_review.csv `
  --labels-file ./validation/matching_review_labels.csv
```

## Artefacts

- `product_attributes`: thuộc tính parse của latest snapshot.
- `product_matches`: top-K match cho từng source SKU.
- `warehouse/matching_review.csv`: bộ review thủ công.
- `model_version`: version parser/vector/scoring được lưu cùng kết quả.
