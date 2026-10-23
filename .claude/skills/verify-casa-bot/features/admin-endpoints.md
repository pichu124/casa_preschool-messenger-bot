# Endpoint admin và secret

Admin (chủ Page, người vận hành) gọi các endpoint quản trị bằng `?secret=<TELEGRAM_WEBHOOK_SECRET>`. Secret sai, thiếu, hoặc server chưa đặt secret → 403 (so sánh hằng thời gian, `require_secret` trong `app/main.py`). Endpoint công khai chỉ có `GET /`, `GET/POST /webhook` (verify token, chữ ký Facebook), `POST /telegram-webhook` (header secret) và `/static/*`.

## Sub-features

- `health` `GET /` → `status`, `version` (`APP_VERSION`), `qa_pairs`, `ai_models`; không cần secret.
- `secret-gate` mọi endpoint dưới đây trả 403 `{"detail":"Invalid secret"}` khi secret sai hoặc thiếu.
- `customers` `GET /customers` → `{"total", "customers": {psid: profile}}`.
- `customer-reset` `POST /customers/{psid}/reset` → `{"status":"reset","existed":true|false}`; xoá hồ sơ của đúng PSID đó (lịch sử, tóm tắt, `lead_card_msg_id`, `followup_sent_at`…) và escalation đang chờ của họ, lưu đĩa, PUT lên GitHub giả khi có hồ sơ. Tin tiếp theo của PSID đó là tin đầu tiên.
- `qa` `GET /qa-database` (mọi cặp), `GET /qa-learned` (category `Học từ admin`), `POST /reload-qa` (kéo lại `data/qa_database.json` từ GitHub giả cộng cặp chưa đẩy được, rồi đẩy các cặp đó; kéo lỗi thì giữ bộ nhớ, hoặc đọc lại file nếu chưa từng kéo được; dựng lại context model), `POST /import-excel?file_path=…`.
- `test-chat` `POST /test-chat` `{"message", "user_id"}` → trả lời model không qua Facebook; ghi hồ sơ và lịch sử cho `user_id`.
- `analytics` `GET /analytics/stats`, `GET /analytics/messages?limit=`, `POST /analytics/reset` (xoá `data/analytics.jsonl`) — xem [dashboard-export.md](dashboard-export.md).
- `setup` `POST /setup-telegram-webhook`, `POST /setup-messenger-profile` — xem [static-messenger-profile.md](static-messenger-profile.md).
- `followup` `POST /followup/run` — xem [followup.md](followup.md).

## How to get to it (user POV)

- Trình duyệt hoặc curl của admin: `https://<host>/<endpoint>?secret=…`. GitHub Actions (`.github/workflows/followup.yml`) gọi `/followup/run` mỗi giờ với secret.

## Driving it with curl

Preconditions:

- `ctl doctor --slug <slug>` in `DOCTOR OK`; `eval "$(python3 .claude/skills/verify-casa-bot/harness/ctl.py env --slug <slug>)"`.

- **Health.** `curl -s "$CASA_APP/"` → `{"status":"ok","version":"…","qa_pairs":<n>,"ai_models":["openai"]}`.
- **Secret sai và thiếu.** Với mỗi endpoint (GET: `/customers`, `/customers/export`, `/dashboard`, `/analytics/stats`, `/analytics/messages`, `/qa-database`, `/qa-learned`; POST: `/analytics/reset`, `/customers/9000000000000001/reset`, `/reload-qa`, `/test-chat`, `/setup-telegram-webhook`, `/setup-messenger-profile`, `/followup/run`, `/import-excel?file_path=x`), chạy `curl -s -o /dev/null -w '%{http_code}\n' -X <GET|POST> "$CASA_APP<endpoint>?secret=wrong"` và không có `secret` → `403` cả hai (`/import-excel`: `?file_path=x&secret=wrong`; `/test-chat`: kèm `-H 'content-type: application/json' -d '{"message":"x"}'`).
- **Secret đúng.** `curl -s "$CASA_APP/customers?secret=$CASA_SECRET"` → `{"total":0,"customers":{}}` trên run mới; sau một tin Messenger thì có PSID đó.
- **Q&A.** `curl -s "$CASA_APP/qa-database?secret=$CASA_SECRET" | python3 -c 'import json,sys; print(json.load(sys.stdin)["total"])'` bằng `qa_pairs` của `GET /`. `curl -s -X POST "$CASA_APP/reload-qa?secret=$CASA_SECRET"` → `{"status":"reloaded","qa_pairs":<n>}`.
- **test-chat.** `curl -s -X POST "$CASA_APP/test-chat?secret=$CASA_SECRET" -H 'content-type: application/json' -d '{"message":"ASK_AGE","user_id":"9000000000000031"}'` → `response` còn nguyên token `[QUICK:age]` (endpoint không xử lý token), `model_used: openai`; outbox chỉ có `AI` (không FB, không GH).
- **Xác nhận lưu bền.** `read profile 9000000000000031 --disk` có `message_count` và lịch sử của lần test-chat.
- **Reset một phụ huynh.** `send text 9000000000000032 "Cho em hỏi về trường ạ"` hai lần (lần hai: request AI có lịch sử, không có `[FIRST_MESSAGE]`), rồi `curl -s -X POST "$CASA_APP/customers/9000000000000032/reset?secret=$CASA_SECRET"` → `{"status":"reset","existed":true}` và một PUT GH mới không còn PSID đó; `read profile 9000000000000032` (cả `--disk`) báo không có hồ sơ. Gửi lại tin đó → `read outbox --host ai --full`: request `chat` mới có `[FIRST_MESSAGE]` và không có lịch sử. Gọi reset lần nữa → `"existed":false`.
- **Bằng chứng.** Lưu từng lệnh curl với `-w '%{http_code}'` vào transcript qua `tee`.

## Gotchas

- `require_secret` chạy trước khi FastAPI kiểm query và body: secret sai thì `/import-excel` thiếu `file_path` hay `/test-chat` thiếu body vẫn trả `403` (đã thử 2026-10-21). Một `422` với secret sai là dấu hiệu thứ tự đó đã đổi.
- `TELEGRAM_WEBHOOK_SECRET` rỗng thì mọi endpoint admin và `/telegram-webhook` khoá cứng (403). Thử bằng `ctl up --slug <slug> --env TELEGRAM_WEBHOOK_SECRET=`; `ctl up` vẫn READY vì readiness không dùng secret, nhưng `read profile` (qua `/customers`) sẽ báo 403, dùng `--disk`.
- `/test-chat` không phải đường của phụ huynh: không quick reply, không ảnh, không lead, không escalation, không sync GitHub. Không dùng làm bằng chứng cho hành vi Messenger.
- `/import-excel` đọc đường dẫn **trên máy chủ**, tương đối với thư mục của bản sao (`FAQS.xlsx` có trong repo). Nó ghi đè `data/qa_database.json` của bản sao.
- `/analytics/reset` xoá dữ liệu: chỉ gọi trên instance của mình.
