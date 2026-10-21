# File tĩnh, Messenger profile và đăng ký webhook

Ảnh trong Q&A (vd thực đơn mẫu) được app phục vụ ở `/static/<file>` để Messenger tải về. Admin đăng ký nút Get Started và bốn ice breaker cho Page bằng `/setup-messenger-profile`, đăng ký webhook Telegram bằng `/setup-telegram-webhook`, và Facebook xác minh webhook bằng `GET /webhook`. Code: `app.mount("/static", …)`, `setup_*`, `verify_webhook` trong `app/main.py`; `set_messenger_profile`, `ICE_BREAKERS` trong `app/messenger.py`.

## Sub-features

- `static` `GET /static/<file>` → file trong `static/` của repo; `[IMAGES:static/x]` thành `PUBLIC_BASE_URL/static/x`.
- `messenger-profile` `POST /setup-messenger-profile` → Graph `POST /v21.0/me/messenger_profile` với `get_started.payload = GET_STARTED` và `ice_breakers` (`IB_1`…`IB_4`); trả về JSON của Graph.
- `telegram-webhook-setup` `POST /setup-telegram-webhook` → Telegram `setWebhook` với `url = PUBLIC_BASE_URL/telegram-webhook` và `secret_token = TELEGRAM_WEBHOOK_SECRET`.
- `fb-verify` `GET /webhook?hub.mode=subscribe&hub.verify_token=…&hub.challenge=…` → trả challenge dạng text khi token đúng, 403 khi sai.

## How to get to it (user POV)

- Phụ huynh: thấy ảnh trong Messenger (Messenger tải URL `/static/…`); thấy nút Bắt đầu và các câu hỏi gợi ý khi mở cuộc trò chuyện mới.
- Admin: `curl -X POST "https://<host>/setup-messenger-profile?secret=…"` và `…/setup-telegram-webhook?secret=…` sau mỗi lần đổi URL hoặc ice breaker.
- Facebook: gọi `GET /webhook` khi admin lưu webhook trong Meta for Developers.

## Driving it with curl

Preconditions:

- `ctl doctor --slug <slug>` OK; `eval "$(python3 .claude/skills/verify-casa-bot/harness/ctl.py env --slug <slug>)"`.

- **File tĩnh.** `curl -s -o /dev/null -w '%{http_code}\n' "$CASA_APP/static/.gitkeep"` → `200`; `…/static/khong-co.jpg` → `404`. Với ảnh mà thay đổi thêm vào `static/` và Q&A: lấy URL từ dòng `FB … IMAGE <url>` của `send`, `curl -s -o /dev/null -w '%{http_code} %{content_type}\n' <url>` → `200 image/…`.
- **Messenger profile.** `curl -s -X POST "$CASA_APP/setup-messenger-profile?secret=$CASA_SECRET"` → `{"result":"success"}`; `read outbox --host fb | tail -1` → `FB messenger_profile {"get_started": {"payload": "GET_STARTED"}, "ice_breakers": [{"locale": "default", "call_to_actions": [... "IB_1" … "IB_4"]}]}`.
- **Ice breaker đã đăng ký hoạt động.** Với từng payload trong body vừa gửi: `send postback 9000000000000061 IB_2` → model nhận đúng câu hỏi của nút, `ICE_BREAKERS["IB_2"]` trong `app/messenger.py` (`read outbox --host ai --full | tail -1` chứa "Trường nhận bé từ bao nhiêu tháng?").
- **Webhook Telegram.** `curl -s -X POST "$CASA_APP/setup-telegram-webhook?secret=$CASA_SECRET"` → JSON của Telegram giả; `read outbox --host tg | tail -1` → `setWebhook {"url": "http://127.0.0.1:<port>/telegram-webhook", "secret_token": "fake-admin-<run_id>"}`.
- **Xác minh webhook Facebook.** `curl -s "$CASA_APP/webhook?hub.mode=subscribe&hub.verify_token=$CASA_VERIFY_TOKEN&hub.challenge=12345"` → `12345`; với `hub.verify_token=sai` → `{"detail":"Verification failed"}` (403).
- **Bằng chứng.** Lệnh curl và dòng outbox qua `tee`.

## Gotchas

- `static/` trong repo chỉ có `.gitkeep`; ảnh Q&A thật được thêm theo `docs/`. Q&A trỏ tới ảnh chưa có thì Graph API thật sẽ không tải được, còn Graph giả vẫn nhận: phải `curl` URL ảnh để chứng minh.
- `PUBLIC_BASE_URL` của harness là `http://127.0.0.1:<port>` nên URL ảnh và `setWebhook.url` mang port của run; ở production là URL Render.
- Graph giả luôn trả `{"result":"success"}` cho messenger profile; nó không kiểm giới hạn của Facebook (tối đa 4 ice breaker, độ dài câu). Thay đổi chạm `ICE_BREAKERS` thì kiểm body trong outbox theo tài liệu Messenger Platform.
