# 4. Roadmap và danh sách công việc

## Ngày 1 — Data Foundation: hoàn thành

- [x] Khảo sát schema và partition nguồn.
- [x] Đọc toàn bộ CSV.
- [x] Chuẩn hóa kiểu dữ liệu.
- [x] Deduplicate theo khóa tự nhiên.
- [x] Tạo DuckDB schema.
- [x] Tạo `promotion_events`.
- [x] Tạo `ingestion_quality`.
- [x] Đóng gói Docker và Docker Compose.
- [x] Chạy kiểm tra local và container.

## Ngày 2 — Product matching

- [x] Chọn latest snapshot và phạm vi candidate cùng quốc gia/category, khác shop.
- [x] Tạo bộ lọc category/country trước khi matching.
- [x] Chuẩn hóa brand, trọng lượng, dung tích, số lượng pack và bundle từ tên.
- [x] Tạo text vector baseline từ `product_name` đã làm sạch.
- [x] Xây hybrid matching và lưu top-K vào `product_matches`.
- [x] Tạo bộ đánh giá thủ công 100 cặp SKU tại `warehouse/matching_review.csv`.
- [x] Có `same_product`, `substitute`, `near_match`, `not_comparable` và `not_enough_evidence`.
- [x] Initial adjudication 100 cặp và chạy evaluator.
- [x] Peer Precision@1 = 1,00 và Peer Precision@5 = 0,90 trên review set.
- [ ] Xác nhận lại bằng reviewer độc lập trước khi dùng làm benchmark chính thức.
- [ ] Hiệu chỉnh threshold theo nhãn thật.
- [x] Chạy optional multilingual sentence-transformer backend để so sánh baseline.

## Ngày 3 — Market signals

- [x] Tạo peer group cho từng SKU trong `peer_groups`.
- [x] Tính price index và discount gap/index trong `market_signals`.
- [x] Tính sales/engagement momentum (proxy từ snapshot).
- [x] Tạo cảnh báo giá, promotion, momentum và pressure trong `competitor_alerts`.
- [x] Lưu timeline theo SKU và snapshot date.
- [x] Đánh dấu SKU không đủ bằng chứng bằng `not_enough_evidence`.
- [x] Ghi confidence, peer count, evidence count và model version.
- [x] Kiểm thử integration và chạy end-to-end bằng Docker.
- [ ] Hiệu chỉnh ngưỡng với người dùng nghiệp vụ trên alert review set.

## Ngày 4 — Recommendation engine

- [x] Thiết kế action space: giữ giá, giảm giá, voucher, không phản ứng.
- [x] Cho phép nhập giá vốn và margin tối thiểu qua CSV.
- [x] Tạo rule engine có version và ngưỡng v0.1.
- [x] Tính giá sàn và kiểm tra constraint.
- [x] Sinh recommendation card có lý do và nguồn dữ liệu.
- [x] Thêm trạng thái `insufficient_evidence`, `needs_cost_validation` và `constraint_blocked`.
- [x] Không dùng causal wording khi chỉ có proxy quan sát.
- [x] Tạo review set 20 recommendation cards và unit tests.
- [ ] Duyệt review set với nghiệp vụ và hiệu chỉnh threshold.

## Ngày 5 — API, UI và demo

- [x] Chốt API contract v1 và envelope `data/meta/error`.
- [x] Tạo API `/api/v1/products/{id}/peers`, `/signals`, `/alerts`, `/recommendation`.
- [ ] Tạo API `/products/{id}/events` (deferred vì dataset hiện tại chưa có event timeline riêng).
- [x] Xây màn hình Market Overview.
- [x] Xây màn hình SKU 360.
- [x] Xây màn hình Competitor Alerts.
- [x] Xây Recommendation Card.
- [x] Thêm AI Chat Copilot chỉ đọc dữ liệu đã tính.
- [ ] Chuẩn bị kịch bản demo end-to-end.

## Agent Layer — Market Intelligence Copilot: phần nền tảng đã scaffold

- [x] Tạo DeepSeek API adapter configurable bằng environment.
- [x] Tạo route harness với giới hạn vòng/tool và trace.
- [x] Tạo read-only allow-listed market tools.
- [x] Tạo short-term session memory và explicit long-term memory.
- [x] Thêm prompt-injection gate, untrusted-data boundary và secret redaction.
- [x] Thêm offline harness tests không phụ thuộc provider/network.
- [x] Thêm publication manifest `pipeline_runs` và chặn agent đọc stage chưa publish.
- [x] Thêm route-specific tool allow-list, argument type validation và audit trace store.
- [x] Thêm bearer token + shop scope guard cho production API mode.
- [x] Thêm in-process rate limit cho HTTP API wrapper.
- [ ] Chuyển HTTP development wrapper sang ASGI/API server production và dùng rate limit phân tán.
- [ ] Chạy red-team prompt injection và đánh giá câu trả lời trên benchmark nghiệp vụ.

## Sau MVP

- [ ] Bổ sung 90–180 ngày snapshot hoặc order log.
- [ ] Bổ sung giá vốn, phí sàn và contribution margin.
- [ ] Bổ sung tồn kho, inbound, lead time và stockout.
- [ ] Bổ sung quảng cáo, spend, click, conversion và ROAS.
- [ ] Bổ sung product matching cross-language tốt hơn.
- [ ] Thử demand forecasting và uplift modeling khi có dữ liệu đủ dài.
- [ ] Xây authentication, audit log và phân quyền shop.
- [ ] Chuyển từ DuckDB sang PostgreSQL nếu cần nhiều người dùng/ghi đồng thời.

## Giai đoạn tiếp theo — Closed-loop Decision Intelligence

MVP hiện tại đã hoàn thiện evidence layer. Để biến nó thành sản phẩm ra quyết
định thực sự, cần bổ sung workflow có trạng thái và feedback loop:

- [ ] Tạo `decision_cases` với priority, business impact, urgency và owner.
- [ ] Tạo `decision_options` cho giữ giá, giảm giá, voucher và no-action.
- [ ] Tạo `decision_constraints` cho cost, fee, price floor và margin floor.
- [ ] Tạo `decision_approvals` với approve/reject/reason/audit trail.
- [ ] Tạo scenario simulator cho nhiều mức giá/discount.
- [ ] Thêm API `decision-cases`, `simulate`, `approve`, `reject`, `feedback`.
- [ ] Xây Control Tower decision queue thay cho catalogue-only overview.
- [ ] Xây SKU Decision Room có timeline quyết định.
- [ ] Xây Approval Center cho duyệt đơn và duyệt batch.
- [ ] Tạo `decision_outcomes` và outcome review sau 1/3/7 ngày.
- [ ] Kết nối order/cost/margin thật trước khi báo cáo business lift.
- [ ] Chỉ xây platform connector sau khi approval workflow và audit log ổn định.
