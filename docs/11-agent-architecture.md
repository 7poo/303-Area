# Market Intelligence Copilot Agent

## Quyết định kiến trúc

Agent là lớp điều phối phía trên các output batch Stage 1–4. DeepSeek chỉ làm
route reasoning, chọn tool và diễn giải; database không bao giờ được đưa trực
tiếp cho model.

```text
User request
    │
    ▼
Safety gate ── blocked injection ──► safe refusal + trace
    │
    ▼
Route harness ──► context builder (session + explicit memory)
    │
    ▼
DeepSeek chat/completions ◄── allow-listed tool schemas
    │                         │
    │                         └── strict args + read-only DuckDB queries
    ▼
Answer validator + secret redaction + evidence trace
```

## DeepSeek adapter

`src/deepseek_client.py` dùng endpoint OpenAI-compatible:

Theo [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion)
và [Tool Calls guide](https://api-docs.deepseek.com/guides/tool_calls), request
dùng `messages`, function tools và tool-call loop; ứng dụng vẫn phải validate
arguments trước khi thực thi.

- Base URL mặc định `https://api.deepseek.com`.
- Endpoint `/chat/completions`.
- Model mặc định `deepseek-chat`, có thể đổi bằng `DEEPSEEK_MODEL`.
- Function calling gửi schema tool; harness vẫn validate arguments vì model có
  thể sinh JSON không hợp lệ.
- Retry tối đa 2 lần, timeout 45 giây, giới hạn 4 vòng và 6 tool calls.

Biến môi trường:

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

## Route harness

Các route v0.1:

- `recommendation`: lấy recommendation card và evidence.
- `competitor_alerts`: lấy cảnh báo theo SKU.
- `sku_analysis`: lấy signal và peers.
- `product_search`: tìm SKU theo tên trong một quốc gia.
- `market_overview` / `general_market_qa`: route mở rộng cho API/UI.

Route được xác định deterministic trước khi gọi model để giới hạn context và
tool. Mỗi response trả `route`, `trace`, `model` và trạng thái safety.

## Tool contract

Tool hiện tại đều read-only và allow-list:

`get_product_snapshot`, `get_market_signals`, `get_peers`,
`get_competitor_alerts`, `get_recommendation`, `search_products`.

Không có tool chạy SQL tùy ý, thay đổi giá, ghi DB thị trường hoặc gọi URL do
model cung cấp. Mọi `country_code`, ID, limit và unknown argument đều được
validate trước khi chạy DuckDB.

## Context và memory

- Short-term: 6 turn gần nhất theo `user_id + session_id`.
- Long-term: memory explicit bằng lệnh `ghi nhớ: ...`; retrieval lexical có
  giới hạn top-5.
- SQLite tại `warehouse/agent_memory.sqlite`, tách khỏi market warehouse.
- Secret được redact trước khi lưu. Tool/memory được bọc trong
  `<UNTRUSTED_DATA>` để model không coi dữ liệu sản phẩm là instruction.
- `agent_traces` lưu request id, route, model, tool trace và safety metadata để
  audit/replay.
- Có thể thay lexical retrieval bằng embedding store sau khi có privacy policy.

## Prompt-injection defense

1. Detect các mẫu `ignore previous instructions`, yêu cầu lộ system prompt/API
   key, fake role tags và arbitrary tool/code.
2. Chặn trước khi gọi DeepSeek và không lưu request bị chặn vào memory.
3. System prompt cấm tin tool/memory như instruction, cấm lộ secrets.
4. Tool schema `additionalProperties=false`, required fields và allow-list.
5. Route policy giới hạn tool theo intent; shop scope kiểm tra lại trong registry,
   không tin scope do model truyền vào.
6. Giới hạn số vòng/tool calls; lỗi tool trở thành dữ liệu lỗi, không retry vô
   hạn.
7. Redact API key/Bearer token ở output và memory.

Production mode yêu cầu `AGENT_API_TOKEN` và `AGENT_SHOP_SCOPE` dạng
`vn:shop_id,id:shop_id`; vẫn cần secret manager, rate limit và red-team
benchmark. Development HTTP wrapper hiện đã có in-process rate limiter qua
`AGENT_RATE_LIMIT`; production nhiều replica nên chuyển limiter sang Redis/API
gateway.

## Chạy local

Không có API key, harness chạy deterministic mode để kiểm tra dữ liệu:

```powershell
$env:DEEPSEEK_API_KEY=""
python -m src.agent "đề xuất cho vn shop_id=173513432 item_id=40662233042"
```

Khi có key, cùng lệnh sẽ dùng DeepSeek tool loop. Không commit key vào repo.

Chạy qua Docker:

```powershell
$env:AGENT_MESSAGE="đề xuất cho vn shop_id=173513432 item_id=40662233042"
docker compose run --rm agent
```

## Tiêu chí nghiệm thu agent

- Route deterministic và trace được từng tool call.
- Tool arguments invalid/arbitrary SQL bị chặn.
- Prompt injection bị từ chối trước provider call.
- Context có session memory nhưng data vẫn được đánh dấu untrusted.
- Không có API key thì fallback rõ ràng, không giả mạo câu trả lời LLM.
- Có test harness offline để tránh phụ thuộc mạng/provider trong CI.
