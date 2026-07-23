# Synthetic benchmark có ground truth

## Mục tiêu

Gói synthetic này kiểm tra độ đúng logic và khả năng chống edge case của hệ
thống. Nó không được trộn vào dữ liệu production và không được dùng để tuyên bố
độ chính xác hay causal uplift ngoài đời thật.

Mọi bảng đều có `is_synthetic`, `generator_version` và `random_seed`. Manifest
lưu SHA-256 cho từng file để kiểm tra khả năng tái lập.

## Thiết kế dữ liệu

Lệnh chuẩn:

```powershell
python -m src.synthetic_benchmark `
  --output-dir ./synthetic/market_benchmark_v1 `
  --canonical-count 250 `
  --sellers-per-product 3 `
  --days 120 `
  --seed 303
```

Đầu ra:

| File | Nội dung |
|---|---|
| `canonical_products.csv` | Identity thật, family, flavor, size, elasticity và market regime |
| `offers.csv` | 3 nhà phân phối cho mỗi canonical product, pack size và title noise |
| `variation_prices.csv` | Ánh xạ option–pack–price và default option |
| `matching_ground_truth.csv` | Cặp cùng sản phẩm, khác pack, substitute, near và not comparable |
| `daily_market.csv` | Giá, checkout price, latent demand, sales, stock và event trong 120 ngày |
| `promotion_terms.csv` | Min spend, cap, thời gian và tỷ lệ seller/platform funding |
| `unit_economics.csv` | COGS, phí, fulfillment, returns và contribution margin |
| `manifest.json` | Row count, data-quality distribution, invariants và file hashes |
| `matching_benchmark.json` | Benchmark matcher hiện tại trên ground truth synthetic |

## Quy luật sinh

- Mỗi canonical product có ba offers từ ba seller entity độc lập.
- Counterfactual twins chỉ đổi seller hoặc pack count; brand, family, flavor và
  unit size được giữ nguyên.
- Hard negatives giữ family/flavor/size gần giống nhưng đổi edition/model.
- Demand tiềm ẩn có own-price elasticity từ -2,4 đến -1,1, weekly seasonality,
  trend và promotion lift.
- Sales quan sát bị chặn bởi tồn kho; latent demand được giữ riêng để nhận biết
  stockout censoring.
- Năm market regime cân bằng: stable, promotion pulse, price war, stockout và
  seasonal growth.
- Missing snapshot và price outlier được chèn có kiểm soát, có ground-truth
  `data_quality_flag`.
- Unit economics tính contribution sau COGS, platform fee, payment fee,
  fulfillment và expected return cost.

## Kết quả v1

Dataset seed 303:

- 250 canonical products.
- 750 offers.
- 1.050 variation prices.
- 3.750 matching pairs có ground truth.
- 90.000 product-day observations.
- 750 promotion contracts và 750 unit-economics rows.
- 642 missing snapshots, 165 price outliers.
- 0 vi phạm identity uniqueness, default variation, cost/price, stock và
  checkout/listed-price invariants.
- Contribution margin trung vị 18,17%; 222 offers dưới ngưỡng 15% để kiểm tra
  constraint blocking.

Matcher `hybrid-tfidf-charword-v0.5`:

- Top-1 relation accuracy: 48,27%.
- Identity retrieval@1: 35,60%.
- Multi-option gate recall: 100%.
- 388 hard negatives có edition/model khác bị dự đoán sai thành
  `same_product`.

Kết quả thấp được giữ nguyên vì nó phát hiện một lỗ hổng thật trong logic:
matcher chưa coi edition/model token là identity gate mạnh. Synthetic benchmark
không được thiết kế lại để làm metric đẹp hơn.

## Cách diễn giải

Benchmark này chứng minh:

1. Cổng listing nhiều lựa chọn hoạt động đúng trên dữ liệu có ground truth.
2. Matching còn nhầm sản phẩm khác edition khi brand/family/flavor/size giống
   nhau.
3. Dữ liệu production ba ngày chưa đủ đánh giá momentum, trong khi synthetic
   120 ngày cho phép regression test đầy đủ.
4. Recommendation có thể được kiểm tra bằng contribution margin thật trong
   simulation thay vì chỉ dựa trên phần trăm seed.

Metric synthetic chỉ là regression/sanity benchmark. Kết luận production vẫn
cần nhãn review độc lập trên dữ liệu thật.
