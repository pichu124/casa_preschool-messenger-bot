# Chuyển bot từ Render sang VPS

Kế hoạch, chưa làm. Ghi lại ngày 22/10/2026 để đọc khi quyết định chuyển. Mục 1 là việc sửa code (giao agent); mục 0 và 2–5 là việc của người vận hành, agent viết hướng dẫn chi tiết khi bắt đầu.

## Vì sao cân nhắc chuyển

| | Render Free (hiện tại) | Render Starter | VPS |
|---|---|---|---|
| Chi phí | 0đ | khoảng 7 USD/tháng | khoảng 100–200 nghìn/tháng gói nhỏ |
| Ngủ khi vắng tin (tin đầu chờ ~50 giây) | Có | Không | Không |
| Hồ sơ phụ huynh mất khi khởi động lại/deploy | Có | Có (trừ khi mua ổ đĩa Render hoặc đặt `CUSTOMERS_GITHUB_REPO`) | Không |
| Tự deploy khi push `main`, HTTPS | Có sẵn | Có sẵn | Phải tự dựng |
| Ai lo máy sập, cập nhật bảo mật, ổ đầy | Render | Render | Người vận hành |

Nên chuyển khi có người theo dõi được máy chủ, hoặc khi đã thuê VPS trong nước cho app `casa-mamnon` (bot rất nhẹ, chạy chung máy đó được). Chưa có thì ở lại Render và đặt `CUSTOMERS_GITHUB_REPO` (README, mục biến môi trường).

Lưu ý pháp lý (không phải kết luận): bot giữ dữ liệu cá nhân (SĐT phụ huynh, tên/tuổi bé), hiện đi qua Render ở Singapore, nhà cung cấp AI, Telegram và Google Sheet. Nếu trường chọn VPS trong nước cho `casa-mamnon` vì Nghị định 13/2023 / Luật 91/2025, hỏi người tư vấn pháp lý xem bot có cần theo cùng hướng không.

## 0. Chuẩn bị (người vận hành)

- VPS: 1 vCPU, 1 GB RAM, 20 GB ổ là đủ cho riêng bot. Ubuntu LTS.
- Tên miền hoặc tên miền con (vd `bot.<tên-miền-của-trường>`) trỏ bản ghi A về IP của VPS. Facebook bắt buộc webhook HTTPS có chứng chỉ hợp lệ, không dùng IP trần được.
- Đăng nhập SSH bằng khoá, tắt đăng nhập mật khẩu.

## 1. Sửa code trước khi chuyển (agent làm, qua quy trình kiểm như mọi lần)

Trên Render ổ đĩa bị xoá mỗi lần deploy nên các vấn đề này không lộ ra; trên VPS thì có:

- Bot ghi dữ liệu thẳng vào thư mục code: `data/customers.json`, `data/qa_database.json`, `data/pending_escalations.json`, `data/analytics.jsonl`, `data/escalation_log.json`. Hai file đầu đang được git theo dõi, nên `git pull` trên VPS sẽ xung đột hoặc ghi đè dữ liệu thật.
  - Thêm biến `DATA_DIR` (vd `/var/lib/casa-bot`) cho mọi file dữ liệu. Lần chạy đầu: chép `qa_database.json` từ repo sang `DATA_DIR`, sau đó dùng bản trong `DATA_DIR`.
- Bot tự đẩy `qa_database.json` (và hồ sơ khách nếu có `CUSTOMERS_GITHUB_REPO`) lên GitHub với commit `[skip deploy]`. Quy trình tự deploy trên VPS phải bỏ qua các commit này, nếu không mỗi lần admin dạy bot là một lần khởi động lại.
- Thêm vào repo: file dịch vụ `systemd` (hoặc `docker-compose.yml`, repo đã có `Dockerfile`), cấu hình Caddy, workflow GitHub Actions tự deploy, và tài liệu cài đặt từng bước.

## 2. Dựng VPS (người vận hành theo tài liệu ở mục 1, khoảng 1–2 giờ)

1. Cập nhật hệ điều hành, bật tự cập nhật bảo mật (`unattended-upgrades`). Tường lửa (`ufw`) chỉ mở cổng 22, 80, 443.
2. Cài Python 3.12 và môi trường ảo, hoặc Docker.
3. Tạo user riêng cho bot. Biến môi trường để trong `/etc/casa-bot.env`, quyền `600`, chép từ trang Environment của Render. Không đưa file này vào git, không dán vào chat.
4. `systemd` chạy `uvicorn app.main:app --host 127.0.0.1 --port 8000`, tự chạy lại khi lỗi và khi khởi động máy.
5. Caddy làm cổng vào: tự xin và gia hạn HTTPS, chuyển tiếp `https://bot.<tên-miền>` vào `127.0.0.1:8000`.
6. Tự deploy: GitHub Actions SSH vào VPS khi push `main` (bỏ qua `[skip deploy]`): kéo code, cài thư viện, khởi động lại dịch vụ.

## 3. Chuyển dữ liệu

- Lấy hồ sơ phụ huynh mới nhất: tải `/customers?secret=…` (JSON) trên Render, hoặc lấy từ repo `CUSTOMERS_GITHUB_REPO` nếu đã đặt. Chép vào `DATA_DIR/customers.json`. Đây là dữ liệu cá nhân: không gửi qua chat, không để lại bản sao trên máy cá nhân sau khi chép xong.
- Thử trên VPS bằng `POST https://bot.<tên-miền>/test-chat?secret=…` trước khi nhận khách thật.

## 4. Chuyển luồng thật (khoảng 15 phút, giờ vắng)

Render vẫn chạy song song tới khi xong.

1. Facebook (developers.facebook.com → app → Webhooks): đổi Callback URL sang `https://bot.<tên-miền>/webhook`, giữ nguyên Verify Token.
2. Telegram: `POST https://bot.<tên-miền>/setup-telegram-webhook?secret=<TELEGRAM_WEBHOOK_SECRET>`.
3. Trên VPS: đặt `PUBLIC_BASE_URL=https://bot.<tên-miền>` (đường dẫn ảnh trong `static/`, vd thực đơn mẫu).
4. GitHub → Settings → Secrets and variables → Actions: đổi `BOT_BASE_URL` (tin nhắc lại) sang tên miền mới.
5. Google Sheet: không đổi gì.
6. Thử: tin thường, gửi SĐT (thẻ Telegram + hàng Sheet), câu cần chuyển tư vấn viên rồi admin trả lời qua Telegram. Đạt thì Suspend dịch vụ trên Render; để vài ngày rồi mới xoá.

Quay lui nếu có lỗi: đổi Callback URL Facebook và gọi lại `/setup-telegram-webhook` trên Render (khoảng 2 phút).

## 5. Vận hành sau khi chuyển

- Sao lưu `DATA_DIR` mỗi ngày ra ngoài máy (repo private hoặc Google Drive). Ổ hỏng mà không có bản sao là mất hết hồ sơ.
- UptimeRobot (miễn phí) gọi `https://bot.<tên-miền>/` (trang kiểm tra sức khoẻ của bot) 5 phút một lần, báo khi bot sập.
- Xoay vòng log (`journald` hoặc `logrotate`) để ổ không đầy.
- Hằng tháng: xem cập nhật bảo mật, dung lượng ổ, Caddy còn gia hạn HTTPS.
- `CUSTOMERS_GITHUB_REPO` khi đó chỉ còn vai trò sao lưu.
