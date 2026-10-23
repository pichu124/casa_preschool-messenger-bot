# Ảnh từ Google Drive của trường

Bot tự đồng bộ ảnh học phí, thực đơn, thời khoá biểu và cơ sở vật chất từ thư mục Drive "Ảnh cho Chatbot": Apps Script của Sheet lead liệt kê file (`type: "media"`), bot phân loại theo thư mục, tải ảnh mới hoặc đã đổi qua link tải Drive, thu nhỏ còn JPEG ≤ 1600 px vào `MEDIA_DIR` (phục vụ ở `/static/media/<id>.jpg`), xoá ảnh không còn trên Drive. Đồng bộ khi khởi động (nền), mỗi `MEDIA_SYNC_MINUTES` phút, và khi admin gõ `/capnhatanh` trong nhóm Telegram. Code: `app/media.py`; `lifespan`, `/static/media`, `GET /media`, nhánh `/capnhatanh` của `/telegram-webhook` trong `app/main.py`. Gửi ảnh cho phụ huynh: `_plan_images`, `_media_note`, `_send_reply_with_images` trong `app/main.py`, dòng `[HỆ THỐNG]` do `media_note` của `app/ai_engine.py` viết; luật đầy đủ ở [docs/quyet-dinh-noi-dung.md](../../../../docs/quyet-dinh-noi-dung.md), mục "Ảnh gửi phụ huynh".

## Sub-features

- `startup-sync` khởi động với `MEDIA_SYNC_ENABLED=true` → một POST tới Apps Script (`{"type":"media","token":…}`), rồi mỗi ảnh một GET `drive.google.com/uc?export=download&id=…` (303 sang `drive.usercontent.google.com/download`); log `Media synced: 30 images, 30 downloaded, …`. Tắt (mặc định của harness) thì không có request nào, log WARNING `Media sync off` một lần.
- `classify` thư mục `HỆ QUỐC TẾ`/`HỆ SONG NGỮ` → `HỌC PHÍ THÁNG N` (fee), `THỰC ĐƠN` (menu), `CƠ SỞ <TÊN>/THỜI KHÓA BIỂU` (timetable, nhóm tuổi theo tháng từ tên file), `CƠ SỞ <TÊN>/ẢNH CƠ SỞ VẬT CHẤT` (facilities); cơ sở là khoá của hồ sơ (`Chùa Láng`, `Mỹ Đình`, `Kim Mã`). File khác: bỏ qua, nằm trong `skipped`.
- `media-endpoint` `GET /media?secret=` → `enabled`, `synced_at`, `last_error`, `total`, `counts` (fee, menu, timetable, facilities), `items` (mỗi ảnh: `kind`, `system`, `month`, `campus`, `age_min`, `age_max`, `path`, `url`), `skipped`; secret sai hoặc thiếu → 403.
- `media-static` `GET /static/media/<id>.jpg` → `200 image/jpeg`; ảnh đã xoá → 404.
- `capnhatanh` `/capnhatanh` (hoặc `/capnhatanh@<bot>`) không phải reply, từ đúng `TELEGRAM_CHAT_ID` → `{"status":"media_sync_started"}`, đồng bộ, rồi một tin Telegram `🖼 CẬP NHẬT ẢNH: …` (số ảnh mỗi loại, mỗi cơ sở, cảnh báo học phí tháng hiện tại chưa có, file bị bỏ qua). Nhóm khác → `ignored`, không request nào.
- `incremental` file không đổi (`id` + `modified`) không tải lại; file đổi tải lại; file không còn trên Drive biến khỏi danh mục và đĩa.
- `send-fee` phụ huynh hỏi học phí (tin này hoặc trước), bot biết tuổi bé + cơ sở → sau `TEXT` là `IMAGE …/static/media/<học phí của hệ>.jpg` (tháng hiện tại; chưa có thì tháng gần nhất, kèm một tin Telegram `⚠️ Chưa có ảnh học phí mới tháng …` mỗi hệ mỗi ngày); mỗi tháng 1 lần. Không để số khi được xin hoặc đã từ chối mà vẫn hỏi học phí, biết cơ sở → gửi ảnh, không `TG` thẻ chuyển tư vấn viên.
- `send-timetable` hỏi chương trình (chủ đề) hoặc tin có "Cambridge"/"thời khóa biểu"/"thời gian biểu"/"TKB"/"lịch học" (không tính "lịch học thử") → `IMAGE` thời khoá biểu theo cơ sở và tuổi; chưa biết cơ sở thì Mỹ Đình (hồ sơ quan tâm hệ Song ngữ thì Kim Mã), chưa biết tuổi thì nhóm 3–5 tuổi.
- `send-facilities` hỏi cơ sở vật chất, biết cơ sở → 4 `IMAGE` của cơ sở đó; chưa biết thì chờ tin nói cơ sở.
- `send-menu` hỏi thực đơn → `IMAGE` thực đơn của hệ (chưa biết: Quốc tế) thay cho `static/thuc-don-mau.jpg` của Q&A.
- `status-line` mỗi lời gọi chat có các dòng `- [HỆ THỐNG] …` cuối khối nhắc nhở: "Sau câu trả lời này hệ thống gửi ảnh …" khi chắc chắn gửi (dòng thời khoá biểu kèm thêm "… KHÔNG [ESCALATE] …" cho câu hỏi lịch học trong tuần), "Nếu phụ huynh hỏi …: sau câu trả lời hệ thống gửi ảnh …" khi tuỳ chủ đề của tin. Tắt đồng bộ → không có dòng nào.
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
- **Drive đổi.** Chép kịch bản, đặt `media_files` là danh sách của fake bỏ một ảnh, đổi `modified` một ảnh, chuyển học phí Song ngữ sang `HỌC PHÍ THÁNG 9`, thêm `logo.png` thẳng trong `HỆ QUỐC TẾ`; `ctl scenario --slug <slug> <file>`; `send tg-command /capnhatanh` → đúng một cặp `DRIVE` (ảnh đã đổi), tin `29 ảnh (tải mới 1, giữ nguyên 28, xoá 1)`, `⚠️ Chưa có ảnh học phí mới tháng <tháng này>: Song ngữ (Song ngữ đang dùng tháng 9)`, `⚠️ Bỏ qua 1 file …: HỆ QUỐC TẾ/logo.png`; `curl` ảnh đã bỏ → 404, `ls $CASA_COPY/static/media/` không còn file đó.
- **Apps Script hỏng.** `fail.media: "500"` → `send tg-command /capnhatanh` → `SHEET` 500, tin `⚠️ Không cập nhật được ảnh (JSONDecodeError). Bot vẫn dùng … ảnh …`; `/media` vẫn đủ ảnh cũ, `last_error` có lý do; ảnh cũ vẫn tải được; `read log --grep "Media sync failed"` có dòng ERROR; `grep -c fake-sheet-token $CASA_EVIDENCE/app.log` → `0`.
- **Không phải nhóm admin.** `send tg-command /capnhatanh --chat-id -1000000000999` → `{"status":"ignored"}`, không có dòng outbox mới. `--bad-secret` → 403.
- **Ảnh học phí.** `send text 9000000000000801 "HOC_PHI cho em hỏi học phí ạ"` → chỉ `TEXT`. `send quick 9000000000000801 QR:age:1 --text "2-3 tuổi"` → chỉ `TEXT`. `send quick 9000000000000801 QR:campus:2 --text "Kim Mã"` → `TEXT` rồi `IMAGE http://127.0.0.1:<port>/static/media/sn-fee-10.jpg`. Hỏi lại `HOC_PHI …` → chỉ `TEXT`. Dòng nhắc model: đọc `messages[-1].content` của lời gọi chat trong `outbox.jsonl` (`kind: "chat"`), lượt bấm Kim Mã có `- [HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh học phí hệ Song ngữ (cơ sở Kim Mã).`; lời gọi chat sau đó có tin bot trước kết thúc bằng `[đã gửi ảnh học phí hệ Song ngữ (cơ sở Kim Mã)]`. `read log --grep "Drive images sent"` → `['fee:song_ngu:2026-10']`.
- **Từ chối số mà đòi giá.** `send text 9000000000000806 "ASK_PHONE TOUR_CAMPUS em quan tâm Mỹ Đình"` (bot xin SĐT), rồi `send text 9000000000000806 "HOC_PHI em cứ báo con số luôn đi"` → `TEXT` rồi `IMAGE …/qt-fee-10.jpg`, không có dòng `TG`.
- **Cơ sở vật chất.** `send text 9000000000000802 "CSVC trường có sân chơi không ạ"` → chỉ `TEXT`; `send quick 9000000000000802 QR:campus:2 --text "Kim Mã"` → `TEXT` rồi 4 `IMAGE …/km-csvc-1.jpg` … `km-csvc-4.jpg`.
- **Chương trình.** `send text 9000000000000803 "CHUONG_TRINH trường dạy chương trình gì ạ"` → `IMAGE …/md-tkb-2.jpg` (Mỹ Đình 3–5 tuổi). Bấm `QR:age:1` rồi `QR:campus:2` cho phụ huynh khác, rồi `send text … "Cambridge học thế nào ạ"` → `IMAGE …/km-tkb-1.jpg`; hỏi lại → chỉ `TEXT`.
- **Thực đơn.** `send text 9000000000000802 "SEND_MENU THUC_DON cho em xem thực đơn"` → `TEXT "Dạ đây là thực đơn mẫu của Casa ạ."` rồi `IMAGE …/static/media/sn-menu.jpg QUICK=[...]`, không có `static/thuc-don-mau.jpg`. Không `--env MEDIA_SYNC_ENABLED=true` thì cùng tin gửi `IMAGE …/static/thuc-don-mau.jpg` như cũ, và không lời gọi chat nào có dòng `- [HỆ THỐNG]`.
- **Bằng chứng.** Lệnh và dòng outbox qua `tee`; `netlog.txt` chỉ có `rewrite` tới host giả và không có `BLOCKED`.

## Gotchas

- Harness mặc định `MEDIA_SYNC_ENABLED=false` để outbox các hành trình khác không đổi; phải `--env MEDIA_SYNC_ENABLED=true` lúc `up`.
- Fake Drive không giả trang "quét virus" hay giới hạn tải của Google; ảnh lớn (14 MB của Kim Mã) chỉ thử được ở pytest (`tests/test_media.py`, Pillow thật), không qua harness.
- `static/media/` bị gitignore nên bản sao bắt đầu không có ảnh; mỗi lần `up` là tải lại đủ.
- Fake extract trả `{}` cho câu tự viết như "Bé 20 tháng, cơ sở Kim Mã": hồ sơ không có tuổi/cơ sở (trích xuất thật thì có). Câu đó vẫn tính cho chính lượt ấy (bot đọc tên cơ sở và tuổi trong tin), nhưng lượt sau thì không; dùng nút `QR:age:*`, `QR:campus:2` hoặc `TOUR_CAMPUS` để hồ sơ có dữ liệu.
- Tóm tắt dùng tháng hiện tại theo giờ Việt Nam của máy; fake chỉ có `HỌC PHÍ THÁNG 10`, nên chạy vào tháng khác sẽ thấy cảnh báo học phí ngay từ lần đầu. Ảnh fake có `modified` 2026-10-01: từ cuối tháng 7/2027 ảnh học phí là ảnh cũ (sửa lần cuối hơn 300 ngày), tóm tắt và tin nhắc ghi thêm "sửa lần cuối 01/10/2026".
