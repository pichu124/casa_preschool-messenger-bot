# Chuyển câu khó cho tư vấn viên và trả lời lại qua Telegram

Khi model trả `[ESCALATE]` (hoặc mọi model đều lỗi), bot gửi câu hỏi vào nhóm Telegram (header `⚠️ CẦN TRỢ GIÚP ⚠️`) và trả lời phụ huynh một câu chuyển tiếp tuỳ theo đã có SĐT hay chưa. Tư vấn viên **reply** tin đó trên Telegram; bot viết lại câu trả lời cho lịch sự bằng model, gửi cho phụ huynh qua Messenger, phân loại thành một cặp Q&A mới, lưu `data/qa_database.json` và đẩy lên GitHub. Code: `escalate_to_admin` trong `app/escalation.py`; `handle_telegram_webhook` trong `app/main.py`; `add_qa_pair` trong `app/qa_database.py`; `push_qa_to_github` trong `app/github_sync.py`.

## Sub-features

- `escalate` `[ESCALATE]` → Telegram `sendMessage` (khách, ID, câu hỏi) + lưu `data/pending_escalations.json` (theo `message_id` Telegram) + `data/escalation_log.json`.
- `escalate-reply-text` câu gửi phụ huynh (nguyên văn của trường, luôn kèm `Hotline 0989 059 838`, không xin SĐT): đã có SĐT (trong hồ sơ hoặc trong chính tin) → `ESCALATION_MESSAGE_HAS_PHONE`; còn lại (kể cả đã từ chối cho số) → `…ASK_PHONE` (bằng `…PHONE_DECLINED`).
- `upset` extract trả `upset: true` (phụ huynh khó chịu, gay gắt đòi thông tin qua chat) → escalate dù model chat không `[ESCALATE]`; câu gửi phụ huynh là `ESCALATION_MESSAGE_UPSET` (lời xin lỗi của trường) thay cho câu của model; `upset` không vào hồ sơ.
- `all-models-fail` không model nào trả lời được → coi như escalate.
- `admin-reply` reply tin escalation → `format_admin_reply` (AI) → FB tới đúng PSID → `classify_qa` (AI) → thêm Q&A, lưu file, PUT GitHub `pichu124/casa_preschool-messenger-bot` `data/qa_database.json`, nạp lại context cho model, xoá khỏi pending.
- `recover-from-text` không có pending (Render deploy làm mất file) nhưng tin được reply bắt đầu bằng header → dựng lại PSID, tên, câu hỏi từ text.
- `ignore` không phải reply → `ignored`; reply tin lead hoặc tin khác → `no_escalation_found`; reply không có chữ → `no_text`; cùng `message_id` Telegram lần hai → `duplicate`.
- `secret` header `X-Telegram-Bot-Api-Secret-Token` khác `TELEGRAM_WEBHOOK_SECRET` → 403.

## How to get to it (user POV)

- Phụ huynh: hỏi điều Q&A không có (tên giáo viên, ngày sự kiện…).
- Tư vấn viên: trong nhóm Telegram, bấm Reply vào tin "CẦN TRỢ GIÚP" và gõ câu trả lời.
- Telegram: `POST /telegram-webhook` với header secret (đã đăng ký bằng `/setup-telegram-webhook`).

## Driving it with send_event.py

Preconditions:

- `ctl doctor --slug <slug>` in `DOCTOR OK`; kịch bản mặc định (`HARD_QUESTION` → `[ESCALATE]`).

- **Escalate khi chưa có SĐT.** Chạy `send text 9000000000000021 "HARD_QUESTION cô giáo lớp Mầm tên gì ạ"`. Thấy `AI chat rule='HARD_QUESTION'`, `TG sendMessage message_id=<N> header='⚠️ CẦN TRỢ GIÚP ⚠️'`, và FB tới `9000000000000021` với câu bắt đầu "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ!", có "phản hồi trực tiếp tại đây" và "Hotline 0989 059 838", không có "SĐT"/"Zalo".
- **Escalate khi đã có SĐT.** PSID khác: `send phone 9000000000000022 0912345678`, rồi `send text 9000000000000022 "HARD_QUESTION …"` → câu FB có "tư vấn viên sẽ liên hệ" và "Hotline 0989 059 838", không xin số.
- **Escalate khi đã từ chối số.** PSID khác: `send text 9000000000000023 "DECLINE chưa muốn để số"`, rồi `send text 9000000000000023 "HARD_QUESTION …"` → cùng câu như chưa có SĐT ("phản hồi trực tiếp tại đây", hotline).
- **Phụ huynh khó chịu.** PSID khác: `send text 9000000000000024 "UPSET sao cứ đòi số thế, gửi qua đây luôn đi"` → `AI chat` theo mặc định (không escalate), `AI extract rule='UPSET'`, `TG sendMessage header='⚠️ CẦN TRỢ GIÚP ⚠️'` có câu của phụ huynh, FB đúng câu "Dạ em xin lỗi Ba/Mẹ vì sự bất tiện này ạ. …", không có câu của model; `read_back.py profile 9000000000000024 --fields upset,phone_declined` → không có `upset`, `phone_declined: true`.
- **Admin trả lời.** Chạy `send tg-reply "Cô Lan chủ nhiệm lớp Mầm" --to <N>` với `<N>` là `message_id` ở dòng `TG` của bước đầu (bỏ `--to` thì reply tin escalation gần nhất trong outbox, ở đây là của …0023). Thấy `HTTP 200 {"status":"ok"}`, `AI format_admin_reply`, `FB to=9000000000000021 TEXT "Dạ, Cô Lan chủ nhiệm lớp Mầm ạ."`, `AI classify`, `GH GET` + `GH PUT /repos/pichu124/casa_preschool-messenger-bot/contents/data/qa_database.json`.
- **Xác nhận lưu bền.** `curl -s "$CASA_APP/qa-database?secret=$CASA_SECRET"` → `total` tăng 1 và cặp cuối có `answer: "Cô Lan chủ nhiệm lớp Mầm"`, `category` từ classify (mặc định `Khác`). Sau `ctl down`: `data_after/qa_database.json` và `github/repos/pichu124/casa_preschool-messenger-bot/contents/data/qa_database.json` có cùng cặp đó; `data_after/pending_escalations.json` không còn `message_id` vừa reply.
- **Dựng lại từ text.** `send tg-reply "Dạ có ạ" --to 999999 --quote "$(printf '⚠️ CẦN TRỢ GIÚP ⚠️\n\n👤 Khách hàng: Test Parent\n🆔 ID: 9000000000000021\n📄 Trang: \n\n❓ Câu hỏi:\nCó xe bus không ạ\n\n🕐 01/01/2026 10:00')"` → `{"status":"ok"}`, FB tới `9000000000000021`; `read log --grep "No pending escalation"` có dòng.
- **Reply tin lead.** `send tg-reply "ok" --to <message_id của tin lead> --quote "📞 KHÁCH ĐỂ LẠI SĐT ..."` → `{"status":"no_escalation_found"}`, không có FB.
- **Dedup và secret.** `send tg-reply "x" --message-id 777 --to 1 --quote z` hai lần → lần một `no_escalation_found`, lần hai `{"status":"duplicate"}` (có `--to 1` để không trả lời lại escalation thật); `send --no-wait tg-reply "x" --bad-secret` → `HTTP 403`.
- **Bằng chứng.** Transcript qua `tee`; `outbox.jsonl` có text tin Telegram và FB; `data_after/` sau `down`.

## Gotchas

- **Repo thật:** `app/github_sync.py` ghi cứng `pichu124/casa_preschool-messenger-bot`, nhánh `main`. Ngoài harness, một admin reply với `GITHUB_TOKEN` thật là một commit lên `main` của repo public, tức một lần deploy. Trong harness nó tới GitHub giả; `ctl doctor` phải OK trước khi drive hành trình này.
- Lúc khởi động (và mỗi `/reload-qa`) app kéo `data/qa_database.json` từ `main` (`GH GET …/qa_database.json` đầu outbox, log `Loaded <n> Q&A pairs from GitHub`); GitHub giả phục vụ bản `data/qa_database.json` của bản sao, PUT sau đó thay nó. Admin reply là một `GH PUT` nêu sha của lần kéo/đẩy trước, không có GET trước. Harness chưa có lệnh restart: giả lập restart bằng cách ghi lại bản trong image (`git show HEAD:data/qa_database.json > $CASA_COPY/data/qa_database.json`) rồi `POST /reload-qa` → `qa_pairs` vẫn gồm cặp vừa học, `/qa-database` có cặp đó ở cuối.
- Commit khác lên `main` (sửa tay, instance khác): `curl -X POST --data-binary @file.json "$CASA_FAKE/__fake/github-commit?path=/repos/pichu124/casa_preschool-messenger-bot/contents/data/qa_database.json"` thay file trên GitHub giả (không vào outbox). PUT kế tiếp của app nêu sha cũ nên nhận `409`, rồi `GH GET` kéo lại và `GH PUT` 200; file trong `github/…` có bản sửa tay cộng cặp mới, cặp đã xoá trong `file.json` không quay lại. `fail.github_put` làm PUT trả 500: log ERROR `… not pushed to GitHub: kept …`, admin reply sau đó đẩy cả cặp cũ.
- `tg-reply` không có `--to` lấy `message_id` từ phản hồi của Telegram giả trong outbox; chưa có escalation thì lệnh dừng với lỗi.
- Trạng thái dedup Telegram nằm trong RAM: `--message-id` mặc định sinh từ thời gian, nên hai lệnh liên tiếp không bị coi là trùng.
- `/qa-learned` chỉ lọc `category == "Học từ admin"`, còn admin reply lấy `category` từ `classify_qa`: với kịch bản mặc định (`Khác`), cặp mới không hiện ở `/qa-learned`. Muốn thấy thì thêm rule `{"kind": "classify", "contains": "", "reply": {"category": "Học từ admin", "keywords": [], "similar_questions": []}}`. Nếu đó là hành vi cần có của sản phẩm thì báo lỗi, đừng sửa map.
- Escalation không ghi `[ESCALATE]` vào câu gửi phụ huynh; lịch sử lưu câu chuyển tiếp, nên `app/followup.py` không nhắc lại phụ huynh đã được chuyển (xem [followup.md](followup.md)).
- `fail.telegram` → `escalate_to_admin` trả False, không có pending, nhưng phụ huynh vẫn nhận câu chuyển tiếp: kiểm điều đó bằng outbox nếu thay đổi chạm tới đường này.
