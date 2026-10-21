# Đợt 4: thông tin cần bổ sung

Thay cho `docs/dot-3-can-bo-sung.md` (các mục đợt 3 đã xong được bỏ; mục còn mở chuyển sang đây). Bổ sung xong thì giao lại cho agent: `/team-lead làm đợt 4 theo docs/dot-4-can-bo-sung.md` (kèm file/câu trả lời).

## A. File cần gửi

- [ ] **Thực đơn mẫu**: ảnh JPG/PNG (dưới 8 MB mỗi ảnh). Agent đặt vào `static/` và gắn vào câu hỏi về thực đơn; bot gửi thẳng cho phụ huynh. Mọi file trong `static/` đều công khai.

## B. Cấu hình sau khi merge vào `main` (người vận hành)

Render (Environment):
- [ ] `TELEGRAM_WEBHOOK_SECRET` (chỉ chữ, số, `_`, `-`) rồi gọi `POST /setup-telegram-webhook?secret=<secret>`. Chưa làm thì admin trả lời qua Telegram không tới khách, dashboard bị khoá.
- [ ] `FB_APP_SECRET`.
- [ ] `LEADS_SHEET_WEBHOOK_URL`, `LEADS_SHEET_TOKEN` theo `docs/google-sheet-leads.md`.
- [ ] `CUSTOMERS_GITHUB_REPO` (tuỳ chọn, repo PRIVATE) nếu muốn giữ hồ sơ khách qua các lần deploy.

Facebook:
- [ ] Webhooks: đăng ký thêm `messaging_postbacks`, `messaging_referrals`, `message_echoes`.
- [ ] Gọi `POST /setup-messenger-profile?secret=<secret>` sau MỖI lần deploy có đổi câu hỏi gợi ý (đợt này đã đổi sang 4 câu của trường).

Bảo mật:
- [ ] Đổi token bot Telegram và `FB_PAGE_ACCESS_TOKEN` nếu người ngoài xem được log Render (bản cũ ghi 2 token này vào log).
- [ ] Chuyển repo GitHub sang private (hồ sơ khách cũ còn trong lịch sử git); có xoá khỏi lịch sử không (cần force-push).
- [ ] `.env.example` chưa thêm biến mới (`TELEGRAM_WEBHOOK_SECRET`, `CUSTOMERS_GITHUB_REPO`, `PUBLIC_BASE_URL`, `LEADS_SHEET_WEBHOOK_URL`, `LEADS_SHEET_TOKEN`, `FOLLOWUP_ENABLED`) vì luật chặn đọc `.env.*` trong `.claude/settings.json` chặn cả file mẫu: tự thêm, hoặc cho phép agent nới luật cho riêng `.env.example`.

## C. Quyết định của trường

1. [ ] **Mẫu tin nhắc lại thứ 3** ("Đã tư vấn tương đối đủ nhưng PH dừng trao đổi") hiện gửi cho phụ huynh **đã từ chối để lại SĐT**. "Tư vấn tương đối đủ" nghĩa là gì để bot nhận ra (vd đã biết tuổi + cơ sở + đã hỏi học phí)? Hay giữ như hiện tại?
2. [ ] **Bật tin nhắc lại** khi nào? (Hiện TẮT.) Trước khi bật: đăng ký `message_echoes` và tắt Instant Reply/Away message của Page.
3. [x] ~~SĐT nước ngoài viết kèm số 0 sau mã nước~~ (vd "+886 0912 345 678"): đã sửa, bot lưu nguyên số nước ngoài, không còn nhận nhầm thành số Việt Nam.
4. [ ] **SĐT theo đầu số cũ** (`01x…` 11 số, máy bàn `04…`) không còn được nhận vì đã đổi đầu số từ 2018. Có cần nhận không?

## D. Dữ kiện cần trường xác nhận

- [ ] Kim Mã có học Cambridge Early Years không? Diện tích lớp ở Kim Mã?
- [ ] Có cho đóng học phí theo tháng không (hiện chỉ biết quý / 6 tháng / 12 tháng)?
- [ ] Camera: xem tại văn phòng "bất kỳ lúc nào trong giờ hành chính" hay "khi có sự việc cụ thể, theo quy trình"?
- [ ] "Cư dân tòa nhà" là cư dân tòa nào (Hongkong Tower, FLC…)?
- [ ] Dữ kiện giữ từ dữ liệu cũ: bảo lưu tối thiểu 1 – tối đa 6 tháng; hạn đóng phí 5 ngày làm việc đầu quý; báo nghỉ trước 7:00 để trừ tiền ăn; nhập học giữa tháng tính theo ngày.
- [ ] Số năm hoạt động: "gần 10 năm" hay "hơn 10 năm"?

## E. Kỹ thuật

- [x] ~~Model AI đã ngừng~~: đã thay model Groq `deepseek-r1-distill-llama-70b` và `llama-3.3-70b-versatile`, DeepSeek `deepseek-chat`, Gemini `gemini-2.0-flash`. Gemini chuyển sang thư viện `google-genai`. Tên model đặt được qua biến môi trường (README, mục "Model AI").
- [ ] **Xác minh tên model mới bằng API key thật** (phiên agent không có key): `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` (Groq), `deepseek-flash`, `gemini-3.5-flash` (khả năng sai cao nhất). Xem danh sách model ở trang console/`/models` của từng nhà cung cấp; tên sai thì đặt biến `*_MODEL` trên Render, không cần sửa code.
- [ ] OpenAI `gpt-4o-mini` ngừng ngày **2027-01-14**: trước mốc này chọn model thay và đặt `OPENAI_MODEL` trên Render.
- [ ] Chạy `.venv/bin/python scripts/eval_chat.py` với một API key AI để chấm hội thoại thật (nhất là sau khi đổi model).
- [ ] Sau deploy, thử trên Messenger thật: nút trả lời nhanh, nút gửi SĐT, câu hỏi gợi ý, tin từ quảng cáo; một lead thật vào nhóm Telegram và Google Sheet.
- [x] ~~`/qa-learned` gần như luôn rỗng~~: đã sửa. Cặp Q&A admin dạy qua Telegram giờ được đánh dấu nguồn `admin` và hiện trong `/qa-learned`.
- [ ] Mỗi lần admin trả lời qua Telegram, bot tự đẩy `data/qa_database.json` lên nhánh `main`. Commit có `[skip deploy]` nên Render **không** deploy lại (đã kiểm tài liệu Render). Còn lại một câu hỏi: repo đang public nên câu trả lời admin dạy cho bot cũng công khai. Có ổn không, hay chuyển repo sang private (xem mục B)?
