# Dashboard, thống kê và xuất Excel

Admin mở `/dashboard?secret=…` trong trình duyệt để xem số tin, tỷ lệ chuyển tư vấn viên, chủ đề hay hỏi, tin gần đây (trang HTML gọi `/analytics/stats` và `/analytics/messages` với cùng secret), và tải danh sách phụ huynh dạng Excel ở `/customers/export`. Code: `app/dashboard.html`, `app/analytics.py`, `export_customers` trong `app/main.py`.

## Sub-features

- `dashboard` `GET /dashboard?secret=` → HTML `app/dashboard.html`; JS đọc `secret` từ URL và gọi hai endpoint thống kê.
- `stats` `GET /analytics/stats` → `total_messages`, `total_escalations`, `escalation_rate`, `unique_users`, `today_*`, `top_categories`, `daily_series` (7 ngày)…
- `messages` `GET /analytics/messages?limit=N` → các tin gần nhất (user_id, user_name, question, model_used, escalated, category).
- `reset` `POST /analytics/reset` → xoá `data/analytics.jsonl`.
- `export` `GET /customers/export` → file `.xlsx` (sheet `Khách hàng Casa`, 20 cột từ `Customer ID` tới `Số tin nhắn`, có `Giai đoạn` từ `lead_stage`, `Nguồn` = `ad_title`).

## How to get to it (user POV)

- Admin: mở `https://<host>/dashboard?secret=…` trong trình duyệt; bấm tải hoặc mở thẳng `https://<host>/customers/export?secret=…`.

## Driving it with curl

Preconditions:

- `ctl doctor --slug <slug>` OK; `eval "$(python3 .claude/skills/verify-casa-bot/harness/ctl.py env --slug <slug>)"`.
- Có dữ liệu: `send text 9000000000000051 "ASK_AGE học phí bao nhiêu"`, `send phone 9000000000000051 0912345678`, `send text 9000000000000052 HARD_QUESTION`.

- **Dashboard tải được.** `curl -s -o artifacts/verify/<slug>/dashboard.html -w '%{http_code} %{content_type}\n' "$CASA_APP/dashboard?secret=$CASA_SECRET"` → `200 text/html; charset=utf-8`; file có `fetch('/analytics/stats' + q)`.
- **Thống kê.** Trên run mới chỉ có ba tin trên: `curl -s "$CASA_APP/analytics/stats?secret=$CASA_SECRET"` → `total_messages: 3`, `total_escalations: 1`, `unique_users: 2`. `curl -s "$CASA_APP/analytics/messages?secret=$CASA_SECRET&limit=5"` → 3 bản ghi, bản `HARD_QUESTION` có `escalated: true`, `model_used: openai`.
- **Xuất Excel.** `curl -s -o artifacts/verify/<slug>/export.xlsx -w '%{http_code} %{content_type}\n' "$CASA_APP/customers/export?secret=$CASA_SECRET"` → `200 application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- **Xác nhận nội dung file.** Đọc lại bằng openpyxl của venv app (đường dẫn in ở `state.json`, khoá `python`): `<python> -c "import openpyxl; ws=openpyxl.load_workbook('artifacts/verify/<slug>/export.xlsx').active; print([c.value for c in ws[1]]); [print(r) for r in ws.iter_rows(min_row=2, values_only=True)]"` → hàng của …0051 có SĐT `0912345678`, `Giai đoạn` `Đã có SĐT`.
- **Reset.** `curl -s -X POST "$CASA_APP/analytics/reset?secret=$CASA_SECRET"` → `{"status":"reset",…}`; stats lại → `total_messages: 0`; `ls "$CASA_COPY/data/analytics.jsonl"` → không còn.
- **Bằng chứng.** `dashboard.html`, `export.xlsx`, JSON stats qua `tee` trong `artifacts/verify/<slug>/`.

## Gotchas

- Analytics ghi ở `data/analytics.jsonl` **tương đối với thư mục chạy** (bản sao), không theo `ANALYTICS_LOG_PATH` (chỉ `/analytics/reset` dùng biến đó, mặc định cùng đường dẫn).
- Chỉ tin Messenger qua `process_message` được tính; `/test-chat`, referral, echo không vào analytics.
- Dashboard là JS chạy trong trình duyệt: curl chỉ chứng minh HTML được phục vụ. Hành trình hiển thị số liệu cần trình duyệt (không có sẵn trong harness); kiểm hai endpoint JSON mà trang gọi là bằng chứng gần nhất, ghi rõ phần chưa kiểm được.
- File Excel chứa dữ liệu phụ huynh: chỉ xuất từ instance của harness (PSID và tên giả), không bao giờ từ app thật.
