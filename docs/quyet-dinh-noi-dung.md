# Quyết định nội dung tư vấn của bot Casa

Nguồn sự thật cho `data/qa_database.json` và `SYSTEM_PROMPT` trong `app/ai_engine.py`. `tests/test_knowledge.py` và `tests/test_prompt.py` kiểm các quyết định này; đổi quyết định thì sửa file này, dữ liệu và test cùng lúc.

Thứ tự ưu tiên khi mâu thuẫn: (1) phản hồi của trường bên dưới > (2) cột "Lưu ý / SỬA LẠI" trong file kịch bản tư vấn > (3) cột "Gợi ý trả lời" > (4) dữ liệu cũ.

## 1. Phản hồi của trường, đợt 1 (nguyên văn)

1. Tuổi nhận: - 15 tháng đi vững
2. Ưu đãi: Với tư vấn ban đầu phụ huynh cố gắng xin số điện thoại trước, nếu PH k đồng ý cho thì có thể chào ưu đãi hấp dẫn. Bỏ qua các mốc 10% hay 5% vì tùy theo chương trình có thể có những đợt giảm giá ưu đãi khác nhau.
3. Ưu đãi anh chị em, cư dân tòa nhà cũng tương tự sẽ thông báo là có, xin số để tư vấn chi tiết. Nếu PH k đồng ý thì sẽ điều hướng trả lời xin thông tin cơ sở quan tâm vì mỗi cơ sở sẽ có chính sách khác nhau. Với hệ Quốc tế là Mỹ Đình và Chùa láng, giảm 10% bé thứ 2 khi 2 anh em cùng theo học tại trường cho tới khi anh/em ra trường và giảm thêm 5% chính sách cư dân tòa nhà tới khi ra trường. Với hệ Kim Mã thì giảm 5% bé thứ 2 khi 2 anh em cùng theo học tại trường cho tới khi anh/em ra trường, k có chính sách cư dân
4. Voucher đồng phục -> bỏ qua vì theo tùy chính sách chương trình mới có
5. Đón muộn: Đón muộn kể từ 17h30 sẽ có khung phí thu muộn riêng. Để hỗ trợ phụ huynh thì Nhà trường có gói đăng ký trông muộn, trông sớm theo tháng
6. Đón con: Nhà trường có hỗ trợ cô dẫn bé xuống sảnh trong trường hợp phụ huynh có việc gấp.....
7. Diện tích mỹ đình: 80-90m2
8. Tần suất dã ngoại: 6 chuyến/năm
9. CHương trình đã chuyển hết qua Cambridge

## 2. Phản hồi của trường, đợt 2 (nguyên văn)

2. Bảng học phí chi tiết thì k gửi trên chat, mục tiêu điều hướng xin số điện thoại để tư vấn hoặc gửi. Nếu PH trả lời k cho, điều hướng để nhân viên trả lời trực tiếp
3. Bỏ phần workshop đi
4. Thực đơn mẫu ok có thể gửi cho PH tham khảo luôn
5. Lead gửi vào nhóm đang dùng đồng thời đẩy qua gg sheet cho dễ lưu trữ thông tin
6. Tạm thời k tư vấn xe bus
7. Đồng ý k hỏi thẳng ngân sách

## 2b. Phản hồi của trường, đợt 3 (phần duyệt nội dung, nguyên văn)

a, 4 câu gợi ý
- Học phí của trường là bao nhiêu?
- Trường nhận bé từ bao nhiêu tháng?
- Hiện tại Nhà trường có ưu đãi gì?
- Có chương trình học thử miễn phí cho học sinh mới không?
b. Tin đầu tiên: Cơ sở quan tâm - chương trình học - đặt lịch tham quan - ưu đãi
Độ tuổi của bé: Dưới 2 tuổi, 2-3 tuổi, 3-5 tuổi, 5-6 tuổi
Còn lại ok
c. (3 mẫu tin nhắc lại — dùng nguyên văn trong `app/followup.py`)
d. Chưa bật
e. Giữ
f. có nới
- Hệ Kim Mã bị chê đắt thì sao lại gợi ý tham khảo hệ Kim Mã, hệ quốc tế là Chùa Láng và Mỹ Đình chứ
- Xe bus: Sẽ tư vấn theo kiểu hiện tại Nhà trường chưa có tuyến xe bus, khi nào có đủ phụ huynh đăng ký nhà trường sẽ tiến hành mở tuyến xe bus

## 3. Cách bot áp dụng

- Nhận bé từ 15 tháng, đã đi vững.
- Học phí: không nêu con số, không gửi bảng phí trên chat. Hỏi tuổi bé + cơ sở, kể giá trị trước, rồi xin SĐT/Zalo để tư vấn viên tư vấn/gửi bảng phí. Phụ huynh không cho số mà vẫn muốn biết → chuyển nhân viên trả lời trực tiếp (`[ESCALATE]`).
- Ưu đãi theo kỳ đóng và khuyến mãi: xin SĐT trước; không cho số → chỉ nói "ưu đãi hấp dẫn, tùy từng đợt/chương trình", không nêu %.
- Ưu đãi anh chị em ruột / cư dân tòa nhà: nói là có, xin SĐT; không cho số → hỏi cơ sở rồi nêu đúng chính sách cơ sở đó:
  - Hệ Quốc tế (Mỹ Đình, Chùa Láng): bé thứ 2 giảm 10% tới khi anh/em ra trường; cư dân tòa nhà giảm thêm 5% tới khi ra trường.
  - Hệ Song ngữ (Kim Mã): bé thứ 2 giảm 5% tới khi anh/em ra trường; không có chính sách cư dân.
- Đồng phục: bắt buộc theo quy định; không nhắc voucher.
- Đón muộn từ 17h30 có khung phí riêng; có gói trông muộn, trông sớm theo tháng. Không nêu số tiền.
- Đón con: cô hỗ trợ dẫn bé xuống sảnh khi phụ huynh có việc gấp.
- Diện tích lớp: Mỹ Đình 80–90 m²; Chùa Láng 90–100 m².
- Dã ngoại: 6 chuyến/năm.
- Chương trình: 3–6 tuổi học Cambridge Early Years là khung chính, Montessori là phương pháp và giáo cụ bổ trợ; 15 tháng–3 tuổi xây nền tảng qua Montessori, làm quen tiếng Anh với giáo viên nước ngoài.
- Bỏ toàn bộ nội dung workshop của cô Phan Thúy (sheet "Workshop" trong kịch bản). Câu trả lời về sự kiện chung của trường (Family Day, workshop, lễ hội…) vẫn giữ — chờ trường xác nhận (docs/dot-3-can-bo-sung.md, mục C6).
- Xe bus: hiện Nhà trường chưa có tuyến xe bus; khi đủ phụ huynh đăng ký, Nhà trường sẽ mở tuyến. Bot mời để lại khu vực nhà + SĐT/Zalo để ghi nhận nhu cầu.
- Khi phụ huynh chê đắt (CARE): không gợi ý hệ/cơ sở khác như phương án rẻ hơn; nêu giá trị khác biệt và mời học thử/tham quan.
- Câu hỏi gợi ý, nút trả lời nhanh, mẫu tin nhắc lại: theo mục 2b. Tin nhắc lại vẫn tắt.
- SĐT: nhận cả số thiếu số 0 đầu, viết tách lạ, số nước ngoài.
- Thực đơn mẫu: gửi thẳng cho phụ huynh khi đã có file trong Q&A (trường `images`).
- Không hỏi thẳng ngân sách; có thể hỏi gia đình cân nhắc hệ Quốc tế hay Song ngữ.
- Tài liệu chưa có file (bảng phí, catalogue, hồ sơ giáo viên): không hứa gửi ngay trên chat; tư vấn viên gửi qua Zalo khi có SĐT, hoặc mời tham quan.
- Lead (phụ huynh để lại SĐT, đổi SĐT, hẹn tham quan/học thử): gửi vào nhóm Telegram đang dùng và đẩy sang Google Sheet.

## 4. Dữ kiện cốt lõi

- 3 cơ sở tại Hà Nội:
  1. Hệ Quốc tế Chùa Láng: Tầng 1+2 Sảnh A1 tòa Hongkong Tower, 185 Huỳnh Thúc Kháng, phường Láng, Hà Nội
  2. Hệ Quốc tế Mỹ Đình: Tầng 3 FLC Complex, 36 Phạm Hùng, phường Từ Liêm, Hà Nội
  3. Hệ Song ngữ Kim Mã: 23 ngõ 294 Kim Mã, phường Ngọc Hà, Hà Nội
- Hệ Quốc tế: giáo viên nước ngoài đồng hành cả ngày 8h30–17h00. Hệ Song ngữ: 1 giáo viên nước ngoài tại cơ sở, lớp 0–3 tuổi ~1–1,5 giờ/ngày, lớp 3–6 tuổi ~2–2,5 giờ/ngày.
- Giờ đón chuẩn 17h30.
- Khai giảng chính thức 05/09 hằng năm; nhận hồ sơ và nhập học quanh năm.
- Tặng 1 tuần học thử hoàn toàn miễn phí.
- Cam kết không tăng học phí trong suốt thời gian con theo học.
- Đại sứ Casa: giới thiệu thành công 1 gia đình học tại Chùa Láng hoặc Mỹ Đình → voucher 3.000.000đ.
- Bảo lưu: báo trước 30 ngày; không áp dụng tháng Tết và tháng hè; đã đóng hết học phí thì phí bảo lưu 3.000.000đ, trừ lại khi con quay lại; còn dư học phí thì không cần đóng.
- Nghỉ giữa chừng (báo trước 30 ngày): hoàn 60% (đóng theo quý), 70% (6 tháng), 80% (12 tháng) phần học phí cơ bản còn lại.
- Nghỉ ốm từ 30 ngày, có giấy xác nhận y tế → hoàn 70% học phí tương ứng.
- Tỷ lệ cô – trò: lớp 0–3 tuổi 4 cô / 23–25 bé; lớp 3–6 tuổi 3 cô / 25–27 bé.
- Camera: không xem trực tiếp trên điện thoại; xem tại văn phòng theo quy trình; cập nhật hằng ngày qua LittleLives.

## 5. 7 nguyên tắc tư vấn (từ kịch bản)

1. Hỏi độ tuổi con + khu vực trước khi nói học phí (không hỏi thẳng ngân sách).
2. Kể giá trị trước, con số sau: giáo viên nước ngoài toàn thời gian (hệ Quốc tế), Cambridge Early Years kết hợp Montessori, cam kết không tăng học phí.
3. Tổng chi phí thực tế do tư vấn viên tính và gửi, không tính trên chat.
4. Dùng "học thử 1 tuần miễn phí" làm bước trung gian với khách còn phân vân.
5. CARE khi chê đắt/so sánh trường khác: Connect → Acknowledge → Resolve → Evaluate.
6. Luôn kết thúc bằng một bước tiếp theo cụ thể (xin SĐT, hẹn tham quan, hẹn học thử).
7. Điều hướng xin SĐT để tư vấn qua Zalo hoặc gọi điện.
