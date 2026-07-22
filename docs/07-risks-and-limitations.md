# 7. Rủi ro và giới hạn

## Giới hạn dữ liệu hiện tại

- Chỉ có 3 ngày snapshot.
- Không có order-level data.
- `history_sold_value` có thể bị làm tròn hoặc cắt ngưỡng.
- `monthly_sold_value` là proxy cửa sổ trượt.
- `is_ad` luôn false.
- `is_sold_out` luôn false.
- Không có giá vốn, lợi nhuận hoặc subsidy.
- Không có traffic, impression, click, conversion.
- Không có cờ shop nội bộ.
- Độ phủ sản phẩm giữa các shop không đồng đều.
- Việt Nam và Indonesia lệch ngành hàng, không nên gộp model ngây thơ.

## Rủi ro sản phẩm

### Khuyến nghị nhầm sản phẩm

Tên sản phẩm có thể chứa combo, quy cách hoặc biến thể khác nhau. Cần hiển thị
điểm tương đồng, cho phép chỉnh sửa và không tự động áp dụng recommendation.

### Sao chép đối thủ không có lợi nhuận

Không có giá vốn nên recommendation về giá chỉ là recommendation cạnh tranh.
Giá sàn phải do người dùng nhập hoặc lấy từ hệ thống thương mại nội bộ.

### Nhầm tương quan với nguyên nhân

Sản phẩm giảm giá đồng thời có thể được tăng traffic, tham gia campaign hoặc
được ưu tiên hiển thị. Hệ thống phải dùng từ “quan sát thấy” và “gợi ý”, không
dùng “chứng minh rằng” khi chưa có thử nghiệm.

### Dữ liệu marketplace thay đổi

Schema, cách hiển thị giá bán và cách làm tròn sold count của sàn có thể thay
đổi. Cần version hóa schema và chạy quality checks sau mỗi lần ingest.

## Biện pháp giảm rủi ro

- Lưu `source_file` trong các bảng chuẩn hóa.
- Lưu model/rule version trong các bảng matching và recommendation ở Ngày 2–4.
- Hiển thị thời điểm snapshot cho mọi insight.
- Dùng confidence threshold và fallback `insufficient_evidence`.
- Yêu cầu người dùng duyệt hành động.
- Duy trì bộ cặp match được kiểm duyệt thủ công.
- Agent chỉ dùng read-only allow-listed tools, route policy và shop scope.
- Prompt/memory/tool data được đánh dấu untrusted; có prompt-injection gate và
  secret redaction.
- `pipeline_runs` ngăn agent đọc stage đang chạy hoặc thất bại.
- Production API phải cấu hình bearer token, tenant scope, rate limit và audit
  trace trước khi public.
- Câu trả lời LLM vẫn là lớp diễn giải; `recommendations` rule engine là nguồn
  quyết định có cấu trúc và luôn cần người dùng duyệt.
