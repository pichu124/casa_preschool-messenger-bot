# Nhận tin Messenger và trả lời

Phụ huynh nhắn Page, bấm nút trả lời nhanh, bấm Get Started hoặc ice breaker, hay mở thread từ quảng cáo; bot trả lời bằng Graph API (`POST /v21.0/me/messages`), kèm nút trả lời nhanh khi model kết câu bằng `[QUICK:<key>]` và gửi ảnh khi có `[IMAGES:...]`. Nhân viên tự nhắn trong hộp thư Page thì bot không trả lời nhưng ghi lại `staff_replied_at`. Code: `handle_webhook`, `parse_messaging_event`, `process_message` trong `app/main.py`; nút ở `app/messenger.py`.

## Sub-features

- `text` tin chữ → typing indicator, lấy tên Facebook, gọi model (trả lời + trích xuất song song), gửi trả lời, lưu hồ sơ và lịch sử, đẩy `customers.json` lên GitHub giả.
- `quick-token` `[QUICK:key]` cuối câu model → bỏ token khỏi chữ, gắn `quick_replies` (payload `QR:<key>:<i>`); key lạ → không có nút; `[QUICK:phone]` → `{"content_type": "user_phone_number"}`.
- `images` `[IMAGES:static/a.jpg,...]` → gửi chữ trước, mỗi ảnh một tin; `static/…` thành `PUBLIC_BASE_URL/static/…`; nút chỉ gắn vào tin cuối.
- `quick-reply` bấm nút `QR:<key>:<i>` → bot xử lý **nghĩa** của nút (`QUICK_REPLIES` trong `app/messenger.py`), không phải chữ trên nút; payload `QR:` lạ → dùng chữ của tin.
- `phone-button` nút SĐT của Messenger (payload là số) → SĐT lấy từ payload, thắng mọi thứ model trích xuất (xem [leads.md](leads.md)).
- `get-started` postback `GET_STARTED` → model nhận "Xin chào Casa ạ"; `IB_1`…`IB_4` → câu hỏi của ice breaker.
- `referral` quảng cáo/m.me link: `source` ADS → `lead_source: ads`, SHORTLINK → `link`, kèm `ad_id`, `ad_title`, `ref`; referral không kèm tin → chỉ lưu, không trả lời; không có `source` → không ghi gì (organic).
- `echo` echo không có `metadata: casa-bot` → `staff_replied_at` (UTC, từ timestamp sự kiện); echo của chính bot → bỏ qua.
- `dedup` cùng `mid` (hoặc cùng postback `mid`) gửi lại → chỉ xử lý một lần.
- `signature` `FB_APP_SECRET` có giá trị (harness luôn đặt) → body sai chữ ký trả 403.
- `error-reply` mọi lỗi trong lúc xử lý → tin xin lỗi "hệ thống của Casa đang gặp sự cố".

## How to get to it (user POV)

- Phụ huynh: nhắn Page, bấm nút trả lời nhanh / nút SĐT, bấm Get Started hoặc ice breaker, bấm quảng cáo Click-to-Messenger hoặc link m.me có `ref`.
- Nhân viên: trả lời phụ huynh trong hộp thư Page (Facebook gửi echo).
- Facebook: `POST /webhook` với `{"object": "page", "entry": [{"messaging": [...]}]}`, header `X-Hub-Signature-256`.

## Driving it with send_event.py

Preconditions:

- `ctl doctor --slug <slug>` in `DOCTOR OK`; kịch bản mặc định.

- **Tin chữ có `[QUICK:age]`.** Chạy `send text 9000000000000001 "ASK_AGE Cho em hỏi về trường ạ"`. Thấy `AI chat rule='ASK_AGE'`, `AI extract`, rồi `FB to=9000000000000001 TEXT "Dạ Casa chào Ba/Mẹ ạ 🌿 Bé nhà mình năm nay mấy tuổi ạ?" QUICK=["QR:age:0", "QR:age:1", "QR:age:2", "QR:age:3"]`: chữ không còn `[QUICK:age]`.
- **Bấm nút tuổi.** Chạy `send quick 9000000000000001 QR:age:1 --text "2-3 tuổi"` (chữ là nhãn, `QUICK_REPLIES["age"][1][0]`). Thấy `AI chat rule='Bé nhà em 2-3 tuổi'` (model nhận nghĩa của nút, `QUICK_REPLIES["age"][1][1]`, không phải nhãn) và trả lời có `QUICK=["QR:visit_time:0", "QR:visit_time:1"]`. `read profile 9000000000000001 --fields kid_age` → `"2-3 tuổi"`.
- **Ảnh.** Chạy `send text 9000000000000001 SEND_MENU`. Thấy hai dòng FB: `TEXT "Dạ đây là thực đơn mẫu của Casa ạ."` không có QUICK, rồi `IMAGE http://127.0.0.1:<port>/static/thuc-don-mau.jpg QUICK=[...age...]`.
- **Key QUICK lạ.** Chạy `send text 9000000000000001 BAD_QUICK`. Dòng FB không có `QUICK=` và chữ không còn token.
- **Get Started từ quảng cáo.** Chạy `send postback 9000000000000002 GET_STARTED --referral ADS --ad-id AD1 --ad-title "Khai giảng"`. Có trả lời FB. `read profile 9000000000000002 --fields lead_source,ad_id,ad_title,message_count` → `ads`, `AD1`, `Khai giảng`, `1`. `read outbox --host ai --full` cho thấy tin của model chứa `[FIRST_MESSAGE] Xin chào Casa ạ` và khối `[TRẠNG THÁI TƯ VẤN]` có `Nguồn: quảng cáo "Khai giảng"`.
- **Ice breaker.** Chạy `send postback 9000000000000002 IB_1`. Bản ghi AI chat (`--full`) chứa đúng `ICE_BREAKERS["IB_1"]` của `app/messenger.py` (hiện là "Học phí của trường là bao nhiêu?").
- **Referral không kèm tin.** Chạy `send referral 9000000000000003 --referral SHORTLINK --ref casa`. Outbox chỉ có `GH GET/PUT` (không FB). `read profile 9000000000000003 --fields lead_source,ref,message_count` → `link`, `casa`, `null`.
- **Echo của nhân viên.** Chạy `send echo 9000000000000001 "Chị gọi lại nhé"`. Không có FB; `read profile 9000000000000001 --fields staff_replied_at` có giờ UTC. Lặp với `--bot`: `staff_replied_at` không đổi.
- **Dedup.** Chạy `send text 9000000000000005 "Xin chào" --mid dup-1` hai lần. Lần hai không in dòng outbox nào; `read log --grep "Skipping duplicate FB message"` có một dòng.
- **Chữ ký sai.** Chạy `send --no-wait text 9000000000000005 hi --bad-signature` → `HTTP 403 {"detail":"Invalid signature"}`.
- **Graph API từ chối.** Kịch bản có `"fail": {"graph_send": true}` (`ctl scenario --slug <slug> <file>`), gửi `send text …`: dòng FB `400`, `read log --grep "Failed to send message"`, rồi bot thử gửi tin xin lỗi (cũng 400).
- **Xác nhận lưu bền.** `read profile <psid> --disk` khớp `read profile <psid>`; sau `ctl down`, `data_after/customers.json` và `github/repos/fake-owner/fake-private-customers/contents/data/customers.json` có cùng hồ sơ.
- **Bằng chứng.** Thêm `| tee -a artifacts/verify/<slug>/transcript.txt` vào mỗi lệnh; `outbox.jsonl` và `app.log` đã ở `artifacts/verify/<slug>/`.

## Gotchas

- `POST /webhook` trả `{"status":"ok"}` trước khi xử lý: HTTP 200 không chứng minh bot đã trả lời.
- Model trả lời và trích xuất chạy song song: thứ tự hai dòng `AI chat` và `AI extract` đổi giữa các lần chạy, đừng assert thứ tự.
- Lần đầu chạm `customer_memory`, app kéo `customers.json` từ GitHub giả (`GH GET … 404`, fake chưa có file) rồi dùng file rỗng của bản sao. Mỗi tin có `GH GET` + `GH PUT` tới `fake-owner/fake-private-customers`: đó là sync, không phải lỗi.
- Postback dedup theo `postback.mid`; harness luôn gửi `mid` cho postback. Bỏ `mid` (sự kiện `raw`) thì key là `pb:<psid>:<timestamp>`.
- Sự kiện thiếu cả chữ lẫn referral (vd chỉ có ảnh đính kèm) bị bỏ qua, không trả lời; muốn thử thì dùng `send raw`.
- `fail.openai` làm OpenAI SDK tự thử lại (mặc định 2 lần): mỗi lời gọi thành 3 bản ghi `500`; hết model thì bot coi là escalate (xem [escalation-admin-reply.md](escalation-admin-reply.md)).
- Ảnh trong `[IMAGES:]` không cần tồn tại trong `static/` để Graph API giả nhận; muốn kiểm ảnh tải được thì `curl -o /dev/null -w '%{http_code}' <url>` (xem [static-messenger-profile.md](static-messenger-profile.md)).
