# Đợt 3: thông tin cần bổ sung

> Đã thay bằng `docs/dot-4-can-bo-sung.md`. File này giữ lại làm lịch sử.

Code cho các mục dưới đây đã có trên nhánh, nhưng chưa chạy được ngoài đời vì thiếu file, thiếu cấu hình hoặc chờ quyết định. Bổ sung xong thì giao lại cho agent: `/team-lead làm đợt 3 theo docs/dot-3-can-bo-sung.md` (kèm file/câu trả lời).

## A. File cần gửi

- [ ] **Thực đơn mẫu**: ảnh JPG/PNG (dưới 8 MB mỗi ảnh; nhiều trang thì gửi nhiều ảnh). Agent đặt vào `static/` và gắn vào câu hỏi về thực đơn trong `data/qa_database.json`, bot gửi thẳng cho phụ huynh. Mọi file trong `static/` đều công khai.

## B. Cấu hình phải làm trước / sau khi merge vào `main` (người vận hành)

Trên Render (Environment):
- [ ] `TELEGRAM_WEBHOOK_SECRET` (chỉ chữ, số, `_`, `-`). Ngay sau deploy gọi `POST /setup-telegram-webhook?secret=<secret>`, nếu không admin không trả lời khách qua Telegram được. Dashboard và mọi lệnh admin cần `?secret=`.
- [ ] `FB_APP_SECRET` (bật kiểm chữ ký webhook Facebook).
- [ ] `LEADS_SHEET_WEBHOOK_URL`, `LEADS_SHEET_TOKEN`: tạo Google Sheet + Apps Script theo `docs/google-sheet-leads.md`.
- [ ] `CUSTOMERS_GITHUB_REPO` (tuỳ chọn): muốn giữ hồ sơ khách qua các lần deploy thì tạo repo PRIVATE, gỡ `data/customers.json` khỏi repo public, rồi đặt biến (README). Để trống thì hồ sơ mất mỗi lần Render khởi động lại.
- [ ] `FOLLOWUP_ENABLED=true` chỉ khi đã duyệt mục C2.

Trên Facebook App → Webhooks:
- [ ] Đăng ký thêm `messaging_postbacks` và `messaging_referrals` (nút Get Started, câu hỏi gợi ý, nhận diện khách từ quảng cáo), và `message_echoes` (để tin nhắc lại biết nhân viên đã tự nhắn với phụ huynh; bắt buộc trước khi bật tin nhắc lại).
- [ ] Sau deploy gọi một lần `POST /setup-messenger-profile?secret=<secret>` để cài nút Get Started và 4 câu hỏi gợi ý.

Trên GitHub (Settings → Secrets and variables → Actions), chỉ khi bật tin nhắc lại:
- [ ] Variable `FOLLOWUP_ENABLED=true`; secrets `BOT_BASE_URL` (vd `https://casa-preschool-messenger-bot.onrender.com`) và `BOT_ADMIN_SECRET` (= `TELEGRAM_WEBHOOK_SECRET`).

Bảo mật:
- [ ] **Đổi token bot Telegram và `FB_PAGE_ACCESS_TOKEN`** nếu người ngoài xem được log Render: trước bản sửa này, thư viện httpx ghi nguyên URL mọi request (có 2 token này) vào log.
- [ ] Chuyển repo GitHub sang private (hồ sơ khách cũ đang công khai trong lịch sử git). Có xoá khỏi lịch sử không (phải force-push)?
- [ ] `.env.example` chưa thêm các biến mới (`TELEGRAM_WEBHOOK_SECRET`, `CUSTOMERS_GITHUB_REPO`, `PUBLIC_BASE_URL`, `LEADS_SHEET_WEBHOOK_URL`, `LEADS_SHEET_TOKEN`, `FOLLOWUP_ENABLED`) vì luật chặn đọc `.env.*` trong `.claude/settings.json` chặn cả file mẫu: tự thêm, hoặc cho phép agent nới luật cho riêng `.env.example`.

## C. Quyết định của trường / người vận hành

1. [ ] **4 câu hỏi gợi ý (ice breakers)** đang dùng: "Học phí bao nhiêu 1 tháng ạ?", "Trường ở đâu ạ?", "Trường áp dụng chương trình gì ạ?", "Cho con học thử được không ạ?". Đổi không?
2. [ ] **Tin nhắc lại** (mặc định TẮT): tự gửi 1 tin khi phụ huynh im lặng 3–23 giờ (trong khung 8h–21h), chưa để lại SĐT, chưa hẹn. 3 mẫu trong `app/followup.py` (`TEMPLATES`):
   - chưa biết tuổi bé: hỏi tuổi bé;
   - đã biết tuổi, chưa có SĐT: xin SĐT/Zalo để tư vấn viên gửi thông tin và học phí;
   - phụ huynh đã từ chối để lại số: mời học thử 1 tuần miễn phí / tham quan (không xin số).
   Duyệt nội dung và cho phép bật? Trước khi bật: đăng ký `message_echoes` (mục B) và tắt tin tự động của Page trong Meta Business Suite (Instant Reply, Away message) — các tin này bị coi là nhân viên đã nhắn nên khách sẽ không được nhắc.
3. [ ] **Nút trả lời nhanh** (nhãn → câu bot hiểu): Học phí / Chương trình học / Cơ sở gần nhà / Đặt lịch tham quan; Dưới 2 tuổi / 2 – 3 tuổi / 3 – 4 tuổi / 4 – 6 tuổi; Chùa Láng / Mỹ Đình / Kim Mã; Buổi sáng / Buổi chiều (hẹn tham quan); Tuần này / Tuần sau (học thử). Đổi không?
4. [ ] Ví dụ CARE trong prompt gợi ý hệ Song ngữ Kim Mã khi phụ huynh muốn tối ưu chi phí. Trường có muốn bot gợi ý như vậy không?
5. [ ] Khi nào tư vấn lại xe bus (và tuyến/phí/ưu đãi hiện hành).
6. [ ] "Bỏ phần workshop" đã được hiểu là bỏ workshop của cô Phan Thúy. Câu trả lời về sự kiện chung ("Family Day, workshop, lễ hội…") vẫn còn chữ "workshop". Có bỏ luôn chữ này không?

## D. Dữ kiện cần trường xác nhận

- [ ] Kim Mã có học Cambridge Early Years không? Diện tích lớp ở Kim Mã?
- [ ] Có cho đóng học phí theo tháng không (hiện chỉ biết quý / 6 tháng / 12 tháng)?
- [ ] Camera: phụ huynh xem tại văn phòng "bất kỳ lúc nào trong giờ hành chính" hay "khi có sự việc cụ thể, theo quy trình"?
- [ ] "Cư dân tòa nhà" là cư dân tòa nào (Hongkong Tower, FLC…)?
- [ ] Dữ kiện giữ từ dữ liệu cũ, chưa có trong kịch bản mới: bảo lưu tối thiểu 1 – tối đa 6 tháng; hạn đóng phí 5 ngày làm việc đầu quý; báo nghỉ trước 7:00 để trừ tiền ăn; nhập học giữa tháng tính theo ngày.
- [ ] Số năm hoạt động dùng con số nào ("gần 10 năm" hay "hơn 10 năm")?

## E. Kỹ thuật cần người có quyền

- [ ] SĐT bot nhận: chỉ số Việt Nam dạng `0…` hoặc `+84…` (lấy số đầu tiên nếu phụ huynh cho nhiều số). Không nhận số nước ngoài, số thiếu số 0 đầu ("912 345 678") hay viết tách quá lạ ("0912 - 345 - 678"). Có cần nới không?
- [ ] Model Groq `deepseek-r1-distill-llama-70b` có thể đã ngừng: kiểm tra trên console Groq, đổi model nếu cần.
- [ ] Chạy `.venv/bin/python scripts/eval_chat.py` với một API key AI để chấm hội thoại thật (bot đã được test với model giả, chưa với model thật).
- [ ] Sau deploy, kiểm trên Messenger thật: nút trả lời nhanh, nút gửi SĐT, câu hỏi gợi ý, tin từ quảng cáo; một lead thật xuất hiện trong nhóm Telegram và Google Sheet.
