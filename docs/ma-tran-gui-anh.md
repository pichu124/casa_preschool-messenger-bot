# Ma trận trường hợp gửi ảnh cho phụ huynh

Mỗi nhánh của luật "Ảnh gửi phụ huynh" ([quyet-dinh-noi-dung.md](quyet-dinh-noi-dung.md), mục 3) là một dòng có mã, kết quả mong đợi và bộ kiểm phụ trách. Code: `_plan_images`, `_media_note`, `_send_reply_with_images`, `_record_images`, `_wait_for_first_media_sync` và token `[SEND:<loại>]` trong `app/main.py`; `ready` trong `app/media.py` (hạn chờ lần đồng bộ đầu); dòng `[HỆ THỐNG]` do `media_note` trong `app/ai_engine.py` viết.

Bản dữ liệu (đọc được bằng code) là `MATRIX` và `MEDIA_CASES` trong `scripts/eval_media_cases.py`; trang này là bản người đọc. `tests/test_eval_media.py` (chạy trong `./scripts/check.sh`) giữ hai bản khớp nhau và chặn thiếu: dòng `eval` phải có ca cùng mã trong `MEDIA_CASES`, dòng `pytest` phải có test đúng tên trong `tests/`, dòng `harness` phải có mã trong [features/media.md](../.claude/skills/verify-casa-bot/features/media.md); ca eval nào cũng thuộc một dòng `eval`. Thêm nhánh luật mới thì thêm dòng ở cả hai nơi cùng bộ kiểm của nó.

## Bộ kiểm

- `eval`: câu chữ hoặc hành vi của model quyết định kết quả (chủ đề trích xuất, tuổi/cơ sở đọc được, token `[SEND:]`, `[ESCALATE]`, câu hỏi lại). Chạy `.venv/bin/python scripts/eval_chat.py media` với API key thật (tốn phí: 38 ca, 48 lượt; mỗi lượt 2 lời gọi model của bot, cộng 1 lời gọi giám khảo cho mỗi lượt không chuyển tư vấn viên, 45 lượt khi bot chuyển đúng 3 lượt phải chuyển: ≈ 141 lời gọi, chưa kể lời gọi dự phòng khi một model lỗi). Bộ này gọi `app.main.process_message` như tin Messenger thật, với model theo `AI_MODEL_ORDER` có key; Graph, Telegram, Sheet, GitHub là fake ghi lại (request httpx tới các host đó bị chặn); `MEDIA_SYNC_ENABLED=true` với danh mục ảnh giả (`catalog_items`: học phí 2 hệ, thực đơn 2 hệ, thời khoá biểu 3 cơ sở theo nhóm tuổi, cơ sở vật chất 3 cơ sở); hồ sơ phụ huynh dựng theo từng ca trong thư mục tạm, không đụng `data/customers.json`; hôm nay là 24/10/2026. Exit 0 đạt, 1 có lượt vi phạm, 2 chưa kết luận (chưa có API key, mọi model lỗi, hoặc không vi phạm nào mà có lượt giám khảo chưa ra phán quyết).
- `pytest`: kết quả do code quyết định khi chủ đề/token đã biết; test dùng model giả (`tests/test_media_replies.py`).
- `harness`: cần app thật qua HTTP (Graph trả lỗi thật, ảnh phục vụ ở `/static/media`, biến môi trường lúc khởi động); skill `verify-casa-bot`, mã ghi ở hành trình tương ứng trong `features/media.md`.

## Mỗi lượt eval chấm gì

Code chấm mọi thứ xác định được:

- Ảnh đi ra đúng tập id fixture của lượt (không thừa, không thiếu), kể cả ảnh mẫu `static/thuc-don-mau.jpg` của Q&A.
- Có/không thẻ Telegram chuyển tư vấn viên; tin Telegram cho admin về ảnh (vd ảnh học phí tháng cũ) đúng như ca đòi, không có tin thừa.
- Lượt không chuyển tư vấn viên: không lộ token hay ghi chú (`[SEND:`, `[IMAGES:`, `[QUICK:`, `[ESCALATE]`, `[đã gửi ảnh`, `chưa gửi được]`) ra tin phụ huynh; không nêu số tiền; nút trả lời nhanh hỏi tuổi bé/cơ sở; cụm phải có/không được có của từng ca.

Luật câu chữ do giám khảo chấm (LLM-as-judge, `JUDGE_PROMPT` trong `scripts/eval_chat.py`): regex tiếng Việt đổi qua đổi lại giữa chấm oan câu đúng và bỏ lọt câu sai qua 4 vòng review, nên bộ media không còn regex ngữ nghĩa. Mỗi lượt không chuyển tư vấn viên là 1 lời gọi model nữa (model theo `AI_MODEL_ORDER`, cùng provider và key như bot; provider cố định temperature 0.3). Giám khảo nhận tin phụ huynh, câu trả lời của bot đã bỏ token, các ảnh thực sự đi ra lượt đó, và các khoá có/không của lượt; trả JSON `{khoá: true/false, …, "ly_do": "…"}` đúng các khoá được hỏi. Khoá:

- `promises_image`: nói/ngụ ý bot đang/sẽ gửi ảnh (bảng phí, thời khoá biểu, thực đơn, ảnh trường…) ngay trong chat; không tính tư vấn viên gửi sau qua Zalo khi phụ huynh để số, gửi "thông tin" bằng chữ, nói ảnh đã gửi ở trên, lời hỏi/mời.
- `asks_age`, `asks_campus`: HỎI thật tuổi bé / cơ sở quan tâm (câu kể như "Học phí tuỳ độ tuổi và cơ sở, …" không tính). Nút trả lời nhanh tuổi/cơ sở cũng tính là hỏi (code thấy được).
- `consultant_sends_image`: nói tư vấn viên sẽ gửi ảnh, thời khoá biểu, thực đơn, ảnh trường (không tính bảng phí qua Zalo sau khi để số).
- `says_cannot_send`: nói không gửi được ảnh trong chat (không tính nói ảnh tin trước lỗi rồi gửi lại ngay).
- `announces_image`: báo chính bot (em) đang gửi/gửi kèm ảnh ngay trong chat ("em gửi Ba/Mẹ …", "Ba/Mẹ xem ảnh bên dưới", "đây là thời khoá biểu…"); không tính tư vấn viên gửi sau, xin SĐT/Zalo để gửi bảng phí. Đây là nguồn chấm duy nhất cho "có ảnh đi thì báo em gửi" (không còn regex hay cụm "gửi" của ca): câu mặc định khi model bỏ qua dòng `[HỆ THỐNG]` ("… để tư vấn viên gửi Ba/Mẹ bảng phí chi tiết kèm ưu đãi ạ.") có chữ "gửi" và đúng ngoại lệ của `consultant_sends_image`, nên chỉ khoá này bắt được ở lượt có ảnh học phí.

Mặc định của mọi lượt không chuyển tư vấn viên (`expected_answers`): `consultant_sends_image` false; không ảnh đi thì `promises_image` false; có ảnh đi (Drive hay ảnh Q&A) thì `says_cannot_send` false và `announces_image` true. Ca thêm kỳ vọng riêng bằng `Step.expect` (vd `{"asks_age": True, "asks_campus": False}`). Prompt có 11 ví dụ biên lấy từ các vòng review ("Dạ em gửi Ba/Mẹ tham khảo ạ." là hứa; "… để tư vấn viên gửi Ba/Mẹ bảng phí xe đưa đón ạ.", "Dạ em gửi Ba/Mẹ một số thông tin về xe đưa đón ạ.", "Dạ em gửi Ba/Mẹ lịch tham quan ạ." không hứa; "Học phí tuỳ độ tuổi và cơ sở, Ba/Mẹ quan tâm cơ sở nào ạ?" hỏi cơ sở, không hỏi tuổi; "Bé nhà mình sinh năm bao nhiêu ạ" hỏi tuổi; có ảnh học phí: "Dạ học phí bên em tuỳ chương trình ạ. Nếu tiện, Ba/Mẹ để lại SĐT/Zalo để tư vấn viên gửi Ba/Mẹ bảng phí chi tiết kèm ưu đãi ạ." không báo gửi, "Dạ em gửi Ba/Mẹ bảng học phí bên dưới ạ" báo gửi; có ảnh thời khoá biểu: "Dạ ảnh thời khoá biểu lúc nãy chưa gửi được, em gửi lại Ba/Mẹ ạ" báo gửi, không nói không gửi được).

Mỗi lượt in phán quyết và lý do (`giám khảo (<model>): khoá=…; lý do: …`). Câu giám khảo khác khuôn JSON hoặc mọi model lỗi thì lượt đó chưa kết luận (`? giám khảo … không ra phán quyết`): không tính đạt, không tính vi phạm; vi phạm code của lượt đó vẫn tính. Giám khảo cũng là model nên có thể sai: lượt vi phạm phải đọc lý do và transcript trước khi sửa bot.

- Trạng thái dòng `[HỆ THỐNG]` gặp trong bộ (test với model giả đòi đủ cả 6): chắc chắn gửi ("Sau câu trả lời này …"), tuỳ chủ đề ("Nếu phụ huynh hỏi …: sau câu trả lời …"), thiếu thông tin ("… nên chưa gửi ảnh …"), đã gửi ("… đã gửi ở tin trước …"), hỏi cơ sở cho ảnh cơ sở vật chất, ảnh lỗi ở tin trước ("Ảnh … tin trước chưa gửi được …").

Heuristic và giám khảo chỉ để lọc nhanh: vẫn đọc transcript (`PH:`, `BOT (<model>):`, `ảnh: …; trích xuất: …`, `giám khảo …`).

## Chưa kiểm được

- Câu ghép báo gửi một ảnh và mời ảnh khác, câu mời "có muốn em gửi … không ạ?", token của ảnh chưa đủ điều kiện: model thật không bị ép nói đúng câu đó, nên chỉ kiểm ở pytest (model giả nói đúng câu). Eval vẫn bắt hậu quả: ảnh thừa so với tập mong đợi.
- Trần 5 ảnh một lượt và nút trên ảnh cuối: do code quyết định, chỉ pytest.
- Ảnh lỗi một phần (`GEN-FAIL-PARTIAL`, `GEN-FAIL-PARTIAL-CAMPUS`, `GEN-FAIL-IN-GROUP`): chỉ pytest, vì `fail.graph_image` của harness làm hỏng mọi ảnh; harness thử câu xin lỗi chung và "gửi lại" (`GEN-FAIL-RESEND-HARNESS`). Bộ eval không làm ảnh lỗi: `GEN-FAIL-RESEND-REPLY`, `GEN-FAIL-NO-RESEND-REPLY`, `GEN-FAIL-OTHER-TOPIC` dựng sẵn lịch sử có ghi chú "[ảnh … chưa gửi được]" và chấm việc model gắn hay không gắn `[SEND:timetable]` (ảnh đi hay không) cùng câu hứa.
- Ảnh học phí, cơ sở vật chất, thực đơn đã gửi không có dòng `[HỆ THỐNG]` "đã gửi" (chỉ thời khoá biểu có): `FEE-SENT-AGAIN` và `CSVC-SENT-AGAIN` đo model có tự đọc ghi chú `[đã gửi ảnh …]` trong lịch sử để không hứa gửi lại hay không.

## Học phí

| Mã | Trường hợp | Kết quả mong đợi | Bộ kiểm |
|---|---|---|---|
| `FEE-ASKED-READY` | Hỏi học phí, đã biết tuổi bé và cơ sở | Ảnh học phí của hệ (Mỹ Đình: qt-fee-10); câu báo em gửi, không con số, không nói không gửi được bảng phí | eval |
| `FEE-WAIT-AGE` | Hỏi học phí, biết cơ sở, chưa biết tuổi; lượt sau bấm nút tuổi | Lượt 1 không ảnh, hỏi tuổi bé (không hỏi lại cơ sở); lượt 2 ảnh học phí hệ Song ngữ (cờ fee_asked chờ) | eval |
| `FEE-WAIT-CAMPUS` | Hỏi học phí, biết tuổi, chưa biết cơ sở; lượt sau bấm nút cơ sở | Lượt 1 không ảnh, hỏi cơ sở; lượt 2 ảnh học phí hệ Quốc tế | eval |
| `FEE-BOTH-SYSTEMS` | Xin học phí "2 hệ" khi chưa rõ cơ sở Quốc tế | Ảnh học phí cả hai hệ (sn-fee-10, qt-fee-10), không hỏi cơ sở | eval |
| `FEE-SENT-AGAIN` | Ảnh học phí tháng này đã gửi, phụ huynh xin lại | Không ảnh; không hứa gửi; nói ảnh đã gửi ở trên | eval |
| `FEE-NOT-ASKED-READY` | Đủ tuổi và cơ sở nhưng hỏi chuyện khác (camera) | Không ảnh học phí (dòng "Nếu phụ huynh hỏi học phí" không được gắn [SEND:fee]) | eval |
| `FEE-PHONE-ASK-OTHER-TOPIC` | Tin bot trước xin SĐT "để em gửi bảng học phí", phụ huynh hỏi xe đưa đón, chưa biết tuổi | Không ảnh nào | eval |
| `FEE-REFUSE-PHONE-CAMPUS` | Đã từ chối để số, biết cơ sở, chưa biết tuổi, đòi giá | Ảnh học phí hệ Quốc tế; không [ESCALATE]; không xin SĐT lại | eval |
| `FEE-REFUSE-PHONE-NO-CAMPUS` | Từ chối để số mà đòi giá, chưa biết cơ sở | Không ảnh; hỏi cơ sở; không [ESCALATE]; không xin SĐT | eval |
| `FEE-ASKED-BEFORE-THEN-REFUSE` | Tin trước hỏi học phí (cờ fee_asked), bot xin SĐT, tin này không để số; biết cơ sở, chưa biết tuổi | Ảnh học phí hệ Quốc tế (dòng chắc chắn gửi); không xin SĐT lại | eval |
| `FEE-STALE` | Drive chỉ có ảnh học phí tháng trước | Gửi ảnh tháng cũ (qt-fee-9) và một tin Telegram "Chưa có ảnh học phí mới tháng 10" | eval |
| `FEE-NO-NUMBER` | Đòi con số cụ thể, đủ tuổi và cơ sở | Ảnh học phí hệ Song ngữ; không viết số tiền; không nói không gửi được bảng phí | eval |
| `FEE-ONCE-A-MONTH` | Ảnh học phí chờ đủ tuổi + cơ sở, rồi mỗi tháng 1 lần | Đã gửi tháng này thì không gửi lại; tháng sau hỏi lại thì gửi | pytest `test_fee_image_waits_for_age_and_campus_then_goes_once_a_month` |
| `FEE-KIM-MA-NO-FOLDER` | Drive thiếu thư mục cơ sở Kim Mã | Vẫn gửi ảnh học phí hệ Song ngữ (hệ theo bảng CAMPUS_SYSTEMS) | pytest `test_kim_ma_parent_gets_the_bilingual_fee_even_without_a_kim_ma_folder_on_drive` |
| `FEE-PHONE-ASK-NO-TOKEN` | Câu trả lời xin SĐT "để em gửi bảng học phí chi tiết" (không token) | Không ảnh học phí, không cờ fee_asked | pytest `test_asking_the_phone_to_send_the_fee_table_sends_no_fee_image` |
| `FEE-NOAGE-ONLY-IF-ASKED` | Chưa biết tuổi, tin bot trước xin SĐT, phụ huynh hỏi chuyện khác mà câu trả lời gắn [SEND:fee] | Không ảnh, không cờ fee_asked (tuổi biết sau cũng không tự gửi) | pytest `test_fee_without_the_age_goes_only_to_a_parent_asking_the_fee` |
| `FEE-MULTI-SYSTEM` | Hồ sơ nhiều cơ sở khác hệ ("Chùa Láng, Kim Mã") | Mỗi hệ một ảnh học phí | pytest `test_fee_of_two_campuses_of_different_systems_is_one_image_each` |
| `FEE-BOTH-THEN-CAMPUS` | Sau ảnh học phí "2 hệ", tin sau nêu cơ sở Quốc tế | Không ảnh nào nữa, cờ fee_asked đã xoá | pytest `test_fee_of_both_systems_goes_without_knowing_the_international_campus` |
| `FEE-STALE-ONCE-A-DAY` | Ảnh học phí tháng cũ gửi nhiều phụ huynh trong ngày | Tin Telegram nhắc trường tối đa 1 lần mỗi hệ mỗi ngày | pytest `test_stale_fee_image_is_sent_and_the_school_is_reminded_once_a_day` |
| `FEE-LAST-YEAR-STALE` | Thư mục tháng này là ảnh sửa hơn 300 ngày trước | Vẫn gửi, coi là ảnh cũ và nhắc trường | pytest `test_last_years_fee_image_of_this_month_is_sent_and_the_school_is_reminded` |
| `FEE-NEXT-MONTH-UNASKED` | Hỏi lại học phí trong tháng đã gửi | Không để cờ chờ; tháng sau không tự gửi khi phụ huynh không hỏi | pytest `test_fee_asked_again_in_the_same_month_does_not_send_next_month_unasked` |
| `FEE-NO-DRIVE-IMAGE` | Drive không có ảnh học phí của hệ | Không ảnh, không cờ chờ | pytest `test_fee_asked_while_drive_has_no_fee_image_of_the_system_does_not_wait` |

## Thời khoá biểu

| Mã | Trường hợp | Kết quả mong đợi | Bộ kiểm |
|---|---|---|---|
| `TKB-WAIT-BOTH` | Xin thời khoá biểu khi chưa biết cơ sở lẫn tuổi; lượt sau nêu cả hai | Lượt 1 không ảnh, hỏi cơ sở và tuổi, không nói tư vấn viên sẽ gửi; lượt 2 ảnh km-tkb-36-72 | eval |
| `TKB-WAIT-AGE` | Biết cơ sở, thiếu tuổi; lượt sau bấm nút "Dưới 2 tuổi" | Lượt 1 không ảnh, hỏi tuổi (không hỏi cơ sở); lượt 2 ảnh md-tkb-15-36 | eval |
| `TKB-WAIT-CAMPUS` | Biết tuổi, thiếu cơ sở; lượt sau bấm nút cơ sở | Lượt 1 không ảnh, hỏi cơ sở (không hỏi tuổi); lượt 2 ảnh cl-tkb-36-60 | eval |
| `TKB-READY` | Xin thời khoá biểu, đã biết cơ sở và tuổi | Ảnh thời khoá biểu đúng cơ sở và nhóm tuổi; câu báo em gửi | eval |
| `TKB-CAMBRIDGE` | Hỏi Cambridge, đã biết cơ sở và tuổi | Trả lời về Cambridge và gửi thời khoá biểu (cl-tkb-36-60) | eval |
| `TKB-PROGRAMME-TOPIC` | Hỏi chương trình học (dòng "Nếu phụ huynh hỏi …"), đủ thông tin | Ảnh md-tkb-15-36 (theo chủ đề trích xuất hoặc token [SEND:timetable]) | eval |
| `TKB-MULTI-CAMPUS` | Hội thoại thật: xin TKB, nêu "Chùa Láng và Kim Mã", bấm tuổi, rồi xin "2 hệ" | Hỏi cơ sở + tuổi, rồi hỏi tuổi; lượt bấm tuổi gửi cl-tkb-36-60 và km-tkb-36-72; xin lại không ảnh, nói ảnh ở trên | eval |
| `TKB-BOTH-SYSTEMS-UNKNOWN` | Xin TKB "2 hệ" khi chưa rõ cơ sở Quốc tế | Gửi TKB Kim Mã, hỏi Chùa Láng hay Mỹ Đình; lượt sau nêu Mỹ Đình thì gửi md-tkb-36-60 | eval |
| `TKB-SENT-AGAIN` | Xin lại thời khoá biểu đã gửi | Không ảnh; nói ảnh ở phía trên; không hứa gửi, không nói tư vấn viên sẽ gửi | eval |
| `TKB-TRIAL-WEEK` | "lịch học thử 1 tuần" (tuần học thử, không phải TKB) | Không ảnh thời khoá biểu | eval |
| `TKB-WEEKDAY` | "lịch học từ thứ 2 đến thứ 6", đủ thông tin | Ảnh thời khoá biểu; không [ESCALATE] | eval |
| `TKB-DAILY-NO-ESCALATE` | Hỏi lịch học từng giờ trong ngày khi có ảnh TKB | Ảnh thời khoá biểu; trả lời chung, không [ESCALATE] | eval |
| `TKB-HOLIDAY-ESCALATE` | Hỏi lịch học hè (không có trong Q&A) | [ESCALATE], thẻ Telegram, không ảnh | eval |
| `TKB-BIRTH-YEAR` | Tuổi ghi theo năm sinh ("sinh năm 2022") | Tính ra 51 tháng: ảnh md-tkb-36-60; không hỏi lại tuổi | eval |
| `TKB-NO-DRIVE-IMAGE` | Drive không có TKB cho cơ sở/tuổi đó | Không ảnh, không cờ chờ | pytest `test_timetable_that_drive_does_not_have_does_not_wait` |
| `TKB-PROGRAM-NOT-CAMPUS` | Chỉ biết hệ quan tâm (song ngữ/quốc tế), chưa biết cơ sở | Không đoán cơ sở theo hệ: không ảnh | pytest `test_the_programme_the_parent_wants_does_not_pick_the_timetable_campus` |
| `TKB-ENROL-YEAR` | "tuyển sinh 2025" trong tin | Không phải năm sinh, vẫn hỏi tuổi | pytest `test_enrolment_year_in_the_message_is_not_the_kids_age` |
| `TKB-TRIAL-NO-ACCENT` | "lich hoc thu …" không dấu | Chỉ là TKB khi sau "thu" là 2–7/hai/bay | pytest `test_trial_week_schedule_is_not_a_timetable_question` |
| `TKB-TRIAL-REPLY-NO-WAIT` | Câu trả lời gửi lịch học thử | Không ảnh TKB, không cờ chờ tuổi | pytest `test_a_reply_sending_the_trial_week_does_not_wait_for_the_kids_age` |
| `TKB-BOTH-NAMED-EARLIER` | "2 hệ" sau khi đã nêu các cơ sở ở tin trước | TKB của mọi cơ sở đã nêu | pytest `test_both_systems_asked_for_get_the_timetables_of_the_campuses_named_earlier` |
| `TKB-BOTH-CAMPUS-WORDS` | "cả 2 cơ sở"/"hai bên"/"2 trường" (BOTH_WORDS không phải "hệ") | TKB của mọi cơ sở đã nêu trong hội thoại; chỉ nêu Kim Mã thì chỉ TKB Kim Mã: không thêm hệ chưa rõ, không hỏi cơ sở, không cờ chờ | pytest `test_both_campuses_get_the_timetables_of_every_campus_named_and_no_system_not_named` |
| `TKB-DECLINED-IN-WORDS` | Phụ huynh từ chối bằng chữ: "Không cần gửi lại thời khoá biểu đâu em" (TKB chưa gửi, đủ tuổi và cơ sở) | Giới hạn đã biết, chưa sửa: _asks_timetable đọc chữ tin phụ huynh nên vẫn gửi km-tkb-36-72; test ghi hành vi hiện tại, người vận hành quyết sau | pytest `test_a_parent_declining_the_timetable_in_words_still_gets_it` |

## Cơ sở vật chất

| Mã | Trường hợp | Kết quả mong đợi | Bộ kiểm |
|---|---|---|---|
| `CSVC-WAIT-CAMPUS` | Hỏi cơ sở vật chất khi chưa biết cơ sở; lượt sau bấm Kim Mã | Lượt 1 không ảnh, hỏi cơ sở; lượt 2 bốn ảnh km-csvc-1..4 | eval |
| `CSVC-READY` | Hỏi cơ sở vật chất, đã biết cơ sở | Bốn ảnh cl-csvc-1..4 | eval |
| `CSVC-SENT-AGAIN` | Xin lại ảnh cơ sở đã gửi | Không ảnh; không hứa gửi; nói ảnh đã gửi ở trên | eval |
| `CSVC-OTHER-CAMPUS-AFTER` | Đã gửi ảnh Kim Mã, tin sau nhắc Mỹ Đình (không hỏi ảnh) | Không ảnh (không tự gửi ảnh cơ sở khác) | eval |
| `CSVC-INVITE-NO-TOKEN` | Câu mời "có muốn em gửi ảnh … không ạ?" (không token) | Không ảnh | pytest `test_an_offer_to_send_images_is_not_saying_they_are_sent` |
| `CSVC-MULTI-CAMPUS` | Nhiều cơ sở | Một cơ sở mỗi lượt (2 cơ sở là 8 ảnh, quá trần 5) | pytest `test_facilities_of_two_campuses_go_one_campus_a_turn` |
| `CSVC-NO-IMAGES-NO-WAIT` | Cơ sở không có ảnh cơ sở vật chất | Không ảnh, không cờ chờ | pytest `test_facilities_of_a_campus_without_images_do_not_wait` |
| `CSVC-ASKED-AGAIN-NO-WAIT` | Hỏi lại cơ sở vật chất khi ảnh cơ sở đó đã gửi | Cờ facilities_asked không bật lại; tin sau nhắc cơ sở khác không nhận ảnh | pytest `test_facilities_asked_again_after_the_images_went_does_not_wait_for_another_campus` |

## Thực đơn

| Mã | Trường hợp | Kết quả mong đợi | Bộ kiểm |
|---|---|---|---|
| `MENU-KNOWN-SYSTEM` | Hỏi thực đơn, biết cơ sở Kim Mã | Ảnh thực đơn hệ Song ngữ (sn-menu), không ảnh mẫu cũ của Q&A | eval |
| `MENU-UNKNOWN-SYSTEM` | Hỏi thực đơn, chưa biết hệ | Ảnh thực đơn hệ Quốc tế (qt-menu) | eval |
| `MENU-NO-DRIVE` | Drive chưa có ảnh thực đơn | Ảnh thực đơn mẫu của Q&A (static/thuc-don-mau.jpg, model gắn [IMAGES:]) | eval |
| `MENU-REPLACES-QA` | Model gắn ảnh mẫu của Q&A khi Drive có thực đơn | Chỉ ảnh thực đơn Drive, bỏ ảnh mẫu cũ | pytest `test_menu_of_kim_ma_is_the_drive_image_not_the_old_sample` |
| `MENU-ONCE` | Xin lại thực đơn đã gửi | Không ảnh (mỗi ảnh một lần: khoá menu:<id>), không dòng [HỆ THỐNG] thực đơn | pytest `test_menu_goes_once_to_each_parent` |
| `MENU-BY-PROGRAM` | Chưa biết cơ sở, hồ sơ có hệ quan tâm (interested_program) | Ảnh thực đơn của hệ đó (song ngữ: sn-menu, quốc tế: qt-menu) | pytest `test_menu_without_a_campus_is_the_one_of_the_programme_the_parent_wants` |

## Chung

| Mã | Trường hợp | Kết quả mong đợi | Bộ kiểm |
|---|---|---|---|
| `GEN-ESCALATE-NO-IMAGE` | Lượt [ESCALATE] (tên giáo viên cụ thể) có kèm chủ đề ảnh | Thẻ Telegram, không ảnh | eval |
| `GEN-UPSET-NO-IMAGE` | Phụ huynh bực vì bị đòi số, đòi bảng học phí (đủ điều kiện gửi) | Câu xin lỗi + thẻ Telegram, không ảnh | eval |
| `GEN-ESCALATE-UPSET-CODE` | Chuyển tư vấn viên hoặc upset với model giả | Không ảnh, không ghi media_sent | pytest `test_no_image_when_the_parent_goes_to_a_consultant` |
| `GEN-COMPOUND-SEND-INVITE` | Câu ghép: báo gửi học phí + mời xem ảnh cơ sở vật chất | Chỉ ảnh học phí | pytest `test_a_reply_sending_the_fee_and_offering_the_facilities_sends_only_the_fee` |
| `GEN-TOKEN-TAGGED` | Câu trả lời gắn `[SEND:<loại>]` khi trích xuất sót chủ đề | Ảnh của dòng "Nếu phụ huynh hỏi …" vẫn đi | pytest `test_an_image_the_reply_tags_as_sent_goes_even_if_the_extraction_missed_its_topic` |
| `GEN-TOKEN-NOT-READY` | Token [SEND] cho ảnh chưa đủ điều kiện (thiếu tuổi/cơ sở) | Không ảnh, không cờ chờ | pytest `test_a_send_token_of_an_image_not_ready_sends_nothing_and_waits_for_nothing` |
| `GEN-TOKEN-HIDDEN` | Token [SEND:] trong câu trả lời | Không lộ ra tin phụ huynh, không lưu vào lịch sử (eval cũng kiểm mọi lượt) | pytest `test_the_send_token_is_neither_shown_to_the_parent_nor_kept_in_the_history` |
| `GEN-SENT-NOTE-HIDDEN` | Model chép ghi chú "[đã gửi ảnh …]" vào câu trả lời | Ghi chú không lộ ra tin phụ huynh | pytest `test_model_copying_the_sent_note_is_not_shown_to_the_parent` |
| `GEN-MAX-FIVE` | Một lượt có hơn 5 ảnh | Tối đa 5 ảnh theo thứ tự học phí, thời khoá biểu, thực đơn, cơ sở vật chất; nút trên ảnh cuối | pytest `test_at_most_five_images_in_one_turn` |
| `GEN-NOT-FIT-NEXT-TURN` | Nhóm ảnh cơ sở vật chất không vừa trần 5 ảnh | Cờ facilities_asked còn: lượt sau ("dạ vâng") 4 ảnh đi, cờ xoá | pytest `test_images_that_did_not_fit_go_on_the_next_turn` |
| `GEN-NOT-FIT-MENU` | Ảnh thực đơn không vừa trần 5 ảnh (2 học phí + 3 thời khoá biểu) | Thực đơn không có cờ chờ: lượt sau không ảnh; hỏi lại thực đơn thì đi | pytest `test_a_menu_that_did_not_fit_waits_until_the_parent_asks_again` |
| `GEN-TOKENS-ONLY` | Câu trả lời chỉ có token ([IMAGES:]/[QUICK:]), không chữ | Không tin chữ rỗng; chỉ ảnh, nút trên ảnh cuối | pytest `test_a_reply_of_only_tokens_sends_only_the_images_with_the_buttons` |
| `GEN-QUICK-ON-LAST` | Lượt có ảnh và nút trả lời nhanh | Nút nằm trên ảnh cuối | pytest `test_facilities_wait_for_the_campus_then_go_once_with_buttons_on_the_last_image` |
| `GEN-FAIL-RETRY` | Graph từ chối ảnh duy nhất của lượt (học phí) | Lượt vẫn xong, câu xin lỗi chung, ảnh chưa tính là đã gửi, lịch sử ghi "[ảnh … chưa gửi được]"; không tự thử lại, chỉ gửi khi phụ huynh hỏi lại (lượt sau hỏi học phí thì ảnh đi) | pytest `test_a_failed_image_does_not_break_the_turn_and_goes_when_asked_again` |
| `GEN-FAIL-NO-AUTO-RETRY` | Ảnh cơ sở vật chất lỗi, lượt sau phụ huynh chỉ bấm nút tuổi | Không gửi lại, không xin lỗi lại, dòng [HỆ THỐNG] không có "Sau câu trả lời này … cơ sở vật chất"; hỏi lại ảnh trường thì gửi | pytest `test_failed_images_are_not_tried_again_until_the_parent_asks_again` |
| `GEN-FAIL-IN-GROUP` | 1 trong 4 ảnh cơ sở vật chất của cơ sở lỗi | 3 ảnh còn lại đi, nhóm tính là đã gửi (media_sent), không câu xin lỗi; báo nhóm Telegram | pytest `test_some_photos_of_the_facilities_failing_count_as_sent_without_an_apology` |
| `GEN-FAIL-QA-IMAGE` | Ảnh Q&A (static/thuc-don-mau.jpg) lỗi | Log WARNING, không câu xin lỗi, không báo nhóm Telegram (như trước khi có ảnh Drive) | pytest `test_a_failed_qa_image_is_skipped_without_an_apology_nor_an_alert` |
| `GEN-FAIL-ALERT` | Ảnh Drive gửi lỗi | Báo nhóm Telegram tối đa 1 lần mỗi giờ, không có tin của phụ huynh | pytest `test_a_failed_image_tells_the_admin_group_once_an_hour_without_the_parents_message` |
| `GEN-FAIL-APOLOGY` | Mọi ảnh Drive định gửi của lượt đều lỗi | Thêm câu xin lỗi ảnh lỗi kèm nút | pytest `test_parent_told_the_images_failed_when_every_drive_image_promised_failed` |
| `GEN-FAIL-PARTIAL` | Ảnh lỗi một phần: xin "học phí và thời khoá biểu", chỉ ảnh thời khoá biểu lỗi | Ảnh học phí đi; câu xin lỗi nêu "thời khoá biểu cơ sở Kim Mã" kèm nút; lịch sử "[đã gửi ảnh học phí …] [ảnh thời khoá biểu … chưa gửi được]"; không cờ chờ: "dạ vâng" không ảnh | pytest `test_a_partly_failed_turn_apologises_for_the_image_that_failed_and_does_not_try_it_again_unasked` |
| `GEN-FAIL-PARTIAL-CAMPUS` | Thời khoá biểu hai cơ sở, chỉ ảnh Kim Mã lỗi | Ảnh Chùa Láng đi; câu xin lỗi nêu "thời khoá biểu cơ sở Kim Mã" | pytest `test_apology_names_the_campus_whose_timetable_failed` |
| `GEN-FAIL-RESEND` | Ngay sau câu xin lỗi (tin bot trước có "[ảnh … chưa gửi được]"), câu trả lời của model gắn [SEND:<loại>] (học phí, thời khoá biểu, cơ sở vật chất, thực đơn) | Dòng [HỆ THỐNG] "Ảnh <nhãn> tin trước chưa gửi được. Nếu phụ huynh xin gửi lại …" cho đúng ảnh lỗi, không "Sau câu trả lời này …"; ảnh đó đi, ghi media_sent | pytest `test_a_failed_image_goes_again_when_the_reply_to_the_parent_asking_tags_it` |
| `GEN-FAIL-RESEND-PARTIAL` | Lượt trước ảnh học phí tới, thời khoá biểu lỗi; câu trả lời gắn [SEND:timetable] | Chỉ dòng ảnh lỗi của thời khoá biểu; chỉ ảnh thời khoá biểu đi (học phí không gửi lại); lượt sau không còn dòng ảnh lỗi | pytest `test_only_the_image_that_failed_is_offered_again_after_a_partly_failed_turn` |
| `GEN-FAIL-NO-RESEND` | Sau câu xin lỗi, câu trả lời không gắn token ("không cần em gửi lại đâu", "dạ vâng", kể cả "em gửi lại ảnh đi") | Không ảnh dù tin có chữ "gửi lại": code không đọc chữ của phụ huynh, model quyết định bằng token | pytest `test_a_failed_image_does_not_go_again_when_the_reply_does_not_tag_it` |
| `GEN-FAIL-RESEND-HARNESS` | App thật, Graph từ chối mọi ảnh (fail.graph_image) của lượt học phí + thời khoá biểu, rồi hết lỗi | Câu xin lỗi chung; "dạ vâng" chỉ TEXT; "em gửi lại ảnh đi" (fake chat trả câu có [SEND:fee] [SEND:timetable]) gửi cả hai ảnh, ghi media_sent; "không cần em gửi lại đâu" (câu không token) chỉ TEXT | harness |
| `GEN-FAIL-RESEND-REPLY` | Lịch sử có ảnh thời khoá biểu lỗi, phụ huynh "em gửi lại ảnh đi" (trích xuất không chủ đề) | Model gắn [SEND:timetable]: ảnh km-tkb-36-72; câu báo em gửi, không nói ảnh ở phía trên | eval |
| `GEN-FAIL-NO-RESEND-REPLY` | Lịch sử có ảnh thời khoá biểu lỗi, phụ huynh "không cần em gửi lại đâu, chị xem web rồi" | Model không gắn token: không ảnh; không hứa gửi ảnh | eval |
| `GEN-FAIL-OTHER-TOPIC` | Lịch sử có ảnh thời khoá biểu lỗi, phụ huynh hỏi chuyện khác (xe đưa đón) | Không ảnh; không hứa gửi lại ảnh, không nhắc "gửi lại" | eval |
| `GEN-FAIL-HARNESS` | Graph thật trả 400 cho ảnh (app chạy cách ly) | IMAGE 400, thẻ ⚠️ Gửi ảnh … bị lỗi, câu xin lỗi; log không có token | harness |
| `GEN-SYNC-OFF` | Tắt đồng bộ hoặc danh mục rỗng | Không ảnh Drive, không dòng [HỆ THỐNG] | pytest `test_without_drive_images_the_bot_behaves_as_before` |
| `GEN-SYNC-OFF-HARNESS` | App chạy không MEDIA_SYNC_ENABLED, hỏi thực đơn | Ảnh static/thuc-don-mau.jpg như cũ, không dòng [HỆ THỐNG] | harness |
| `GEN-URL-SERVED-HARNESS` | URL ảnh gửi phụ huynh | `GET /static/media/<id>.jpg` trả 200 image/jpeg | harness |
| `GEN-LOG-PLANNED` | Mỗi lượt khi bật đồng bộ | Log INFO các ảnh định gửi | pytest `test_every_turn_logs_the_drive_images_it_plans_to_send` |
| `GEN-GRAPH-NO-TOKEN` | Lỗi Graph khi gửi ảnh/tin | Log và lỗi không có access token | pytest `test_graph_errors_are_logged_and_raised_without_the_access_token` |
| `GEN-TEST-CHAT` | /test-chat | Model nhận đúng dòng [HỆ THỐNG] như Messenger | pytest `test_test_chat_tells_the_model_which_images_follow_like_messenger` |
| `GEN-TEST-CHAT-NO-TOKEN` | /test-chat với câu trả lời có [SEND:] | Lịch sử không giữ token | pytest `test_test_chat_keeps_no_send_token_in_the_history` |

## Lần đồng bộ ảnh đầu sau khởi động

| Mã | Trường hợp | Kết quả mong đợi | Bộ kiểm |
|---|---|---|---|
| `SYNC-WAIT` | Tin tới khi lần đồng bộ đầu còn chạy (đĩa trống) | Chờ đồng bộ xong rồi trả lời: dòng "Sau câu trả lời này …" và ảnh; không WARNING | pytest `test_a_message_right_after_start_waits_for_the_first_sync_and_gets_the_timetable` |
| `SYNC-START-HARNESS` | App thật, tin ngay sau READY | TEXT rồi IMAGE; log first sync done | harness |
| `SYNC-SLOW` | Đồng bộ đầu lâu hơn MEDIA_FIRST_SYNC_WAIT | Trả lời không ảnh sau hạn; một WARNING | pytest `test_a_first_sync_slower_than_the_wait_still_gets_an_answer_without_images` |
| `SYNC-DEADLINE` | Nhiều tin tới trong và sau lúc chờ đồng bộ đầu | Một hạn chung = lúc bắt đầu đồng bộ + MEDIA_FIRST_SYNC_WAIT: tin giữa chừng chờ phần còn lại, tin sau hạn không chờ; WARNING một lần | pytest `test_every_message_waits_for_the_first_sync_until_one_deadline` |
| `SYNC-TYPING` | Đang chờ đồng bộ đầu | "đang soạn" bật lại mỗi TYPING_REFRESH_EVERY, dừng khi xong | pytest `test_waiting_for_the_first_sync_keeps_the_typing_indicator_on` |
| `SYNC-OFF-NO-WAIT` | Tắt MEDIA_SYNC_ENABLED hoặc thiếu LEADS_SHEET_WEBHOOK_URL | Không chờ, không gọi Apps Script | pytest `test_with_media_sync_off_a_message_does_not_wait` |
| `SYNC-FAILED` | Lần đồng bộ đầu lỗi | Tin đó trả lời khi lỗi; tin sau không chờ lần đồng bộ kế | pytest `test_a_failed_first_sync_answers_then_and_no_later_message_waits` |
| `SYNC-DISK` | Ảnh của lần chạy trước còn trên đĩa | Dùng ngay, không chờ | pytest `test_images_kept_on_disk_from_before_the_restart_are_used_without_waiting` |
| `SYNC-TEST-CHAT` | /test-chat ngay sau khởi động | Chờ đồng bộ đầu như Messenger | pytest `test_test_chat_right_after_start_waits_for_the_first_sync` |
