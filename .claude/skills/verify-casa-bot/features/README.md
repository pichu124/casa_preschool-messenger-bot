# Feature map: bot Messenger Casa

Mỗi file là một tính năng người dùng (phụ huynh, tư vấn viên trên Telegram, admin) thấy được, theo mẫu của `create-verify-skill`: `Sub-features`, `How to get to it (user POV)`, `Driving it with …`, `Gotchas`.

| Tính năng | File | Entry point chính |
|---|---|---|
| Nhận tin Messenger và trả lời (tin chữ, `[QUICK:]`, `[IMAGES:]`, quick reply, postback, referral, echo, dedup, chữ ký) | [webhook-messaging.md](webhook-messaging.md) | `POST /webhook` |
| Lead: SĐT, đổi SĐT, hẹn tham quan → Telegram + Google Sheet | [leads.md](leads.md) | `POST /webhook` |
| Chuyển câu khó cho tư vấn viên và trả lời lại qua Telegram | [escalation-admin-reply.md](escalation-admin-reply.md) | `POST /webhook`, `POST /telegram-webhook` |
| Endpoint admin và secret | [admin-endpoints.md](admin-endpoints.md) | `?secret=` |
| Tin nhắc lại phụ huynh im lặng | [followup.md](followup.md) | `POST /followup/run` |
| Dashboard, thống kê, xuất Excel | [dashboard-export.md](dashboard-export.md) | `/dashboard`, `/customers/export` |
| File tĩnh, Messenger profile, đăng ký webhook | [static-messenger-profile.md](static-messenger-profile.md) | `/static/*`, `/setup-*`, `GET /webhook` |

## Điều kiện nền

- Một instance do chính mình bật: `python3 .claude/skills/verify-casa-bot/harness/ctl.py up --slug <slug>` in `READY`, và `ctl.py doctor --slug <slug>` in `DOCTOR OK`. Xem [../SKILL.md](../SKILL.md).
- Bản sao bắt đầu với `data/customers.json` rỗng `{}`, `data/qa_database.json` của nguồn, không có `analytics.jsonl` hay escalation đang chờ. Hành trình cần hồ sơ có sẵn thì tạo bằng chính sự kiện Messenger (vd gửi `phone` trước), không sửa file.
- Kịch bản model: `harness/scenario.default.json` (bảng token trong SKILL.md, mục Drive).

## Quy ước điều khiển

Trong các file tính năng, viết tắt (khi chạy thì gõ đủ đường dẫn, chạy từ gốc repo, không dùng biến shell làm tên chương trình):

- `ctl …` = `python3 .claude/skills/verify-casa-bot/harness/ctl.py …`
- `send …` = `python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> …`
- `read …` = `python3 .claude/skills/verify-casa-bot/harness/read_back.py --slug <slug> …`
- `$CASA_APP`, `$CASA_SECRET`, `$CASA_COPY`, `$CASA_EVIDENCE`: từ `eval "$(python3 .claude/skills/verify-casa-bot/harness/ctl.py env --slug <slug>)"`.
- PSID giả: chuỗi số 16 chữ số, mỗi phụ huynh một số (`9000000000000001`, `…02`, …). ID dạng số quan trọng: `/telegram-webhook` dựng lại escalation từ text bằng regex `ID:\s*(\d+)`.

## Tiêu chuẩn bằng chứng

- Hành động: dòng `SENT …` của `send` (hoặc lệnh curl kèm HTTP code). Kết quả: các dòng outbox nó in ra, cộng một lần đọc lại độc lập (`read profile` qua `/customers` và `--disk`, hoặc `data_after/` sau `ctl down`).
- `POST /webhook` luôn trả 200 trước khi xử lý: chỉ outbox và hồ sơ đọc lại mới là kết quả.
- Không dùng `/test-chat` thay cho đường Messenger; không gọi hàm trong `app/`; không sửa `data/` của bản sao bằng tay giữa hành trình.
- Ghi transcript: thêm `| tee -a artifacts/verify/<slug>/transcript.txt` vào mỗi lệnh.
- Không có dữ liệu phụ huynh thật trong bằng chứng: chỉ dùng PSID, tên (`fb_profile`) và SĐT giả.
