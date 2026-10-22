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

## 2c. Phản hồi của trường, đợt 4 (nguyên văn)

1. Ảnh thực đơn như ảnh (kèm ảnh "Thực đơn mẫu 1 tuần cho bé", Thứ 2–6; lưu thành `static/thuc-don-mau.jpg`)
2. Kim mã có theo Cambridge nhưng theo 1 môn là Tiếng Anh thôi, còn hệ quốc tế theo full chương trình 3 môn tiếng anh, toán, lets explore
3. Điều kiện chính xác của "đã tư vấn tương đối đủ":
   1. Có đủ thông tin độ tuổi bé, cơ sở PH quan tâm
   2. Cung cấp được thông tin về trường, cơ sở
   3. Cung cấp được thông tin về chương trình học, chương trình ngoại khóa
   4. Cung cấp được thông tin về thực đơn, chế độ dinh dưỡng
   5. Cung cấp chương trình tặng 1 tuần học thử miễn phí
   6. Cung cấp được thông tin về cơ sở vật chất, không gian lớp học, mời phụ huynh đặt lịch tham quan

## 2d. Phản hồi của trường, đợt 5 (nguyên văn)

2. Hỏi trường hai ca tin nhắc lại:
   1. Chưa biết tuổi bé:
“Dạ em chào Ba/Mẹ ạ. Em xin phép nhắn lại để tiếp tục hỗ trợ Ba/Mẹ tìm hiểu về Casa. Ba/Mẹ cho em xin độ tuổi hiện tại của bé, để em có thể gửi đúng thông tin về chương trình và lớp học phù hợp với con ạ. Nếu Ba/Mẹ cần thêm thông tin nào khác, em cũng luôn sẵn sàng hỗ trợ.”
   2. Đã biết tuổi bé, chưa có SĐT:
“Dạ em chào Ba/Mẹ ạ. Không biết Ba/Mẹ còn cần em hỗ trợ thêm thông tin nào về chương trình, học phí hay lớp phù hợp với bé không ạ? Nếu thuận tiện, Ba/Mẹ có thể để lại SĐT/Zalo để Casa tư vấn kỹ hơn cho mình nhé.”
   3. Đã tư vấn tương đối đủ nhưng PH dừng trao đổi:
“Dạ em chào Ba/Mẹ ạ. Không biết Ba/Mẹ còn điều gì đang băn khoăn hay cần em tư vấn thêm không ạ? Nếu cần, Casa có thể hỗ trợ Ba/Mẹ tìm hiểu kỹ hơn về chương trình học hoặc sắp xếp một buổi tham quan để gia đình trực tiếp cảm nhận môi trường học của con.”

3. Câu mới cần trường trả lời: Các bạn sẽ tiếp tục học theo phương pháp Montessori trong đó các bạn sẽ phát triển đúng theo 5 lĩnh vực theo phương pháp bao gồm toán, tiếng việt...

Mục D:
1. Diện tích lớp ở Kim Mã: - Cơ sở Kim Mã không gian biệt thự sân vườn xanh mát, mỗi tầng là 1 lớp học rộng 80m² rất thoáng cho bé
2. Toán và khám phá ở Kim Mã: Các bạn sẽ tiếp tục học theo phương pháp Montessori trong đó các bạn sẽ phát triển đúng theo 5 lĩnh vực theo phương pháp bao gồm toán, tiếng việt... thực hành cuộc sống, giác quan.... ngoài ra có các chương trình ngọa khóa phong phú
3. Đóng học phí theo tháng: học phí có cho đóng theo tháng không -> không, tất cả đều thu theo quý
4. Camera: phụ huynh được xem bất kỳ lúc nào trong giờ hành chính, hay chỉ khi có sự việc cụ thể? trong giờ hành chính
5. "Cư dân tòa nhà" là tòa nào: Hongkong Tower (cơ sở Chùa Láng) và FLC Complex (cơ sở Mỹ Đình)
6. Dữ kiện giữ từ dữ liệu cũ (Bảo lưu tối thiểu 1 tháng, tối đa 6 tháng. Đóng phí trong 5 ngày làm việc đầu quý, quá hạn có phí nộp muộn. Báo nghỉ trước 7:00 sáng (qua LittleLives hoặc email) thì tiền ăn ngày nghỉ được trừ vào quý sau. Nhập học giữa tháng thì học phí tháng đầu tính theo số ngày đi học thực tế.) — các điểm này còn đúng không? bổ sung thêm nhập học giữa tháng tiền đầu kỳ như phí phát triển trường, học liệu và hoạt động ngoại khóa sẽ thu tròn theo tháng bé nhập học tới hết tháng 6 của năm học. Nhà trường sẽ thu tròn năm/khoản vào tháng 7 hàng năm
7. Số năm hoạt động: Hơn 10 năm

## 2e. Phản hồi của trường, đợt 6 (nguyên văn)

* học phí thu theo quý, 6 tháng hoặc 12 tháng
* 5 lĩnh vực Montessori: ngôn ngữ, toán, thực hành cuộc sống, giác quan, văn hoá

## 2f. Quyết định của người vận hành, 2026-10-22 (lời mời học thử/tham quan)

Yêu cầu (nguyên văn ý): câu "Ba/Mẹ cho bé học thử 1 tuần miễn phí để cảm nhận trực tiếp nhé, tuần này hay tuần sau ạ?" sửa thành kiểu "Ba/Mẹ cho bé học thử 1 tuần miễn phí để cảm nhận trực tiếp nhé, không biết Ba/Mẹ có muốn đăng ký luôn không ạ?" — đoạn "tuần này hay tuần sau ạ" cụt ngủn và cảm giác ép buộc; điều chỉnh cả giọng văn. Đã chốt:

- (a) Áp dụng cho CẢ học thử và tham quan.
- (b) Nút lúc mời đổi thành "Đăng ký học thử / Tìm hiểu thêm" và "Đặt lịch tham quan / Tìm hiểu thêm"; chỉ SAU KHI phụ huynh đồng ý mới hỏi thời gian với nút "Tuần này / Tuần sau" hoặc "Buổi sáng / Buổi chiều" như cũ.
- Xưng hô giữ "Ba/Mẹ" (chỉ gọi "mẹ" khi phụ huynh tự xưng).

## 3. Cách bot áp dụng

- Nhận bé từ 15 tháng, đã đi vững.
- Học phí: không nêu con số, không gửi bảng phí trên chat. Hỏi tuổi bé + cơ sở, kể giá trị trước, rồi xin SĐT/Zalo để tư vấn viên tư vấn/gửi bảng phí. Phụ huynh không cho số mà vẫn muốn biết → chuyển nhân viên trả lời trực tiếp (`[ESCALATE]`).
- Chuyển tư vấn viên (`[ESCALATE]`, người vận hành 2026-10-22, sau khi khách cũ quay lại sau ~6 tháng hỏi "tôi muốn tìm hiểu thông tin về trường" bị chuyển): chỉ khi câu hỏi ngoài lề, hỏi một dữ kiện cụ thể không có trong Q&A (hoặc không chắc dữ kiện đó), hay đã từ chối cho số mà vẫn cần học phí. Câu hỏi chung về trường (giới thiệu, chương trình, cơ sở, giáo viên, lịch học, độ tuổi…) luôn tự trả lời: giới thiệu ngắn rồi hỏi tuổi bé/cơ sở còn thiếu, kể cả khách cũ lâu ngày quay lại.
- Kỳ đóng học phí (mục 2e; 2d, D3): học phí thu theo quý, 6 tháng hoặc 12 tháng; không thu theo tháng. Hỏi "đóng theo tháng được không" → không, nêu đủ 3 kỳ đóng. Chính sách hoàn phí (60/70/80%) và ưu đãi đóng theo kỳ dùng đúng 3 kỳ này.
- Khoản đầu kỳ (mục 2d, D6): phí phát triển trường, phí học liệu và hoạt động ngoại khóa thu tròn năm vào tháng 7 hằng năm; bé nhập học giữa năm học thì thu tròn theo tháng, từ tháng bé nhập học tới hết tháng 6 của năm học. Học phí tháng đầu vẫn tính theo số ngày đi học thực tế. Không nêu số tiền.
- Ưu đãi theo kỳ đóng và khuyến mãi: xin SĐT trước; không cho số → chỉ nói "ưu đãi hấp dẫn, tùy từng đợt/chương trình", không nêu %.
- Ưu đãi anh chị em ruột / cư dân tòa nhà: nói là có, xin SĐT; không cho số → hỏi cơ sở rồi nêu đúng chính sách cơ sở đó:
  - Hệ Quốc tế (Mỹ Đình, Chùa Láng): bé thứ 2 giảm 10% tới khi anh/em ra trường; cư dân tòa nhà giảm thêm 5% tới khi ra trường. Cư dân tòa nhà là cư dân tòa Hongkong Tower (cơ sở Chùa Láng) và tòa FLC Complex (cơ sở Mỹ Đình) (mục 2d, D5).
  - Hệ Song ngữ (Kim Mã): bé thứ 2 giảm 5% tới khi anh/em ra trường; không có chính sách cư dân.
- Đồng phục: bắt buộc theo quy định; không nhắc voucher.
- Đón muộn từ 17h30 có khung phí riêng; có gói trông muộn, trông sớm theo tháng. Không nêu số tiền.
- Đón con: cô hỗ trợ dẫn bé xuống sảnh khi phụ huynh có việc gấp.
- Diện tích lớp: Mỹ Đình 80–90 m²; Chùa Láng 90–100 m²; Kim Mã là không gian biệt thự sân vườn xanh mát, mỗi tầng là 1 lớp học rộng 80 m², rất thoáng cho bé (mục 2d, D1). Câu trả lời về diện tích lớp nêu đủ 3 cơ sở.
- Camera (mục 2d, D4): không xem trực tiếp trên điện thoại; phụ huynh đến văn phòng trường xem camera bất kỳ lúc nào trong giờ hành chính, không cần có sự việc cụ thể.
- Số năm (mục 2d, D7): Casa / nền tảng Montessori của trường "hơn 10 năm" (không dùng "gần 10 năm"). Số năm kinh nghiệm của từng giáo viên giữ nguyên.
- Dã ngoại: 6 chuyến/năm.
- Chương trình: 3–6 tuổi học Cambridge Early Years là khung chính, Montessori là phương pháp và giáo cụ bổ trợ; 15 tháng–3 tuổi xây nền tảng qua Montessori, làm quen tiếng Anh với giáo viên nước ngoài.
  - Cambridge theo hệ (mục 2c): hệ Quốc tế (Chùa Láng, Mỹ Đình) học trọn 3 môn English, Mathematics, Let's Explore (khám phá khoa học, thế giới xung quanh); hệ Song ngữ Kim Mã học Cambridge 1 môn English. Không nói Kim Mã học Mathematics hay Let's Explore; câu trả lời chung về chương trình nêu rõ khác biệt này. Tên môn dùng "Let's Explore", không dùng "Understanding the World".
  - Kim Mã (mục 2d, D2): ngoài Cambridge môn English, các con tiếp tục học theo phương pháp Montessori, phát triển theo 5 lĩnh vực của phương pháp; ngoài ra có các chương trình ngoại khóa phong phú.
  - 5 lĩnh vực Montessori (mục 2e): ngôn ngữ, toán, thực hành cuộc sống, giác quan, văn hóa. Câu nào nhắc "5 lĩnh vực" thì nêu đủ 5, không liệt kê dở ("…"), không dùng "tiếng Việt" thay cho "ngôn ngữ", không thêm lĩnh vực khác.
- Bỏ toàn bộ nội dung workshop của cô Phan Thúy (sheet "Workshop" trong kịch bản). Câu trả lời về sự kiện chung của trường (Family Day, workshop, lễ hội…) vẫn giữ — chờ trường xác nhận (docs/dot-3-can-bo-sung.md, mục C6).
- Xe bus: hiện Nhà trường chưa có tuyến xe bus; khi đủ phụ huynh đăng ký, Nhà trường sẽ mở tuyến. Bot mời để lại khu vực nhà + SĐT/Zalo để ghi nhận nhu cầu.
- Khi phụ huynh chê đắt (CARE): không gợi ý hệ/cơ sở khác như phương án rẻ hơn; nêu giá trị khác biệt và mời học thử/tham quan.
- Câu hỏi gợi ý, nút trả lời nhanh: theo mục 2b; nút mời học thử/tham quan theo mục 2f. Mẫu tin nhắc lại: nguyên văn mục 2d. Tin nhắc lại vẫn tắt.
- Chọn mẫu tin nhắc lại (`app/followup.py`), theo thứ tự:
  1. Đã tư vấn tương đối đủ (mục 2c.3) → mẫu 3 (mời tham quan). Điều kiện 1 = bot đã biết tuổi bé **và** cơ sở phụ huynh quan tâm (chỉ biết khu vực nhà thì chưa đủ). Điều kiện 2–6 = câu bot đã gửi có nói tới: trường/cơ sở (địa chỉ), chương trình học, ngoại khóa, thực đơn/dinh dưỡng, học thử 1 tuần miễn phí, cơ sở vật chất/không gian lớp, và lời mời tham quan (`app/coverage.py` dò trên câu bot gửi, lưu ở `topics_covered`).
  2. Chưa biết tuổi bé → mẫu 1 (hỏi tuổi).
  3. Còn lại (đã biết tuổi, chưa có SĐT, chưa tư vấn đủ) → mẫu 2 (xin SĐT/Zalo), kể cả khi phụ huynh đã từ chối để lại số — theo nhãn mẫu của trường (mục 2d).
  Nguyên văn 3 mẫu: mục 2d (thay bản ở mục 2b.c).
- SĐT: nhận cả số thiếu số 0 đầu, viết tách lạ, số nước ngoài.
- Thứ tự hỏi (người vận hành 2026-10-22): chưa biết tuổi bé thì hỏi tuổi trước thời điểm dự kiến nhập học, kể cả ngay sau khi phụ huynh gửi SĐT, vì học phí và chương trình theo tuổi. Không gọi bé là "lứa nhỏ" (nguồn là câu ví dụ "Lứa này…" trong prompt, đã đổi thành "Ở tuổi này…").
- Thực đơn mẫu: gửi thẳng cho phụ huynh ảnh `static/thuc-don-mau.jpg` (trường `images` của cặp Q&A thực đơn chung; JPG chuyển từ ảnh trường gửi để Messenger nhận chắc chắn). Món ví dụ trong câu trả lời lấy đúng từ ảnh (thứ Hai), không thêm món ngoài ảnh; 5 bữa: sáng, nhẹ sáng, trưa, chiều, phụ chiều.
- Không hỏi thẳng ngân sách; có thể hỏi gia đình cân nhắc hệ Quốc tế hay Song ngữ.
- Tài liệu chưa có file (bảng phí, catalogue, hồ sơ giáo viên): không hứa gửi ngay trên chat; tư vấn viên gửi qua Zalo khi có SĐT, hoặc mời tham quan.
- Lead (phụ huynh để lại SĐT, đổi SĐT, hẹn tham quan/học thử): gửi vào nhóm Telegram đang dùng và đẩy sang Google Sheet.
  - Phụ huynh ĐỒNG Ý học thử/tham quan (bấm "Đăng ký học thử"/"Đặt lịch tham quan" hoặc tự nói muốn) là có lead ngay, dù chưa chọn tuần/buổi: lead đến nhóm ngay khi phụ huynh đồng ý, để phụ huynh rời đi giữa chừng vẫn không mất lead. Chưa có SĐT thì bot xin SĐT/Zalo mềm 1 lần, không xin lại. Tư vấn viên liên hệ qua SĐT nếu có; nếu không thì nhắn qua hộp thư Page, trong 24 giờ kể từ tin cuối của phụ huynh (cửa sổ nhắn tin của Messenger). Chỉ hỏi ("học thử thế nào ạ?"), còn cân nhắc hay bấm "Tìm hiểu thêm" thì chưa phải lead.
  - Mỗi chi tiết hẹn mới là một lead: phụ huynh bấm "Đặt lịch tham quan"/"Đăng ký học thử" (đồng ý) rồi chọn buổi/tuần thì nhóm có thể nhận 2 tin cho cùng một lịch — tin đầu để tư vấn viên liên hệ sớm, tin sau thêm buổi/tuần để chốt giờ. Bấm lại cùng buổi/tuần không gửi nữa; đã có buổi/tuần mà bấm lại nút đồng ý thì prompt extract dặn không ghi bản chung chung hơn (giữ lịch cụ thể, không lead thừa).
  - Mỗi phụ huynh một thẻ Telegram và một hàng Sheet (người vận hành, 2026-10-22, sau khi một phụ huynh ra 3 thẻ đầy đủ trong 2 phút): lead đầu là thẻ đầy đủ; SĐT/lịch hẹn đổi sau đó là tin ngắn trả lời vào thẻ, chỉ nêu phần đổi ("Hẹn: tham quan buổi sáng → tham quan sáng mai"); Sheet cập nhật hàng của phụ huynh, giữ "Lần đầu liên hệ" (`docs/google-sheet-leads.md`). Không gộp theo thời gian.
  - Đánh đổi: hồ sơ đã có `visit_request` thì tin nhắc lại tự động không gửi (`_is_due` trong `app/followup.py`), kể cả khi chưa có SĐT — phụ huynh đã đồng ý mà chưa để số thì chỉ còn tư vấn viên nhắn qua hộp thư Page trong 24 giờ đó.

- Giọng văn (người vận hành chốt 2026-10-22, sau khi xem hội thoại thật): nhắn như tư vấn viên thật, không như bot.
  - Xưng "em", gọi "Ba/Mẹ"; chỉ gọi "anh/chị/mẹ bé…" khi phụ huynh tự xưng như vậy. Không đoán giới tính từ tên Facebook (tên Facebook không đưa vào prompt chat).
  - Mỗi tin 1–3 câu ngắn: trả lời đúng ý hỏi, tối đa 1 điểm nổi bật, rồi 1 bước tiếp theo (nguyên tắc 6).
    Ngoại lệ: lúc vừa chốt lịch hẹn chỉ xác nhận ngắn, không cần bước tiếp theo. Câu admin trả lời qua Telegram được bot viết lại cùng giọng nhưng giữ đủ mọi dữ kiện admin đưa (ngày, giờ, con số, tên), có thể dài hơn 3 câu.
  - Không nhắc lại thông tin phụ huynh đã đưa (SĐT, tuổi, cơ sở, buổi hẹn), không đọc lại số điện thoại; chỉ xác nhận ngắn 1 lần lúc vừa chốt lịch hẹn.
  - Thông tin đã biết vẫn dùng để tư vấn đúng hệ/cơ sở/nhóm tuổi (vd phụ huynh Kim Mã hỏi giáo viên nước ngoài thì trả lời theo hệ Song ngữ), chỉ không kể lại.
  - Mở đầu đa dạng, không khuôn "em ghi nhận…", emoji chỉ thỉnh thoảng.
  - Mời học thử/tham quan (mục 2f): câu hỏi ý mềm ("không biết Ba/Mẹ có muốn … không ạ?", "nếu tiện…") kèm nút mời (`trial_invite`: Đăng ký học thử / Tìm hiểu thêm; `visit_invite`: Đặt lịch tham quan / Tìm hiểu thêm), không bắt chọn tuần/buổi ngay. Nút mời thay cho nút thời gian ở lần mời đầu; phụ huynh đồng ý (bấm nút hoặc nói muốn) thì mới hỏi tuần (`trial_week`: Tuần này / Tuần sau) hay buổi (`visit_time`: Buổi sáng / Buổi chiều). "Tìm hiểu thêm" → hỏi Ba/Mẹ muốn biết thêm điều gì, chưa mời lại. Xin SĐT cũng mềm ("Nếu tiện, Ba/Mẹ để lại SĐT/Zalo…"). Câu kết trọn ý, có từ đệm tự nhiên, không cụt, không thúc ép.
  - Không lặp lại câu vừa gửi, không chép câu ví dụ trong prompt (thử model thật 2026-10-22): phụ huynh đổi/chốt cụ thể hơn (vd "sáng mai được không") thì trả lời thẳng ý mới, không gửi lại câu xác nhận. Bot không tự hứa lịch trống ("sáng mai được ạ", "tuần này sắp xếp được ạ", "còn chỗ"): nhận yêu cầu, tư vấn viên gọi xác nhận giờ. Lượt phụ huynh vừa đồng ý chỉ hỏi tuần/buổi, chưa xin SĐT; xin SĐT mềm 1 lần ở lượt sau, tin trước vừa xin thì không xin lại ngay (thử DeepSeek thật 2026-10-22).

## 4. Dữ kiện cốt lõi

- 3 cơ sở tại Hà Nội:
  1. Hệ Quốc tế Chùa Láng: Tầng 1+2 Sảnh A1 tòa Hongkong Tower, 185 Huỳnh Thúc Kháng, phường Láng, Hà Nội
  2. Hệ Quốc tế Mỹ Đình: Tầng 3 FLC Complex, 36 Phạm Hùng, phường Từ Liêm, Hà Nội
  3. Hệ Song ngữ Kim Mã: 23 ngõ 294 Kim Mã, phường Ngọc Hà, Hà Nội
- Casa hoạt động hơn 10 năm.
- Cơ sở Kim Mã: không gian biệt thự sân vườn xanh mát, mỗi tầng là 1 lớp học rộng 80 m².
- Hệ Quốc tế: giáo viên nước ngoài đồng hành cả ngày 8h30–17h00. Hệ Song ngữ: 1 giáo viên nước ngoài tại cơ sở, lớp 0–3 tuổi ~1–1,5 giờ/ngày, lớp 3–6 tuổi ~2–2,5 giờ/ngày.
- Kim Mã: Cambridge môn English + phương pháp Montessori (5 lĩnh vực: ngôn ngữ, toán, thực hành cuộc sống, giác quan, văn hóa) + ngoại khóa phong phú.
- Giờ đón chuẩn 17h30.
- Khai giảng chính thức 05/09 hằng năm; nhận hồ sơ và nhập học quanh năm.
- Tặng 1 tuần học thử hoàn toàn miễn phí.
- Cam kết không tăng học phí trong suốt thời gian con theo học.
- Học phí thu theo quý, 6 tháng hoặc 12 tháng; không thu theo tháng. Đóng trong 5 ngày làm việc đầu quý, quá hạn có phí nộp muộn.
- Nhập học giữa tháng: học phí tháng đầu tính theo số ngày đi học thực tế. Khoản đầu kỳ (phí phát triển trường, phí học liệu và hoạt động ngoại khóa): thu tròn năm vào tháng 7 hằng năm; nhập học giữa năm học thì thu tròn theo tháng, từ tháng bé nhập học tới hết tháng 6.
- Báo nghỉ trước 7:00 sáng (LittleLives hoặc email) → tiền ăn ngày nghỉ trừ vào quý sau.
- Ưu đãi cư dân tòa nhà (hệ Quốc tế): cư dân tòa Hongkong Tower (Chùa Láng) và FLC Complex (Mỹ Đình); Kim Mã không có.
- Đại sứ Casa: giới thiệu thành công 1 gia đình học tại Chùa Láng hoặc Mỹ Đình → voucher 3.000.000đ.
- Bảo lưu: báo trước 30 ngày; tối thiểu 1 tháng, tối đa 6 tháng; không áp dụng tháng Tết và tháng hè; đã đóng hết học phí thì phí bảo lưu 3.000.000đ, trừ lại khi con quay lại; còn dư học phí thì không cần đóng.
- Nghỉ giữa chừng (báo trước 30 ngày): hoàn 60% (đóng theo quý), 70% (6 tháng), 80% (12 tháng) phần học phí cơ bản còn lại.
- Nghỉ ốm từ 30 ngày, có giấy xác nhận y tế → hoàn 70% học phí tương ứng.
- Tỷ lệ cô – trò: lớp 0–3 tuổi 4 cô / 23–25 bé; lớp 3–6 tuổi 3 cô / 25–27 bé.
- Camera: không xem trực tiếp trên điện thoại; phụ huynh xem tại văn phòng trường bất kỳ lúc nào trong giờ hành chính; cập nhật hằng ngày qua LittleLives.

## 5. 7 nguyên tắc tư vấn (từ kịch bản)

1. Hỏi độ tuổi con + khu vực trước khi nói học phí (không hỏi thẳng ngân sách).
2. Kể giá trị trước, con số sau: giáo viên nước ngoài toàn thời gian (hệ Quốc tế), Cambridge Early Years kết hợp Montessori, cam kết không tăng học phí.
3. Tổng chi phí thực tế do tư vấn viên tính và gửi, không tính trên chat.
4. Dùng "học thử 1 tuần miễn phí" làm bước trung gian với khách còn phân vân.
5. CARE khi chê đắt/so sánh trường khác: Connect → Acknowledge → Resolve → Evaluate.
6. Luôn kết thúc bằng một bước tiếp theo cụ thể (xin SĐT, hẹn tham quan, hẹn học thử), trừ lúc vừa chốt lịch hẹn (chỉ xác nhận ngắn; chưa có SĐT và phụ huynh chưa từ chối để số thì xin SĐT/Zalo mềm 1 lần để tư vấn viên gọi xác nhận giờ, đã xin rồi thì không xin lại). Từ 2026-10-22 (mục 2f): mời mềm trước, phụ huynh đồng ý rồi mới hỏi thời gian.
7. Điều hướng xin SĐT để tư vấn qua Zalo hoặc gọi điện.
