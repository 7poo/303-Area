# 8. Thiết kế Product Matching

## Mục tiêu

Ghép một SKU tham chiếu với các sản phẩm ở shop khác để phân biệt:

- `same_product`: cùng dòng, biến thể và quy cách.
- `same_product_variant`: cùng dòng và biến thể nhưng khác số lượng/quy cách.
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
same country + (same catid hoặc same product_type) + different seller entity
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
- `total_weight_g`, `total_volume_ml`, `package_ambiguous`.
- `family_signature`, `variant_signature`.
- `company_id`, `company_name`: hãng/chủ sở hữu thương hiệu dùng làm phạm vi phân tích.
- `seller_entity_id`, `seller_entity_name`: nhà bán/nhà phân phối dùng để loại tự so sánh.
- `is_bundle` cho combo/set/bộ/thùng.
- `is_gift` cho quà tặng/free gift/sản phẩm không bán.
- `brand_clean` để quy về một dạng brand.

## Hybrid score

Phiên bản baseline dùng:

```text
0.40 × text similarity
0.25 × product type
0.20 × attributes
0.10 × pack size
0.05 × brand relation
```

Text backend mặc định là TF-IDF character n-gram vì chạy được ngay trong Docker
và dễ tái lập. Backend `sentence-transformers` là tùy chọn, dùng model
`paraphrase-multilingual-MiniLM-L12-v2` cho tiếng Việt/Indonesia.

Giá không tham gia điểm nhận diện vì đây là biến cần phân tích, không phải bằng
chứng để quyết định hai SKU có giống nhau. Model v0.5 hiện đánh dấu 382/1.157
source là `matchable`; đây là số đo độ phủ, chưa phải kết luận precision.

## Ngưỡng và confidence

| Score | Confidence | Ý nghĩa |
|---:|---|---|
| ≥ 0,80 | high | Có thể dùng làm benchmark sau khi qua các gate thuộc tính |
| 0,70–0,80 | medium | Có thể hiển thị, vẫn cần kiểm tra evidence |
| 0,60–0,70 | low | Chỉ dùng làm bối cảnh/theo dõi đối thủ thay thế |
| < 0,60 | not_enough_evidence | Không khuyến nghị |

Một source chỉ có `source_status=matchable` khi có `same_product`,
`same_product_variant` hoặc `substitute` đạt ngưỡng tối thiểu. Top candidate yếu vẫn được lưu để debug,
nhưng không được dùng làm recommendation.

Hai shop thuộc cùng `seller_entity_id` không được tạo thành candidate. Hai nhà
phân phối khác nhau của cùng `company_id` vẫn được ghép để tìm cùng SKU và so
sánh chênh lệch giá theo kênh.
Phép so giá trong market signals chỉ sử dụng `same_product` và
`same_product_variant` có thể chuẩn hóa theo 100g, 100ml hoặc mỗi đơn vị;
`substitute` chỉ dùng làm bối cảnh thị trường hoặc khuyến nghị theo dõi, không
tạo mức giá mục tiêu.

Nếu `tier_variation_options` có hơn một lựa chọn, parser đặt
`price_variant_ambiguous=true`. Quan hệ sản phẩm vẫn có thể được xếp hạng,
nhưng giá hiển thị không được coi là giá của quy cách trích từ tên cho đến khi
có dữ liệu ánh xạ giá–biến thể.

## Cách tạo bộ review tối đa 200 cặp

`warehouse/matching_review.csv` được lấy mẫu cố định seed 42 và phân tầng theo
ba nhóm: dự đoán cùng sản phẩm, trường hợp hệ thống từ chối vì thiếu bằng
chứng, và các source matchable còn lại. Pipeline giữ tối đa top-5 candidate
của mỗi source. Đây là mẫu QA có chủ đích, không phải mẫu đại diện để ước lượng
tỷ lệ toàn quần thể.

Người review điền:

```text
review_label = same_product | same_product_variant | substitute | near_match | not_comparable
review_notes  = lý do ngắn
```

Người review phải gán nhãn cho đủ 5 candidate của từng source. Nhãn được nối
với review set bằng `pair_key` ổn định, không dùng `review_id` sau khi pipeline
thay đổi. Bộ nhãn legacy hiện tại cần được adjudicate lại cho model v0.4.

## Cách đánh giá

Với mỗi source SKU:

```text
peer_relevant = same_product hoặc same_product_variant hoặc substitute hoặc near_match
strict_relevant = same_product
```

- `peer_precision@1`: top 1 có phải peer hợp lệ hay không.
- `peer_precision@5`: số peer hợp lệ trong top 5 chia cho 5.
- `strict_precision@1/@5`: chỉ tính `same_product`.
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
  --top-k 10 `
  --review-size 200 `
  --company-registry ./config/company_registry.csv
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
