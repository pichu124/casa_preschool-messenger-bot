# Tin nhắc lại phụ huynh im lặng

Một phụ huynh đang được tư vấn rồi im lặng nhận đúng một tin nhắc lại cố định, ngay trước khi cửa sổ 24 giờ của Messenger đóng (sau 24 giờ Graph API từ chối tin thường), chỉ trong 8:00–20:59 giờ Việt Nam. GitHub Actions gọi `POST /followup/run` hai lần mỗi giờ (phút 17 và 47). Không gửi gì khi `FOLLOWUP_ENABLED` khác `true`. Code: `app/followup.py`; endpoint `followup_run` trong `app/main.py`.

## Sub-features

- `due` đến hạn khi: chưa có `phone` và chưa có `visit_request`; tin cuối trong lịch sử là của bot và không phải câu chuyển tư vấn viên (escalation); `now` nằm trong slot `[latest_send − 2h, latest_send]` và cách tin cuối của phụ huynh ít nhất 3 giờ, với `latest_send` = tin cuối + 23 giờ (`deadline`) khi cả slot `[deadline − 2h, deadline]` nằm trong 8:00–20:59:59 giờ Việt Nam (`deadline` 10:00–20:59:59), ngược lại 20:59:59 gần nhất trước `deadline` (vd `deadline` 8:00–9:59:59 → 20:59:59 hôm trước); chưa có `followup_sent_at` hay `staff_replied_at` từ sau tin đó; giờ Việt Nam trong 8–20.
- `template` theo nhãn của trường, thứ tự của `_template_key` (nguyên văn trong `TEMPLATES`): 1. tư vấn tương đối đủ (`fully_consulted` của `app/coverage.py`: có `kid_age` và `interested_campus`, `topics_covered` chứa đủ 7 nhóm của `TOPICS`) → `invite_visit` (mẫu 3); 2. chưa có `kid_age` → `ask_age` (mẫu 1); 3. còn lại (có tuổi, chưa đủ) → `ask_phone` (mẫu 2). `phone_declined` không đổi mẫu.
- `topics` mỗi câu bot trả lời (không escalate) được dò bằng `topics_in_reply` trên chữ còn token `[QUICK:]`, nhóm tìm thấy gộp vào `topics_covered` của hồ sơ (bỏ trùng); model trích xuất không ghi được trường này; tin nhắc lại không đi qua bộ dò. Kịch bản mặc định: `TOUR_CAMPUS` cho `school`, `program`, `facilities`, `visit_invite` (và `interested_campus` Mỹ Đình), `TOUR_MENU` cho `menu`, `trial`, `TOUR_EXTRA` cho `extracurricular`.
- `dry-run` `dry_run=true` hoặc `FOLLOWUP_ENABLED` tắt → chỉ đếm, `sent: 0`.
- `send` bật và không dry run → Graph API gửi template, ghi `followup_sent_at`, thêm tin vào lịch sử, đẩy `customers.json` lên GitHub; Graph API từ chối → bỏ qua phụ huynh đó.
- `verbose` `verbose=true` thêm `followups: [{"template_key", "customer_id": <4 ký tự cuối>}]`; không bao giờ có tên, SĐT hay nội dung tin.
- `staff-reply` echo của nhân viên sau tin cuối của phụ huynh → không nhắc (xem `echo` trong [webhook-messaging.md](webhook-messaging.md)).

## How to get to it (user POV)

- Phụ huynh: nhận một tin Messenger từ Page vài giờ sau khi ngừng trả lời.
- Vận hành: workflow `.github/workflows/followup.yml` (`curl -X POST "$BOT_BASE_URL/followup/run?secret=…"`), hoặc admin gọi tay.

## Driving it with send_event.py và curl

Preconditions:

- Một slug chỉ dùng cho hành trình này (vd `followup-1`): mọi PSID đã nhắn ở bước khác trong cùng run (webhook, lead, …) cũng có thể đến hạn khi tua đồng hồ, nên `due`, `sent` và dòng FB sẽ lớn hơn số dưới đây. Dùng chung instance thì chỉ so các mục `followups` và dòng FB của các PSID 0041–0049, không so `due`/`sent`.
- Instance bật gửi: `ctl up --slug <slug> --env FOLLOWUP_ENABLED=true`, `ctl doctor` OK, `eval "$(python3 .claude/skills/verify-casa-bot/harness/ctl.py env --slug <slug>)"`.
- Ba kịch bản `now_utc` tính từ tin cuối của phụ huynh theo quy tắc `latest_send` ở trên: `before` = `latest_send` − 2h30 (trước slot), `in` = `latest_send` − 1h (trong slot, slot luôn nằm trong khung giờ), `after` = `latest_send` + 5 phút. Vd nhắn lúc 14:30 giờ Việt Nam → `deadline` 13:30 hôm sau (trong khung) → `in` 12:30 hôm sau; nhắn lúc 23:00 → `deadline` 22:00 hôm sau (ngoài khung) → `latest_send` 20:59:59 → `in` 19:59:59; nhắn lúc 10:00 → `deadline` 9:00 hôm sau (slot lẹm trước 8:00) → `latest_send` 20:59:59 cùng ngày → `in` 19:59:59. Nhắn hết các bước tạo phụ huynh dưới đây trong vài phút, xong mới tạo ba file (lấy giờ hiện tại làm tin cuối; lệch vài phút vẫn nằm trong lề):

  ```bash
  python3 - <slug> <<'EOF'
  import json, sys, datetime as d
  vn = d.timezone(d.timedelta(hours=7))
  s = json.load(open(".claude/skills/verify-casa-bot/harness/scenario.default.json"))
  latest = (d.datetime.now(d.timezone.utc) + d.timedelta(hours=23)).astimezone(vn)
  if not 10 <= latest.hour <= 20:
      end = latest.replace(hour=20, minute=59, second=59, microsecond=0)
      latest = end if end < latest else end - d.timedelta(days=1)
  times = {
      "before": latest - d.timedelta(hours=2, minutes=30),
      "in": latest - d.timedelta(hours=1),
      "after": latest + d.timedelta(minutes=5),
  }
  for name, at in times.items():
      s["now_utc"] = at.astimezone(d.timezone.utc).isoformat(timespec="seconds")
      json.dump(s, open(f"artifacts/verify/{sys.argv[1]}/scenario-{name}.json", "w"), ensure_ascii=False)
      print(name, s["now_utc"], at.strftime("%d/%m %H:%M:%S giờ VN"))
  EOF
  ```

  `latest_send` trước 10:30 (nhắn lúc 11:00–11:29 giờ Việt Nam) thì `before` rơi ra ngoài 8:00–20:59, nên `due: 0` vì hai lý do; muốn thấy riêng "trước slot" thì nhắn vào giờ khác. Chưa nạp file nào vào run.

- **Tạo phụ huynh.** `send text 9000000000000041 "Xin chào"` (chưa có tuổi), `send quick 9000000000000042 QR:age:1 --text "2-3 tuổi"` (có tuổi), `send text 9000000000000043 "DECLINE chưa muốn để số"` (từ chối số, chưa có tuổi). Ba phụ huynh có tuổi đi qua kịch bản tư vấn, mỗi lệnh chờ xong mới gửi lệnh sau: …0047 tư vấn đủ `send quick 9000000000000047 QR:age:1 --text "2-3 tuổi"`, `send text 9000000000000047 "TOUR_CAMPUS Cơ sở Mỹ Đình thế nào ạ"`, `send text 9000000000000047 "TOUR_MENU Bé ăn uống thế nào ạ"`, `send text 9000000000000047 "TOUR_EXTRA Có ngoại khóa gì ạ"`; …0048 tư vấn chưa đủ rồi từ chối số `send quick 9000000000000048 QR:age:1 --text "2-3 tuổi"`, `send text 9000000000000048 "TOUR_CAMPUS Cơ sở Mỹ Đình thế nào ạ"`, `send text 9000000000000048 "DECLINE chưa muốn để số"`; …0049 thiếu ngoại khóa `send quick 9000000000000049 QR:age:1 --text "2-3 tuổi"`, `send text 9000000000000049 "TOUR_CAMPUS Cơ sở Mỹ Đình thế nào ạ"`, `send text 9000000000000049 "TOUR_MENU Bé ăn uống thế nào ạ"`. Thêm một phụ huynh đã có SĐT: `send phone 9000000000000044 0912345678`, một đã được chuyển tư vấn viên: `send text 9000000000000045 HARD_QUESTION`, và một đã được nhân viên tự nhắn: `send text 9000000000000046 "Xin chào"` rồi `send echo 9000000000000046 "Chị gọi Ba/Mẹ nhé"`.
- **Nhóm đã tư vấn.** `read profile 9000000000000047 --fields kid_age,interested_campus,topics_covered` → `kid_age` 2-3 tuổi, `interested_campus` Mỹ Đình, `topics_covered` đúng 7 khoá của `TOPICS` (so như tập: thứ tự là thứ tự gộp); `--disk` khớp. …0049 có 6 khoá, thiếu `extracurricular`. `read outbox --host fb` các dòng `to=9000000000000047`: phần `TEXT "…"` không chứa `[` (token đã bị cắt; nút nằm ở `QUICK=[…]`).
- **Chưa tới giờ.** `curl -s -X POST "$CASA_APP/followup/run?secret=$CASA_SECRET&dry_run=true&verbose=true"` → `{"due":0,…}` (vừa nhắn xong). `ctl scenario --slug <slug> artifacts/verify/<slug>/scenario-before.json`, dry run lại → `due: 0`.
- **Quá giờ.** `ctl scenario --slug <slug> artifacts/verify/<slug>/scenario-after.json`, dry run → `due: 0`.
- **Trong slot.** `ctl scenario --slug <slug> artifacts/verify/<slug>/scenario-in.json`. Dry run lại → `due: 6`, `followups` có `ask_age` …0041, `ask_phone` …0042, `ask_age` …0043 (quy tắc 2: chưa tuổi dù đã từ chối số), `invite_visit` …0047 (quy tắc 1), `ask_phone` …0048 (quy tắc 3: có tuổi, chưa đủ, dù đã từ chối số), `ask_phone` …0049 (quy tắc 3: thiếu ngoại khóa); không có …0044 (có SĐT), …0045 (đã chuyển tư vấn viên), …0046 (nhân viên đã nhắn). Outbox không có FB mới.
- **Gửi.** `curl -s -X POST "$CASA_APP/followup/run?secret=$CASA_SECRET&verbose=true"` → `"sent":6,"enabled":true`. `read outbox --host fb --since <seq trước đó>` có 6 dòng `TEXT "Dạ em chào Ba/Mẹ ạ. …"`, mỗi dòng đúng nguyên văn `TEMPLATES[template_key]` của `app/followup.py` cho PSID đó.
- **Không nhắc hai lần.** Gọi lại không dry run → `{"due":0,"sent":0,…}`, không có FB mới.
- **Xác nhận lưu bền.** `read profile 9000000000000041 --fields followup_sent_at` có giá trị bằng `now_utc`; `--disk` khớp; lịch sử cuối là template.
- **Graph API từ chối.** Trước bước Gửi (hoặc trên instance khác): `scenario-in.json` thêm `"fail": {"graph_send": true}` → `sent: 0`, `read log --grep "Follow-up"` có `not sent to customer …0041: Exception` (chỉ 4 ký tự cuối).
- **Bằng chứng.** JSON của từng lần gọi qua `tee`; outbox; `data_after/customers.json` sau `down`.

## Gotchas

- `FOLLOWUP_ENABLED` đọc lúc import: phải `ctl up --env FOLLOWUP_ENABLED=true`, không đổi được khi đang chạy. Tắt (mặc định của harness) thì `enabled: false`, `sent: 0` dù có `due`.
- `now_utc` chỉ tác động `app/followup.py` (qua `_now_utc`); dấu thời gian lịch sử vẫn là giờ thật lúc nhắn. Vì vậy phải nhắn trước rồi mới tua; tua ra ngoài slot (sớm hơn `latest_send` − 2h hoặc muộn hơn `latest_send`) thì không ai đến hạn.
- Giờ Việt Nam ngoài 8–20 (ngoài 01:00–13:59 UTC) → `due: 0` với mọi phụ huynh, kể cả trong slot.
- Harness chạy app với `TZ=UTC` như Render; lịch sử lưu `datetime.now()` không múi giờ, `app/followup.py` đọc là UTC.
- Phụ huynh đã được chuyển tư vấn viên bị loại vì tin cuối của bot là câu chuyển tiếp; nếu câu chuyển tiếp đổi chữ mà `HANDED_TO_CONSULTANT` không đổi theo thì phụ huynh đó sẽ bị nhắc: kiểm bằng hành trình trên.
- Phụ huynh đã nhận câu xin lỗi `ESCALATION_MESSAGE_UPSET` trong 24 giờ tính tới tin cuối của họ cũng bị loại, kể cả khi họ nhắn tiếp và tin cuối của bot là câu trả lời thường (`UPSET …` rồi một tin bất kỳ, tua vào slot → không có trong `followups`).
- `/test-chat` cũng tạo hồ sơ có lịch sử (`user_id` mặc định `test_user`) và có thể đến hạn; không dùng nó trong hành trình này.
