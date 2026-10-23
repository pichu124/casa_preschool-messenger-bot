# Ảnh từ Google Drive của trường

Bot tự đồng bộ ảnh học phí, thực đơn, thời khoá biểu và cơ sở vật chất từ thư mục Drive "Ảnh cho Chatbot": Apps Script của Sheet lead liệt kê file (`type: "media"`), bot phân loại theo thư mục, tải ảnh mới hoặc đã đổi qua link tải Drive, thu nhỏ còn JPEG ≤ 1600 px vào `MEDIA_DIR` (phục vụ ở `/static/media/<id>.jpg`), xoá ảnh không còn trên Drive. Đồng bộ khi khởi động (nền), mỗi `MEDIA_SYNC_MINUTES` phút, và khi admin gõ `/capnhatanh` trong nhóm Telegram. Code: `app/media.py`; `lifespan`, `/static/media`, `GET /media`, nhánh `/capnhatanh` của `/telegram-webhook` trong `app/main.py`. Quy tắc khi nào gửi ảnh nào cho phụ huynh chưa có ở đây.

## Sub-features

- `startup-sync` khởi động với `MEDIA_SYNC_ENABLED=true` → một POST tới Apps Script (`{"type":"media","token":…}`), rồi mỗi ảnh một GET `drive.google.com/uc?export=download&id=…` (303 sang `drive.usercontent.google.com/download`); log `Media synced: 30 images, 30 downloaded, …`. Tắt (mặc định của harness) thì không có request nào, log WARNING `Media sync off` một lần.
- `classify` thư mục `HỆ QUỐC TẾ`/`HỆ SONG NGỮ` → `HỌC PHÍ THÁNG N` (fee), `THỰC ĐƠN` (menu), `CƠ SỞ <TÊN>/THỜI KHÓA BIỂU` (timetable, nhóm tuổi theo tháng từ tên file), `CƠ SỞ <TÊN>/ẢNH CƠ SỞ VẬT CHẤT` (facilities); cơ sở là khoá của hồ sơ (`Chùa Láng`, `Mỹ Đình`, `Kim Mã`). File khác: bỏ qua, nằm trong `skipped`.
- `media-endpoint` `GET /media?secret=` → `enabled`, `synced_at`, `last_error`, `total`, `counts` (fee, menu, timetable, facilities), `items` (mỗi ảnh: `kind`, `system`, `month`, `campus`, `age_min`, `age_max`, `path`, `url`), `skipped`; secret sai hoặc thiếu → 403.
- `media-static` `GET /static/media/<id>.jpg` → `200 image/jpeg`; ảnh đã xoá → 404.
- `capnhatanh` `/capnhatanh` (hoặc `/capnhatanh@<bot>`) không phải reply, từ đúng `TELEGRAM_CHAT_ID` → `{"status":"media_sync_started"}`, đồng bộ, rồi một tin Telegram `🖼 CẬP NHẬT ẢNH: …` (số ảnh mỗi loại, mỗi cơ sở, cảnh báo học phí tháng hiện tại chưa có, file bị bỏ qua). Nhóm khác → `ignored`, không request nào.
- `incremental` file không đổi (`id` + `modified`) không tải lại; file đổi tải lại; file không còn trên Drive biến khỏi danh mục và đĩa.
- `failure` Apps Script lỗi (500, `ok:false`, mạng) → danh mục cũ giữ nguyên, log ERROR không có token, tin Telegram `⚠️ Không cập nhật được ảnh (…)`.

## How to get to it (user POV)

- Người vận hành: dán script mới, deploy New version, đặt `MEDIA_SYNC_ENABLED=true` trên Render ([docs/google-sheet-leads.md](../../../../docs/google-sheet-leads.md), mục 7).
- Trường: đổi ảnh trong thư mục Drive; admin gõ `/capnhatanh` trong nhóm Telegram để cập nhật ngay và đọc tóm tắt.
- Admin: `https://<host>/media?secret=…` để xem danh mục.

## Driving it with ctl, send and curl

Preconditions:

- `ctl up --slug <slug> --env MEDIA_SYNC_ENABLED=true` in `READY`, `ctl doctor --slug <slug>` in `DOCTOR OK`; `eval "$(python3 .claude/skills/verify-casa-bot/harness/ctl.py env --slug <slug>)"`.
- Fake Apps Script trả cây thư mục thật của trường (30 ảnh, `MEDIA_FILES` trong `harness/fake_server.py`); fake Drive trả một PNG 64x48 cho mọi id.

- **Đồng bộ lúc khởi động.** `read outbox | head` → `SHEET {"type": "media", "token": "fake-sheet-token-…"} files=30`, rồi từng cặp `DRIVE GET drive.google.com/uc id=… -> http://127.0.0.1:<port>/drive.usercontent.google.com/download?…` (303) và `DRIVE GET drive.usercontent.google.com/download id=… -> <image/png, … bytes>`. `read outbox --host drive` đủ 60 dòng. `read log --grep app.media` → `Media synced: 30 images, 30 downloaded, 0 removed, 0 skipped, 0 failed`.
- **Danh mục.** `curl -s "$CASA_APP/media?secret=$CASA_SECRET"` → `total: 30`, `counts: {"fee": 2, "menu": 2, "timetable": 8, "facilities": 18}`, timetable `Kim Mã` 15–36 và 36–72, `url` là `http://127.0.0.1:<port>/static/media/<id>.jpg`. Không secret hoặc `secret=wrong` → 403.
- **Ảnh qua app.** `curl -s -o /tmp/x.jpg -w '%{http_code} %{content_type}\n' "$CASA_APP/static/media/km-tkb-2.jpg"` → `200 image/jpeg`, file là JPEG 64x48.
- **/capnhatanh.** `send tg-command /capnhatanh` → `SENT tg-command -> HTTP 200 {"status":"media_sync_started"}`, một `SHEET {"type": "media", …}`, không có `DRIVE` (không file nào đổi), `TG sendMessage … header='🖼 CẬP NHẬT ẢNH: 30 ảnh (tải mới 0, giữ nguyên 30, xoá 0)'`. Đọc đủ tin: `read outbox --host tg --full | tail -1`.
- **Drive đổi.** Chép kịch bản, đặt `media_files` là danh sách của fake bỏ một ảnh, đổi `modified` một ảnh, chuyển học phí Song ngữ sang `HỌC PHÍ THÁNG 9`, thêm `logo.png` thẳng trong `HỆ QUỐC TẾ`; `ctl scenario --slug <slug> <file>`; `send tg-command /capnhatanh` → đúng một cặp `DRIVE` (ảnh đã đổi), tin `29 ảnh (tải mới 1, giữ nguyên 28, xoá 1)`, `⚠️ Chưa có học phí tháng <tháng này>: Song ngữ (Song ngữ đang dùng tháng 9)`, `⚠️ Bỏ qua 1 file …: HỆ QUỐC TẾ/logo.png`; `curl` ảnh đã bỏ → 404, `ls $CASA_COPY/static/media/` không còn file đó.
- **Apps Script hỏng.** `fail.media: "500"` → `send tg-command /capnhatanh` → `SHEET` 500, tin `⚠️ Không cập nhật được ảnh (JSONDecodeError). Bot vẫn dùng … ảnh …`; `/media` vẫn đủ ảnh cũ, `last_error` có lý do; ảnh cũ vẫn tải được; `read log --grep "Media sync failed"` có dòng ERROR; `grep -c fake-sheet-token $CASA_EVIDENCE/app.log` → `0`.
- **Không phải nhóm admin.** `send tg-command /capnhatanh --chat-id -1000000000999` → `{"status":"ignored"}`, không có dòng outbox mới. `--bad-secret` → 403.
- **Bằng chứng.** Lệnh và dòng outbox qua `tee`; `netlog.txt` chỉ có `rewrite` tới host giả và không có `BLOCKED`.

## Gotchas

- Harness mặc định `MEDIA_SYNC_ENABLED=false` để outbox các hành trình khác không đổi; phải `--env MEDIA_SYNC_ENABLED=true` lúc `up`.
- Fake Drive không giả trang "quét virus" hay giới hạn tải của Google; ảnh lớn (14 MB của Kim Mã) chỉ thử được ở pytest (`tests/test_media.py`, Pillow thật), không qua harness.
- `static/media/` bị gitignore nên bản sao bắt đầu không có ảnh; mỗi lần `up` là tải lại đủ.
- Tóm tắt dùng tháng hiện tại theo giờ Việt Nam của máy; fake chỉ có `HỌC PHÍ THÁNG 10`, nên chạy vào tháng khác sẽ thấy cảnh báo học phí ngay từ lần đầu.
