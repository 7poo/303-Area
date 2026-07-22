# 1. Phạm vi sản phẩm

## Bối cảnh

Các shop thương mại điện tử cần biết sản phẩm nào của đối thủ tương đương,
đối thủ đang thay đổi giá/khuyến mãi ra sao và nên phản ứng thế nào. Dữ liệu
nguồn là các snapshot sản phẩm Shopee theo shop, quốc gia và ngày.

## Người dùng mục tiêu

- E-commerce manager theo dõi thị trường.
- Category manager phụ trách một ngành hàng.
- Pricing/promotion analyst.
- Seller hoặc brand manager cần kiểm tra phản ứng cạnh tranh.

## Giá trị cần chứng minh

Người dùng chọn một SKU tham chiếu và trong một màn hình có thể:

1. Tìm được nhóm sản phẩm cạnh tranh thực sự tương đồng.
2. Hiểu giá, discount, voucher và sức bán proxy của nhóm đó.
3. Nhìn thấy thay đổi mới nhất của đối thủ.
4. Nhận một khuyến nghị có lý do, dữ liệu dẫn chứng và mức tin cậy.

## Use case MVP

### UC-01 — Tìm sản phẩm tương đồng

Input: `country_code`, `shop_id`, `item_id`.

Output: top-K sản phẩm đối thủ, điểm tương đồng, lý do match và các thuộc tính
khác biệt như brand, quy cách, giá.

### UC-02 — Theo dõi hành động đối thủ

Input: SKU hoặc category.

Output: timeline thay đổi giá, discount, promotion và voucher; cảnh báo các
thay đổi vượt ngưỡng cấu hình.

### UC-03 — Khuyến nghị phản ứng cạnh tranh

Input: sản phẩm tham chiếu, giá vốn tùy chọn, margin tối thiểu tùy chọn.

Output: giữ giá, giảm giá, dùng voucher hoặc không phản ứng; luôn hiển thị
bằng chứng và cảnh báo nếu thiếu dữ liệu.

## Ngoài phạm vi MVP

- Tối ưu tồn kho vì chưa có tồn thực tế, inbound và lead time.
- Tối ưu quảng cáo vì chưa có spend, impression, click, conversion và ROAS.
- Khẳng định quan hệ nhân quả giữa giảm giá và doanh số.
- Tự động thay đổi giá trên sàn.

## Nguyên tắc sản phẩm

- Evidence-first: mọi khuyến nghị phải truy được về snapshot/event cụ thể.
- Human-in-the-loop: người dùng duyệt hành động trước khi áp dụng.
- Confidence-aware: có thể trả về “chưa đủ dữ liệu để khuyến nghị”.
- Tách rõ số liệu quan sát, proxy và giả định người dùng nhập vào.
