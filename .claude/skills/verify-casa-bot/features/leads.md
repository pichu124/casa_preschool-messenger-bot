# Lead: SĐT và hẹn tham quan tới Telegram và Google Sheet

Khi một tin của phụ huynh đem lại SĐT mới, SĐT khác số cũ, hoặc lịch tham quan/học thử mới, bot báo nhóm Telegram của tư vấn viên và gửi mỗi sự kiện một POST tới Google Sheet (Apps Script web app) cùng lúc. Mỗi phụ huynh một thẻ Telegram: lead đầu là thẻ đầy đủ (message_id lưu ở `lead_card_msg_id` trong hồ sơ), thay đổi sau là tin ngắn `🔄 …` trả lời vào thẻ (`reply_parameters.message_id`). Mỗi phụ huynh một hàng Sheet là việc của Apps Script trong `docs/google-sheet-leads.md` (fake Sheet chỉ trả `{"ok": true}`, không giữ hàng). Reply thẻ hay tin ngắn trên Telegram không gửi gì cho phụ huynh. Code: `lead_events`, `publish_lead_events`, `_send_lead_telegram` trong `app/escalation.py`; `post_lead_row` trong `app/leads_sheet.py`; `_clean_extracted`, `PHONE_PATTERN` trong `app/main.py`.

## Sub-features

- `new-phone` hồ sơ chưa có SĐT, tin có SĐT → sự kiện `new_phone`; là lead đầu thì thẻ header `📞 KHÁCH ĐỂ LẠI SĐT`, không thì tin ngắn `🔄 <tên FB>: để lại SĐT <số>`.
- `phone-changed` SĐT khác số cũ sau khi chuẩn hoá (`+84 912…` = `0912…`) → `phone_changed`, tin ngắn `🔄 <tên FB>: SĐT: <cũ> → <mới>` (thẻ header `📞 KHÁCH ĐỔI SĐT` chỉ khi chưa có thẻ); cùng số viết khác → không có sự kiện.
- `visit-request` `visit_request` mới (so không phân biệt hoa thường, khoảng trắng) → `visit_request`; lead đầu thì thẻ header `📅 KHÁCH HẸN THAM QUAN/HỌC THỬ`, không thì tin ngắn `🔄 <tên FB>: Hẹn: <cũ> → <mới>` (chưa có hẹn cũ: `Hẹn: <mới>`); trùng lịch cũ → không có sự kiện.
- `lead-card` một thẻ mỗi phụ huynh: một tin có nhiều sự kiện là một tin Telegram (thẻ, hoặc một tin ngắn nối các thay đổi bằng `; `); tin ngắn có dòng thứ hai `🕐 dd/mm/yyyy HH:MM` giờ Việt Nam.
- `card-deleted` Telegram từ chối tin trả lời (thẻ đã bị xoá: `message to be replied not found`) → bot gửi thẻ đầy đủ mới, lưu `lead_card_msg_id` mới; thay đổi sau trả lời vào thẻ mới.
- `phone-button` nút SĐT của Messenger: payload là số, thắng SĐT model trích xuất.
- `phone-clean` SĐT model trích xuất được lọc: lấy số Việt Nam đầu tiên (`"0912345678, 0987654321"` → số đầu), bỏ khi không có số (`"không có"`).
- `sheet-row` body Sheet: `fb_name, customer_id, phone, kid_name, kid_age, campus, area, expected_start, visit_request, ad_title, stage, last_message` + `token` (`LEADS_SHEET_TOKEN`), `event`, `time` (giờ Việt Nam).
- `sheet-failure` web app trả `{"ok": false}` hoặc HTTP 500 → log `Sheet written=False`, Telegram vẫn gửi, phụ huynh vẫn nhận trả lời.

## How to get to it (user POV)

- Phụ huynh: bấm nút SĐT Messenger dưới câu bot xin số (`[QUICK:phone]`), gõ số trong tin, hoặc chốt lịch tham quan/học thử (gõ, hoặc bấm nút đồng ý `visit_invite`/`trial_invite` rồi nút buổi/tuần `visit_time`/`trial_week`).
- Tư vấn viên: đọc tin trong nhóm Telegram; quản lý: xem Google Sheet.
- Hệ thống: `POST /webhook` (Messenger) → `api.telegram.org/bot…/sendMessage` + `script.google.com/macros/s/…/exec`.

## Driving it with send_event.py

Preconditions:

- `ctl doctor --slug <slug>` in `DOCTOR OK`; kịch bản mặc định (`fail.sheet: ok`); PSID chưa có hồ sơ.

- **Nút SĐT → lead mới.** Chạy `send text 9000000000000011 "ASK_PHONE cho em xin học phí"` (bot gửi nút: dòng FB có `QUICK=["user_phone_number"]`), rồi `send phone 9000000000000011 0912345678`. Thấy đúng một `SHEET {"event": "new_phone", "customer_id": "9000000000000011", "phone": "0912345678", …, "stage": "Đã có SĐT", "token": "fake-sheet-token-<run_id>"}` và một `TG sendMessage message_id=… header='📞 KHÁCH ĐỂ LẠI SĐT'`, cộng câu trả lời FB.
- **Nội dung Telegram.** `read outbox --host tg --full` → `body.text` có `📱 SĐT: 0912345678`, `🆔 ID: 9000000000000011`, `👤 Facebook: Test Parent`, `📊 Giai đoạn: Đã có SĐT`, và dòng cuối "Reply tin này không gửi tới khách."; `body` không có `reply_parameters`.
- **Xác nhận lưu bền.** `read profile 9000000000000011 --fields phone,parent_name,lead_card_msg_id` → `0912345678`, `Test Parent`, đúng `message_id` của thẻ; `read profile 9000000000000011 --fields phone,lead_card_msg_id --disk` → cùng giá trị; `read log --grep "Lead new_phone"` → `Telegram msg_id=<n>, Sheet written=True`.
- **Gửi lại cùng số, viết khác.** `send text 9000000000000011 "+84 912 345 678"` với kịch bản có rule extract trả `{"phone": "+84 912 345 678"}` → không có dòng SHEET hay TG mới.
- **Đổi số.** `send text 9000000000000011 "PHONE_B số mới của em"` → `SHEET {"event": "phone_changed", … "phone": "0987654321" …}` và `TG sendMessage message_id=… reply_to=<message_id của thẻ> header='🔄 Test Parent: SĐT: 0912345678 → 0987654321'`.
- **Hẹn tham quan, rồi đổi lịch (sự cố 2026-10-22).** `send text 9000000000000011 "VISIT_AM em chốt sáng thứ 7"` → `SHEET {"event": "visit_request", …, "visit_request": "tham quan buổi sáng", "stage": "Đã hẹn tham quan/học thử"}` và `TG … reply_to=<thẻ> header='🔄 Test Parent: Hẹn: tham quan buổi sáng'`. Gửi lại `VISIT_AM` → không có lead mới. `send text 9000000000000011 "VISIT_TOMORROW à sáng mai nhé"` → `SHEET {"event": "visit_request", …, "visit_request": "tham quan sáng mai"}` và `TG … reply_to=<thẻ> header='🔄 Test Parent: Hẹn: tham quan buổi sáng → tham quan sáng mai'`. Cả hành trình: `read outbox --host tg` có đúng một thẻ (không `reply_to`), các dòng sau đều `reply_to=` cùng id thẻ; `--full` cho dòng thứ hai của `body.text` là `🕐 dd/mm/yyyy HH:MM`.
- **Hẹn bằng nút: đồng ý rồi chọn buổi.** PSID mới: `send text 9000000000000012 INVITE_VISIT` (FB có `QUICK=["QR:visit_invite:0", "QR:visit_invite:1"]`), `send quick 9000000000000012 QR:visit_invite:0 --text "Đặt lịch tham quan"` → lead `visit_request` `tham quan trường` (SHEET + thẻ TG `📅 KHÁCH HẸN THAM QUAN/HỌC THỬ`), rồi `send quick 9000000000000012 QR:visit_time:0 --text "Buổi sáng"` → SHEET `tham quan buổi sáng` và TG `reply_to=<thẻ> header='🔄 Test Parent: Hẹn: tham quan trường → tham quan buổi sáng'`: mỗi chi tiết hẹn mới là một lead (quyết định 2026-10-22, xem `docs/quyet-dinh-noi-dung.md`). Bấm lại `Buổi sáng` → không có lead mới.
- **Thẻ bị xoá.** PSID mới, `send phone 9000000000000013 0912000222` (thẻ), rồi kịch bản có `"fail": {"telegram_reply": true}` và `send text 9000000000000013 "VISIT_AM"` → một dòng `TG` status `400` có `reply_to=<thẻ cũ>`, rồi một thẻ đầy đủ mới `header='📅 KHÁCH HẸN THAM QUAN/HỌC THỬ'` không `reply_to`; `read profile 9000000000000013 --fields lead_card_msg_id` → id thẻ mới; `read log --grep "not replied to"` có `Lead card <thẻ cũ> of customer 9000000000000013 not replied to, sending a new card`.
- **Sheet hỏng.** Kịch bản có `"fail": {"sheet": "false"}` (hoặc `"500"`), PSID mới, `send phone <psid> 0912000111` → dòng `SHEET` có status `200` (hoặc `500`), `TG` vẫn có, phụ huynh vẫn nhận trả lời FB. `read log --grep "Google Sheet"` có `Lead new_phone rejected by Google Sheet web app (HTTP 200)` (với `false`) hoặc `Lead new_phone not written to Google Sheet: JSONDecodeError` (với `500`), và `read log --grep "Sheet written=False"` có dòng. Các dòng đó không chứa URL Sheet hay SĐT.
- **Bằng chứng.** Transcript qua `tee`; `outbox.jsonl` có body đầy đủ của Sheet và Telegram.

## Gotchas

- Mỗi tin chỉ sinh lead khi giá trị **mới** so với hồ sơ trước tin đó; muốn thấy `new_phone` lần nữa thì dùng PSID khác, không xoá hồ sơ.
- Trích xuất SĐT trong tin chữ đến từ **model giả**: phải có rule `extract` trả `phone`, nếu không thì không có lead dù tin có số. Nút SĐT (`send phone`) không cần rule.
- Telegram và Sheet chạy song song: thứ tự dòng `SHEET`/`TG` đổi giữa các lần chạy.
- `parent_name` lấy từ tên Facebook (`fb_profile` trong kịch bản, mặc định `Test Parent`).
- `last_message` trong Sheet là chữ phụ huynh gửi, với nút SĐT là chính số đó.
- Header Telegram, mẫu tin ngắn `🔄 …` và tên sự kiện là hợp đồng với `docs/google-sheet-leads.md` và Apps Script: đổi chúng là thay đổi người dùng thấy.
- Thẻ gắn với hồ sơ (`lead_card_msg_id`), không với run: muốn thấy thẻ đầy đủ lần nữa thì dùng PSID khác.
- Một hàng mỗi phụ huynh không kiểm được qua harness (fake Sheet không giữ hàng): bằng chứng ở đây là mỗi sự kiện một POST mang đúng `customer_id`.
