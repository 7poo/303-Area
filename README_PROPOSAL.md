# Proposal: E-commerce Decision Intelligence

## Pricing & Promotion Control Tower

### Một hệ thống giúp operator biết SKU nào cần hành động, nên làm gì, vì sao và hành động đó có hiệu quả hay không

## 1. Vấn đề thật sự cần giải quyết

Một seller có vài nghìn SKU không thiếu dashboard. Vấn đề là mỗi ngày họ vẫn
phải làm thủ công:

1. Lọc những SKU có doanh số hoặc margin đang giảm.
2. Tìm đúng sản phẩm đối thủ để so sánh, tránh so sánh nhầm pack size hoặc loại
   sản phẩm.
3. Kiểm tra giá, discount, voucher và trạng thái bán của đối thủ.
4. Chọn hành động: giữ giá, giảm giá, chạy voucher hay không phản ứng.
5. Gửi yêu cầu thay đổi cho người duyệt hoặc cập nhật lên sàn.
6. Vài ngày sau kiểm tra xem hành động có tạo ra kết quả hay chỉ làm giảm margin.

Các dashboard thông thường chỉ hoàn thành bước 1–3. Một chatbot chỉ trả lời
câu hỏi cũng chưa giải quyết bước 4–6. Vì vậy sản phẩm này không được định
nghĩa là “dashboard có AI”, mà là **decision workflow có AI hỗ trợ**.

### Tình huống cụ thể

Một operator quản lý 3.000 SKU mở hệ thống lúc 9:00. Hệ thống phải trả lời:

> “Trong hôm nay, 20 SKU nào cần tôi xem trước? SKU nào đang bị peer giảm giá?
> Nếu giảm 5% thì có vi phạm margin floor không? Tôi có thể duyệt nhóm hành
> động nào và tuần sau đo hiệu quả ở đâu?”

Nếu không trả lời được toàn bộ chuỗi này, hệ thống mới chỉ là analytics chứ
chưa phải Decision Intelligence.

## 2. Đề xuất giải pháp

Xây **Pricing & Promotion Control Tower** với vòng lặp quyết định khép kín:

```text
Observe → Diagnose → Simulate → Recommend → Approve → Execute → Learn
   ↑                                                          ↓
   └────────────── outcome và feedback quay lại hệ thống ─────┘
```

### Observe — Quan sát

Nạp snapshot sản phẩm, lịch sử giá, promotion, voucher, sales proxy, tồn kho
và dữ liệu quảng cáo nếu có.

### Diagnose — Chẩn đoán

Ghép peer đúng, tính price gap, discount gap, momentum, pressure và xác định
nguyên nhân có thể quan sát được. Mỗi cảnh báo phải có evidence, không chỉ có
một điểm số.

### Simulate — Mô phỏng

Cho operator thử các phương án:

- Giữ giá.
- Giảm 3%, 5% hoặc 10%.
- Tăng discount bằng voucher.
- Không phản ứng.

Hệ thống tính tác động **dự kiến** lên giá tương đối, margin floor, discount
position và risk. Đây là scenario analysis, không được trình bày như cam kết
doanh thu nếu chưa có causal evidence.

### Recommend — Đề xuất

Policy engine chọn action phù hợp với context, mục tiêu và constraint. LLM chỉ
giải thích và điều phối tool; LLM không tự quyết định giá.

### Approve — Phê duyệt

Operator xem evidence, chỉnh tham số, duyệt một SKU hoặc một batch. Tất cả
quyết định tạo thành `decision_case` và có người chịu trách nhiệm.

### Execute — Triển khai

MVP chỉ tạo action plan/read-only preview. Giai đoạn sau mới kết nối Shopee,
OMS hoặc promotion service sau bước xác nhận rõ ràng của người dùng.

### Learn — Học từ kết quả

Sau thời gian đánh giá, hệ thống ghi nhận giá mới, sales, margin, conversion,
stockout và kết quả thực tế. Từ đó đo recommendation acceptance, action lift
và hiệu chỉnh policy.

## 3. Phạm vi sản phẩm: làm hẹp để giải quyết được vấn đề

Không bắt đầu bằng việc hứa tối ưu đồng thời giá, promotion, tồn kho và ads.
MVP nên tập trung vào một decision loop có thể chứng minh:

### P0 — Pricing & promotion decisioning

- SKU nào lệch giá so với peer?
- Có nên giảm giá hoặc chạy voucher?
- Hành động có vượt price floor/margin floor không?
- Ai duyệt và kết quả sau hành động là gì?

### P1 — Competitor monitoring

- Peer nào vừa giảm giá hoặc tăng promotion?
- Alert nào đáng xử lý trước?
- Alert nào chỉ là nhiễu hoặc thiếu evidence?

### P2 — Inventory decisioning

Chỉ bật khi có tồn kho, inbound, lead time và stockout. Khi đó action space mới
có thể gồm reorder, markdown hoặc giữ giá để bảo vệ tồn.

### P3 — Advertising decisioning

Chỉ bật khi có spend, impressions, clicks, orders, conversion và ROAS. Không
suy diễn hiệu quả quảng cáo từ product snapshot.

## 4. Người dùng và workflow hằng ngày

### Workflow A — Daily decision queue

Mỗi sáng hệ thống sinh danh sách các `decision_case` được xếp hạng theo:

```text
priority = business_impact × confidence × urgency × actionability
```

Một case chỉ vào queue khi có đủ evidence tối thiểu. Case thiếu peer, thiếu
cost hoặc mâu thuẫn dữ liệu phải hiện rõ trạng thái `not_enough_evidence`, không
bị ép thành recommendation.

### Workflow B — SKU Decision Room

Operator mở một SKU và thấy trong cùng một màn hình:

- Giá và promotion hiện tại.
- Peer được match, match score và lý do match.
- Price gap, discount gap, pressure và timeline.
- Constraint: cost, price floor, margin tối thiểu.
- Các scenario “giữ giá / giảm 5% / voucher”.
- Recommendation, evidence và confidence.
- Lịch sử quyết định trước đây của SKU.

### Workflow C — Approve batch

Operator chọn nhiều SKU có cùng pattern, xem tổng tác động dự kiến, sau đó:

- Duyệt batch.
- Từ chối và ghi lý do.
- Gửi lại để review.
- Chỉ xuất action plan nếu tất cả constraint đều hợp lệ.

### Workflow D — Outcome review

Sau 1, 3 hoặc 7 ngày, hệ thống tạo outcome card:

- Action đã thực hiện.
- Giá/promotion trước và sau.
- Sales, margin, conversion, stockout trước và sau.
- Kết quả đạt/không đạt/không đủ dữ liệu.

Đây là phần biến hệ thống từ “recommendation demo” thành sản phẩm có learning
loop.

## 5. Các thành phần phải xây

### 5.1 Data layer

Nguồn tối thiểu:

- `product_snapshots`: giá, discount, brand, category, pack size, shop.
- `price_history`: thay đổi giá theo ngày/giờ.
- `promotion_events`: promotion, voucher, start/end time.
- `sales_snapshots`: sold value hoặc order data nếu có.
- `cost_constraints`: cost, fee, margin floor.
- `inventory_snapshots`: stock, inbound, lead time ở giai đoạn sau.
- `ad_metrics`: spend, click, conversion, ROAS ở giai đoạn sau.

DuckDB phù hợp cho batch MVP. Khi có nhiều user, action write và concurrency,
chuyển metadata/workflow sang PostgreSQL; DuckDB vẫn có thể giữ vai trò
analytical warehouse.

### 5.2 Feature và matching layer

- Chuẩn hóa product name.
- Tách brand, category, type, weight, volume, quantity, bundle.
- Candidate filter cùng country/category, khác shop.
- Hybrid matching: text embedding + structured features + business rules.
- Lưu `match_score`, `match_type`, `matching_features`, `model_version`.
- Có manual review set và threshold theo category.

### 5.3 Signal và alert layer

Tính:

- `price_index`, `price_gap_pct`.
- `discount_gap_pct`.
- `sales_momentum_pct` và `engagement_momentum_pct`.
- `competitive_pressure_score`.
- `signal_confidence`, `evidence_count`.

Alert phải có severity, metric, threshold, target peer và evidence JSON. Không
đẩy toàn bộ biến động vào inbox của operator; cần deduplicate và group theo
decision case.

### 5.4 Decision engine

Đây là module hiện còn thiếu nếu chỉ dừng ở recommendation table. Cần xây:

- `decision_case`: vấn đề cần xử lý.
- `decision_options`: các phương án có thể chọn.
- `decision_constraints`: price floor, margin, stock, policy.
- `decision_recommendation`: phương án mặc định và confidence.
- `decision_approval`: ai duyệt, lúc nào, lý do.
- `decision_action`: action plan đã tạo.
- `decision_outcome`: kết quả sau thời gian đánh giá.

Recommendation engine hiện tại là nền tảng policy v0.1. Bước tiếp theo là bọc
engine trong một workflow có trạng thái:

```text
detected → triaged → simulated → proposed → approved/rejected
→ executed → measuring → evaluated
```

### 5.5 Agent layer

Agent không được phép tự do truy cập database. Agent chỉ dùng các tool đã cấp
quyền theo route:

- `search_products`.
- `get_product_snapshot`.
- `get_peers`.
- `get_market_signals`.
- `get_competitor_alerts`.
- `get_recommendation`.
- `simulate_decision` — tool mới cần xây, chỉ tính scenario.
- `get_decision_history` — tool mới cần xây, chỉ đọc audit log.

Các thao tác thay đổi giá hoặc gửi promotion phải tách thành command service,
có confirmation UI và audit log; không cho LLM tự gọi trực tiếp.

### 5.6 API layer

Các API read-only hiện có:

```text
GET  /api/v1/products
GET  /api/v1/products/{id}
GET  /api/v1/products/{id}/peers
GET  /api/v1/products/{id}/signals
GET  /api/v1/products/{id}/alerts
GET  /api/v1/products/{id}/recommendation
POST /api/v1/chat
GET  /api/v1/alerts
GET  /api/v1/recommendations
```

Các API cần xây tiếp để đóng vòng lặp:

```text
GET  /api/v1/decision-cases?status=proposed
GET  /api/v1/decision-cases/{id}
POST /api/v1/decision-cases/{id}/simulate
POST /api/v1/decision-cases/{id}/approve
POST /api/v1/decision-cases/{id}/reject
POST /api/v1/decision-cases/{id}/feedback
GET  /api/v1/decision-cases/{id}/outcome
```

Mọi POST phải có user, reason, idempotency key và audit trace. `approve` trước
mắt chỉ tạo action plan; connector thực thi thật là một phase riêng.

### 5.7 Frontend cần xây

1. **Control Tower** — decision queue, filter theo severity/impact/status.
2. **SKU Decision Room** — toàn bộ evidence, peer, signal và timeline.
3. **Scenario Simulator** — slider giá/discount, margin guardrail và so sánh
   phương án.
4. **Approval Center** — duyệt/reject batch, bắt buộc reason.
5. **Outcome Review** — so sánh before/after và đánh dấu outcome.
6. **Copilot panel** — hỏi đáp có context từ case đang mở.
7. **Admin/Model view** — model version, threshold, publication run, failed
   pipeline và data freshness.

Market Overview hiện tại là nền tảng tốt, nhưng cần chuyển trọng tâm từ
“xem catalogue” sang “xử lý decision queue”.

## 6. Kiến trúc triển khai

```text
Sources / CSV / platform APIs
            ↓
Ingestion + validation + data quality
            ↓
DuckDB analytical warehouse
            ↓
Matching → Signals → Decision policy
            ↓
Decision case store + publication manifest
            ↓
API/Agent service ─────→ React Control Tower
            ↓
Approval / command service (phase sau)
            ↓
Platform connector / action execution
            ↓
Outcome collector → evaluation + feedback
```

### Dev deployment

Docker Compose gồm:

- Batch data foundation.
- Product matching.
- Market signals.
- Recommendation engine.
- Agent API.
- React frontend.

### Production deployment

Tách các thành phần có state và write:

- PostgreSQL: users, scopes, decision cases, approvals, audit log.
- Object storage: raw CSV và model artefacts.
- DuckDB/Parquet hoặc analytical warehouse: feature/snapshot query.
- Redis: rate limit, queue và short-lived cache.
- Worker: pipeline, simulation, outcome evaluation.
- API gateway: auth, tenant isolation, CORS và observability.
- Secret manager: DeepSeek key và platform credentials.

## 7. Lộ trình triển khai thực tế

### Sprint 1 — Evidence foundation

- Giữ pipeline hiện tại.
- Hoàn thiện publication manifest và data freshness.
- Nâng manual matching review lên benchmark theo category.
- Đưa alert về cùng một schema decision case.

### Sprint 2 — Decision workflow

- Xây `decision_cases`, `decision_options`, `decision_approvals`.
- Xây decision queue và SKU Decision Room.
- Thêm approve/reject/feedback API.
- Lưu toàn bộ action và lý do của operator.

### Sprint 3 — What-if và outcome

- Xây scenario simulator có margin floor.
- Thêm price/discount policy versioning.
- Xây outcome collector và before/after card.
- Đo recommendation acceptance và action completion.

### Sprint 4 — Agent và production hardening

- Thêm `simulate_decision` và `get_decision_history` tools.
- Context Copilot theo case đang mở.
- Red-team prompt injection.
- FastAPI/ASGI, PostgreSQL metadata, Redis rate limit, monitoring.

### Sau khi có dữ liệu đủ dài

- Demand forecasting.
- Uplift/causal evaluation.
- Inventory allocation.
- Ads budget/ROAS decisioning.
- Platform action connector với approval bắt buộc.

## 8. KPI chứng minh sản phẩm có giá trị

### KPI vận hành

- Thời gian từ alert đến quyết định.
- Tỷ lệ decision case được xử lý.
- Tỷ lệ recommendation được chấp nhận.
- Tỷ lệ action plan được thực thi.
- Số SKU operator có thể xử lý mỗi ngày.

### KPI kinh doanh

- Margin không vi phạm floor.
- Price competitiveness theo category.
- Sales/conversion before-after, chỉ báo cáo causal lift khi có thiết kế đo
   phù hợp.
- Tỷ lệ giảm các alert không actionable.

### KPI mô hình

- Matching Precision@1 và Precision@5.
- Alert precision theo loại alert.
- Recommendation calibration/confidence.
- Tỷ lệ `not_enough_evidence` đúng.
- Data freshness và publication success rate.

## 9. Những gì đã có và những gì còn thiếu

### Đã có trong repository

- Data Foundation và DuckDB.
- Product matching baseline.
- Peer groups, market signals và competitor alerts.
- Rule-based recommendation với cost/margin guardrail.
- DeepSeek agent harness, memory, tools và safety gate.
- Read-only API v1.
- React/Vite/TypeScript dashboard MVP.

### Còn thiếu để thật sự trở thành Decision Intelligence

- Decision queue có business impact và priority.
- Decision case store và lịch sử quyết định.
- Scenario simulator có nhiều option.
- Approval/reject/feedback workflow.
- Action plan và connector thực thi.
- Outcome collector và before/after evaluation.
- Dữ liệu cost, fee, order, inventory và ads ở các phase tương ứng.

Đây là điểm quan trọng: phiên bản hiện tại đã có **evidence layer**, nhưng
chưa hoàn toàn có **closed-loop decision layer**. Proposal này đặt closed loop
làm trung tâm của sản phẩm tiếp theo.

## 10. Kịch bản demo thuyết phục

1. Mở Control Tower: hệ thống có 20 decision cases, không phải danh sách 3.000
   SKU vô tổ chức.
2. Chọn case “peer giảm giá mạnh”.
3. Mở SKU Decision Room, xem peer, evidence, price gap và confidence.
4. Mở Simulator, thử giữ giá và giảm 5%; hệ thống chặn phương án vi phạm
   margin floor.
5. Duyệt phương án còn hợp lệ; hệ thống tạo action plan và audit record.
6. Hỏi Copilot vì sao đề xuất này; Copilot trả lời từ đúng case context.
7. Chạy outcome review, xem before/after và ghi feedback.

Demo này chứng minh đủ chuỗi: **phát hiện → hiểu → thử → quyết định → kiểm tra
kết quả**, thay vì chỉ trình diễn một chatbot hoặc một biểu đồ.

## 11. Chạy bản MVP hiện tại

```powershell
docker compose up --build agent-api frontend
```

- Frontend: `http://localhost:5173`
- API: `http://localhost:8080`

Frontend chỉ chứa `VITE_API_BASE_URL` và token tùy chọn. DeepSeek key chỉ nằm
ở backend/agent runtime, không đưa vào browser bundle.

## 12. Tài liệu kỹ thuật

- [Kiến trúc hiện tại](docs/02-architecture.md)
- [Product Matching](docs/08-product-matching.md)
- [Market Signals](docs/09-market-signals.md)
- [Recommendation Engine](docs/10-recommendation-engine.md)
- [Agent Architecture](docs/11-agent-architecture.md)
- [API và Frontend MVP](docs/12-api-and-fe.md)
- [Roadmap kỹ thuật](docs/04-implementation-roadmap.md)
