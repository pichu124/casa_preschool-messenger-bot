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

## 2g. Phản hồi của trường, đợt 7 (sau khi thử bot; câu mẫu nguyên văn)

1. Câu chuyển tư vấn viên phải có hotline. Văn mẫu: "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, nhân viên phụ trách sẽ hỗ trợ và phản hồi trực tiếp tại đây sớm nhất ạ. Nếu Ba/Mẹ cần được tư vấn ngay, mình có thể liên hệ Hotline 0989 059 838 để Casa hỗ trợ nhanh hơn nhé ạ." Bot xin số nhiều lần làm phụ huynh bực; hotline thay vai trò đó.
2. Phụ huynh nhất quyết không để số, muốn nhận thông tin qua chat và tỏ ra khó chịu: không im, không vòng vo, chuyển tư vấn viên với câu: "Dạ em xin lỗi Ba/Mẹ vì sự bất tiện này ạ. Em đã chuyển thông tin sang tư vấn viên phụ trách để hỗ trợ mình ngay tại đây. Bên em sẽ gửi thông tin đầy đủ để Ba/Mẹ tiện xem và trao đổi ạ."
3. Phụ huynh muốn tham quan thứ 7, Chủ nhật: trường làm việc thứ 2–6, cuối tuần phải sắp xếp riêng một cô tới tiếp. Khéo léo mời qua giờ hành chính thứ 2–6; không sắp xếp được thì báo tư vấn viên sắp xếp và liên hệ xác nhận (xin SĐT nếu chưa có). Không hứa "được ạ" cho cuối tuần (bot từng trả lời "Em báo tư vấn viên xếp mẹ ghé thứ 7 ạ…").
4. Nhóm 3–6 tuổi: câu chung, không tự kể khác biệt giữa các cơ sở khi phụ huynh chưa nói cơ sở. Văn mẫu: "Dạ nhóm 3–6 tuổi tại Casa học Cambridge Early Years kết hợp Montessori. Nội dung và thời lượng Cambridge sẽ được triển khai phù hợp theo từng chương trình/cơ sở. Ba/Mẹ đang quan tâm cơ sở nào để em tư vấn chính xác cho mình nhé ạ."
5. Giáo viên nước ngoài được đào tạo cả chương trình Cambridge, không chỉ Montessori.
6. Thời lượng Cambridge (hệ Quốc tế): "Dạ tại Casa, các bé 3–6 tuổi học Cambridge Early Years hằng ngày từ thứ Hai đến thứ Sáu, với tổng thời lượng khoảng 1,5–2 giờ/ngày. Buổi sáng các con có English khoảng 30–40 phút, sau đó tiếp tục hoạt động theo nhóm nhỏ, hoặc cá nhân. Buổi chiều, từ khoảng 14:45–16:00, các con học luân phiên Mathematics hoặc Let's Explore theo thời khóa biểu. Như vậy Cambridge không chỉ là một "tiết học riêng", mà được bố trí đều trong ngày và kết nối với các hoạt động Montessori, trải nghiệm và học nhóm nhỏ của con."
7. Không chào lại giữa cuộc trò chuyện ("Cảm ơn Ba/Mẹ đã quan tâm tới Casa dei Bambini…"), không hỏi lại thông tin đã có (đã nói Mỹ Đình vẫn hỏi cơ sở; đã để SĐT vẫn xin số).

## 3. Cách bot áp dụng

- Dữ kiện chỉ ở Q&A (người vận hành 2026-10-23, `docs/kiem-ke-du-kien.md`): địa chỉ, giờ, giáo viên, chương trình theo tuổi, ưu đãi… nằm ở `data/qa_database.json`; trường sửa thông tin thì sửa Q&A. THÔNG TIN CỐT LÕI của prompt chỉ giữ tóm tắt không được sai (3 cơ sở và hệ; nhận bé 15 tháng, đã đi vững, đến 6 tuổi; không nêu con số học phí; 1 tuần học thử miễn phí). Luật hành xử ở prompt; câu cố định nguyên văn (mẫu nhắc lại, câu chuyển tư vấn viên, nút) ở code. `tests/test_prompt.py` kiểm phần còn trong prompt khớp Q&A.
- Nhận bé từ 15 tháng, đã đi vững. Nhóm nhỏ nhất gọi là "15 tháng–3 tuổi", không dùng "18–36 tháng" (sót từ tuổi nhận cũ, sửa 2026-10-23).
- Học phí (người vận hành 2026-10-23, thay quyết định cũ "không gửi bảng phí trên chat" theo mục 2.2): không viết con số. Hỏi tuổi bé + cơ sở, kể giá trị trước; biết đủ thì bot gửi ảnh học phí của trường (mục "Ảnh gửi phụ huynh" bên dưới) và nói ngắn "em gửi Ba/Mẹ chính sách học phí tại cơ sở … để gia đình tham khảo". Chưa có ảnh (danh mục rỗng, tắt đồng bộ) thì như cũ: xin SĐT/Zalo để tư vấn viên gửi bảng phí. Phụ huynh không để số khi được xin hoặc từ chối cho số mà vẫn đòi mức học phí: KHÔNG chuyển tư vấn viên nữa; đã biết cơ sở thì gửi ảnh học phí, kể cả khi chưa biết tuổi bé; chưa biết cơ sở thì hỏi cơ sở.
- Chuyển tư vấn viên (`[ESCALATE]`, người vận hành 2026-10-22, sau khi khách cũ quay lại sau ~6 tháng hỏi "tôi muốn tìm hiểu thông tin về trường" bị chuyển): chỉ khi câu hỏi ngoài lề, hỏi một dữ kiện cụ thể không có trong Q&A (hoặc không chắc dữ kiện đó), (ca "không để số mà vẫn đòi học phí" bỏ từ 2026-10-23, xem dòng Học phí). Câu hỏi chung về trường (tìm hiểu trường, chương trình, cơ sở, giáo viên, độ tuổi…) luôn tự trả lời: giới thiệu ngắn rồi hỏi tuổi bé/cơ sở còn thiếu, kể cả khách cũ lâu ngày quay lại. Luật này không áp cho dữ kiện cụ thể: lịch học/thời gian biểu trong ngày không có trong Q&A nên vẫn `[ESCALATE]`, không bịa giờ (review 2026-10-22). Ngoại lệ (review 2026-10-23): lượt hệ thống chắc chắn gửi ảnh thời khoá biểu (dòng `[HỆ THỐNG] Sau câu trả lời này … thời khoá biểu`, vd tin có "lịch học", mục "Ảnh gửi phụ huynh") thì câu hỏi lịch học trong tuần/giờ trong ngày được trả lời chung và báo em gửi thời khoá biểu, không `[ESCALATE]`, vẫn không tự nêu giờ ngoài Q&A (lịch hè, Tết, học bù không có trong Q&A vẫn `[ESCALATE]`); điều kiện nằm trong chính dòng đó (`IMAGE_ANSWERS` trong `app/ai_engine.py`), không trong SYSTEM_PROMPT. Không có ảnh, ảnh chỉ gửi nếu phụ huynh hỏi chương trình (dòng "Nếu phụ huynh hỏi …"), hoặc ảnh còn chờ cơ sở/tuổi bé (người vận hành 2026-10-24: khi đó hỏi cái còn thiếu), thì câu hỏi giờ cụ thể vẫn `[ESCALATE]` như trên.
- Câu chuyển tư vấn viên (mục 2g.1, `app/escalation.py`): luôn kèm Hotline 0989 059 838 (hằng số `HOTLINE`), không xin SĐT/Zalo. Chưa có SĐT hoặc đã từ chối để số: nguyên văn của trường; đã có SĐT: "…tư vấn viên sẽ liên hệ và trả lời Ba/Mẹ trong thời gian sớm nhất ạ." rồi cùng đoạn hotline.
- Phụ huynh khó chịu (mục 2g.2): model trích xuất trả `"upset": true` chỉ khi đủ cả ba: phụ huynh không muốn để số, muốn nhận thông tin qua chat, và tỏ ra khó chịu về việc đó. Không tính (review 2026-10-23, trước đó định nghĩa có "phàn nàn" nên "học phí đắt quá, trường gần nhà rẻ hơn" nhận câu xin lỗi thay vì được tư vấn kiểu CARE): chê đắt, so sánh trường khác, lo lắng về bé (khóc, ăn uống, an toàn), hỏi lại một câu, từ chối để số nhưng lịch sự. `scripts/eval_chat.py upset` chấm định nghĩa này với model thật (không câu âm nào bị bật cờ, bắt được ≥ 2/3 câu dương). Khi cờ bật, bot chuyển tư vấn viên (thẻ Telegram như mọi lần chuyển) và gửi nguyên văn câu xin lỗi của trường thay cho câu của model, kể cả khi model chat tự trả lời. Cờ này không lưu vào hồ sơ. Tin cuối của bot đã là câu chuyển tư vấn viên (câu xin lỗi, câu chuyển thường, kể cả bản trước khi có hotline) mà phụ huynh lại bực: không gửi lại câu xin lỗi, không tạo thẻ Telegram mới, chỉ gửi câu ngắn (lead viết, 2026-10-23): "Dạ tư vấn viên đang xem và sẽ phản hồi Ba/Mẹ ngay tại đây ạ. Nếu cần gấp, Ba/Mẹ gọi Hotline 0989 059 838 giúp em nhé ạ."
- Tham quan/học thử cuối tuần (mục 2g.3): trường làm việc thứ 2–6. Không hứa thứ 7/Chủ nhật; khéo mời qua giờ hành chính thứ 2–6; phụ huynh không sắp xếp được thì báo tư vấn viên sắp xếp và liên hệ xác nhận, chưa có SĐT thì xin SĐT/Zalo mềm 1 lần.
- Không chào lại, không hỏi lại (mục 2g.7): lời chào tin đầu chỉ có khi chưa có lịch sử (hoặc khách cũ quay lại sau ≥ 24 giờ); thông tin đã biết (cơ sở, SĐT) đi vào [THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT] và "Còn thiếu" không còn nhắc nó. Hai tin liền nhau của một phụ huynh được trả lời lần lượt (trước đây trả lời cùng lúc nên cả hai được chào như tin đầu). Hồ sơ và lịch sử mất khi Render khởi động lại mà chưa đặt `CUSTOMERS_GITHUB_REPO`: khi đó phụ huynh đang nói dở cũng thành khách mới.
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
  - Cambridge theo hệ (mục 2c): hệ Quốc tế (Chùa Láng, Mỹ Đình) học trọn 3 môn English, Mathematics, Let's Explore (khám phá khoa học, thế giới xung quanh); hệ Song ngữ Kim Mã học Cambridge 1 môn English. Không nói Kim Mã học Mathematics hay Let's Explore. Tên môn dùng "Let's Explore", không dùng "Understanding the World".
  - Khi chưa biết cơ sở (mục 2g.4, thay quy tắc cũ "câu trả lời chung nêu rõ khác biệt"): câu chung "nhóm 3–6 tuổi tại Casa học Cambridge Early Years kết hợp Montessori; nội dung và thời lượng Cambridge triển khai phù hợp theo từng chương trình/cơ sở" rồi hỏi cơ sở. Chi tiết theo hệ chỉ nêu khi phụ huynh đã cho biết cơ sở hoặc hỏi đúng hệ/cơ sở đó (hay hỏi so sánh các hệ): Q&A chương trình chung đặt chi tiết sau dấu "Chi tiết theo hệ (chỉ nêu khi …)"; prompt không còn liệt kê môn theo hệ.
  - Thời lượng Cambridge (mục 2g.6): hệ Quốc tế dùng nguyên văn của trường (bỏ "Dạ tại Casa," để ghi rõ áp cho hệ Quốc tế). Kim Mã học môn English khoảng 40 phút; ngoài giờ Cambridge, các con còn có các giờ học khác bằng tiếng Anh với giáo viên nước ngoài (trường xác nhận 2026-10-24).
  - Giáo viên nước ngoài (mục 2g.5): được trường đào tạo cả chương trình Cambridge Early Years lẫn phương pháp Montessori.
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
- Không nhắc lại phụ huynh đã nhận câu xin lỗi (mục 2g.2) trong 24 giờ tính tới tin cuối của họ, kể cả khi họ nhắn tiếp và bot trả lời bình thường (review 2026-10-23: phụ huynh bực vì bị đòi số, nhắn "ừ nhanh nhé", 3 giờ sau nhận mẫu 2 xin SĐT). Không lưu cờ vào hồ sơ: dò câu xin lỗi trong lịch sử. Luật chọn mẫu ở trên giữ nguyên.
- SĐT: nhận cả số thiếu số 0 đầu, viết tách lạ, số nước ngoài.
- Thứ tự hỏi (người vận hành 2026-10-22): chưa biết tuổi bé thì hỏi tuổi trước thời điểm dự kiến nhập học, kể cả ngay sau khi phụ huynh gửi SĐT, vì học phí và chương trình theo tuổi. Không gọi bé là "lứa nhỏ" (nguồn là câu ví dụ "Lứa này…" trong prompt, đã đổi thành "Ở tuổi này…").
- Thực đơn mẫu (khi Drive chưa có ảnh thực đơn, xem "Ảnh gửi phụ huynh"): gửi thẳng cho phụ huynh ảnh `static/thuc-don-mau.jpg` (trường `images` của cặp Q&A thực đơn chung; JPG chuyển từ ảnh trường gửi để Messenger nhận chắc chắn). Món ví dụ trong câu trả lời lấy đúng từ ảnh (thứ Hai), không thêm món ngoài ảnh; 5 bữa: sáng, nhẹ sáng, trưa, chiều, phụ chiều.
- Không hỏi thẳng ngân sách; có thể hỏi gia đình cân nhắc hệ Quốc tế hay Song ngữ.
- Tài liệu chưa có file (catalogue, hồ sơ giáo viên; bảng phí khi chưa có ảnh học phí): không hứa gửi ngay trên chat; tư vấn viên gửi qua Zalo khi có SĐT, hoặc mời tham quan.
- Lead (phụ huynh để lại SĐT, đổi SĐT, hẹn tham quan/học thử): gửi vào nhóm Telegram đang dùng và đẩy sang Google Sheet.
  - Phụ huynh ĐỒNG Ý học thử/tham quan (bấm "Đăng ký học thử"/"Đặt lịch tham quan" hoặc tự nói muốn) là có lead ngay, dù chưa chọn tuần/buổi: lead đến nhóm ngay khi phụ huynh đồng ý, để phụ huynh rời đi giữa chừng vẫn không mất lead. Chưa có SĐT thì bot xin SĐT/Zalo mềm 1 lần, không xin lại. Tư vấn viên liên hệ qua SĐT nếu có; nếu không thì nhắn qua hộp thư Page, trong 24 giờ kể từ tin cuối của phụ huynh (cửa sổ nhắn tin của Messenger). Chỉ hỏi ("học thử thế nào ạ?"), còn cân nhắc hay bấm "Tìm hiểu thêm" thì chưa phải lead.
  - Mỗi chi tiết hẹn mới là một lead: phụ huynh bấm "Đặt lịch tham quan"/"Đăng ký học thử" (đồng ý) rồi chọn buổi/tuần thì nhóm có thể nhận 2 tin cho cùng một lịch — tin đầu để tư vấn viên liên hệ sớm, tin sau thêm buổi/tuần để chốt giờ. Bấm lại cùng buổi/tuần không gửi nữa; đã có buổi/tuần mà bấm lại nút đồng ý thì prompt extract dặn không ghi bản chung chung hơn (giữ lịch cụ thể, không lead thừa).
  - Mỗi phụ huynh một thẻ Telegram và một hàng Sheet (người vận hành, 2026-10-22, sau khi một phụ huynh ra 3 thẻ đầy đủ trong 2 phút): lead đầu là thẻ đầy đủ; SĐT/lịch hẹn đổi sau đó là tin ngắn trả lời vào thẻ, chỉ nêu phần đổi ("Hẹn: tham quan buổi sáng → tham quan sáng mai"); Sheet cập nhật hàng của phụ huynh, giữ "Lần đầu liên hệ" (`docs/google-sheet-leads.md`). Không gộp theo thời gian.
  - Phụ huynh đã là lead (có SĐT hoặc hẹn) nói thêm hoặc đổi thông tin trên thẻ (tên/tuổi bé, cơ sở/hệ, khu vực, dự kiến nhập học, mối quan tâm) thì cập nhật luôn hàng Sheet ("Sự kiện": Cập nhật thông tin) và gửi tin ngắn trả lời vào thẻ, vd "🔄 Lan Thử: Dự kiến nhập học: tháng 12" (người vận hành, 2026-10-23, sau khi "Tầm tháng 12" không lên Sheet); chưa là lead thì không gửi gì.
  - Đánh đổi: hồ sơ đã có `visit_request` thì tin nhắc lại tự động không gửi (`_is_due` trong `app/followup.py`), kể cả khi chưa có SĐT — phụ huynh đã đồng ý mà chưa để số thì chỉ còn tư vấn viên nhắn qua hộp thư Page trong 24 giờ đó.
- Thống kê chủ đề phụ huynh hỏi (người vận hành, 2026-10-23, để tối ưu content và quảng cáo): model trích xuất gắn mỗi tin vào danh sách cố định `app/topics.py` (tin chỉ là thông tin hồ sơ hoặc chào hỏi: không có chủ đề; tin chuyển tư vấn viên: ít nhất "Khác"). Chủ đề không lưu vào hồ sơ phụ huynh. Dashboard đếm 7 ngày; tab "Chủ đề" của Sheet (bật bằng `TOPICS_SHEET_ENABLED`) mỗi tin một dòng, có quảng cáo nguồn, câu hỏi gốc đã che SĐT, không có tên Facebook.
- Ảnh từ Google Drive (người vận hành, 2026-10-23): ảnh học phí, thực đơn, thời khoá biểu, cơ sở vật chất lấy từ thư mục Drive "Ảnh cho Chatbot" của trường, bot tự đồng bộ (30 phút một lần, hoặc ngay khi admin gõ `/capnhatanh` trong nhóm Telegram); trường đổi ảnh trên Drive, không cần sửa code. Quy ước: mỗi tháng một thư mục `HỌC PHÍ THÁNG N` trong từng hệ (chưa có tháng hiện tại thì dùng tháng gần nhất trước đó), tên ảnh thời khoá biểu ghi nhóm tuổi, cơ sở mới là thư mục `CƠ SỞ <TÊN>` (README mục 12).
- Ảnh gửi phụ huynh (người vận hành 2026-10-23; mọi trường hợp và bộ kiểm của từng trường hợp: `docs/ma-tran-gui-anh.md`; `_plan_images` trong `app/main.py`). Ảnh đi sau câu trả lời, nút trả lời nhanh nằm trên tin cuối; tối đa 5 ảnh một lượt (nhóm ảnh không vừa thì chờ lần hỏi sau); lượt chuyển tư vấn viên hoặc phụ huynh khó chịu không gửi ảnh; tắt đồng bộ (`MEDIA_SYNC_ENABLED`) hoặc danh mục rỗng thì không gửi ảnh Drive nào. Gửi lỗi (Graph API) thì log WARNING, lượt vẫn xong, ảnh chưa tính là đã gửi; từ 2026-10-24 (hội thoại thật: bot báo "em gửi ngay bên dưới" mà ảnh không tới) ảnh Drive gửi lỗi còn báo nhóm Telegram admin tối đa 1 lần mỗi giờ (ảnh nào, mã HTTP và thông điệp lỗi Graph, gợi ý kiểm `PUBLIC_BASE_URL` và mở thử URL ảnh; không có token, không có tin của phụ huynh), và khi mọi ảnh Drive định gửi của lượt đều lỗi (đó là ảnh model đã được dặn báo gửi: ảnh chắc chắn, ảnh tuỳ chủ đề khớp chủ đề hoặc được gắn token) thì bot gửi thêm "Dạ ảnh em gửi đang bị lỗi chưa tới được, Ba/Mẹ nhắn lại em sau ít phút để em gửi lại nhé ạ." (`IMAGES_FAILED_MESSAGE` trong `app/main.py`). Ảnh gửi lỗi không tự thử lại (thử thật trên Render 2026-10-24: `PUBLIC_BASE_URL` sai, ảnh cơ sở vật chất lỗi, cờ `facilities_asked` còn chờ nên lượt sau phụ huynh chỉ bấm "Dưới 2 tuổi" mà bot lại gửi, lại lỗi, lại xin lỗi): ảnh đã thử gửi trong lượt, tới hay lỗi, không để cờ chờ của loại đó, nên câu xin lỗi chỉ đi ở lượt lỗi, lượt sau không gửi lại, không xin lỗi lại; phụ huynh hỏi lại (chủ đề, chữ, token như thường) thì bot gửi lại. Log INFO mỗi lượt các ảnh định gửi; log lỗi Graph không có access token. Ảnh đã gửi lưu trong hồ sơ (`media_sent`), lịch sử ghi chú ngắn "[đã gửi ảnh …]" để model biết. Câu "em gửi Ba/Mẹ …" do model nói theo dòng `[HỆ THỐNG]` cuối khối nhắc nhở; dòng này tính trước khi biết kết quả trích xuất (hai lời gọi model chạy song song), nên ảnh chỉ gửi nếu tin hỏi đúng chủ đề thì dòng ghi "Nếu phụ huynh hỏi …". Không hứa suông (2026-10-24): ảnh của dòng "Nếu phụ huynh hỏi …" cũng gửi khi model gắn token của loại ảnh đó vào câu trả lời (`[SEND:fee]`, `[SEND:timetable]`, `[SEND:facilities]`, `[SEND:menu]`), như khi phụ huynh hỏi đúng chủ đề. Chính dòng đó dặn (`SEND_TOKEN_RULE` trong `app/ai_engine.py`, không trong SYSTEM_PROMPT): "Chỉ khi câu trả lời báo em gửi ảnh này thì thêm [SEND:<loại>] ở cuối (trước [QUICK:]); hỏi/mời xem ảnh thì không thêm." Code tách token khỏi câu gửi phụ huynh, không lưu vào lịch sử (lịch sử đã có "[đã gửi ảnh …]"). Token của loại ảnh chưa đủ điều kiện (thiếu tuổi bé, cơ sở; học phí mà phụ huynh không hỏi khi chưa biết tuổi) bị bỏ qua: không gửi, không để cờ chờ (phụ huynh không hỏi gì). Review vòng thời khoá biểu v3 (2026-10-24): trước đó code đọc chữ câu trả lời ("em … gửi" kèm từ của loại ảnh) và ba vòng review liền bắt lỗi: câu mời "có muốn em gửi … không ạ?" bị tính là báo gửi, câu ghép "em gửi bảng học phí ạ, Ba/Mẹ có muốn xem ảnh cơ sở vật chất không ạ?" kéo theo 4 ảnh cơ sở vật chất; nay không đoán ý model từ chữ nữa. Dòng `[HỆ THỐNG]` dặn chỉ nói em gửi ảnh có dòng, không nói tư vấn viên sẽ gửi ảnh đó. Cơ sở và tuổi bé lấy từ trích xuất, từ chính tin nhắn (tên cơ sở; tuổi 15 tháng–7 tuổi, để "đóng 12 tháng" không bị đọc là tuổi) rồi từ hồ sơ. Tuổi ghi theo năm sinh ("sinh năm 2022", "sinh tháng 3/2022") tính ra số tháng tới hôm nay giờ Việt Nam, chỉ có năm thì tính như sinh tháng 7 (review 2026-10-24: trước đó không đọc được, bot mỗi lượt dặn hỏi lại tuổi bé); "tuyển sinh 2025", "học sinh năm 2024" không phải năm sinh. Nhiều cơ sở (2026-10-24): tin, trích xuất hay hồ sơ (`interested_campus` có thể ghi nhiều tên, vd "Chùa Láng, Kim Mã") nêu nhiều cơ sở thì bot tính đủ các cơ sở đó; tin xin "2 hệ", "cả hai cơ sở" lấy mọi cơ sở phụ huynh đã nêu trong hội thoại, "2 hệ" thêm Kim Mã khi chưa có cơ sở Song ngữ (hệ đó chỉ có Kim Mã), còn chưa rõ cơ sở Quốc tế (Chùa Láng hay Mỹ Đình) thì hỏi, không đoán (ảnh theo cơ sở: thời khoá biểu, cơ sở vật chất); ảnh học phí đi theo hệ nên vẫn gửi (dòng Học phí).
  - Học phí: chủ đề "Học phí" hoặc "Ưu đãi" ở tin này hoặc tin trước (cờ `fee_asked` trong hồ sơ, chỉ giữ khi còn thiếu tuổi bé/cơ sở hoặc ảnh không vừa lượt (quá 5 ảnh); ảnh tháng này đã gửi hoặc Drive không có ảnh học phí của hệ thì xoá, để tháng sau không tự gửi khi phụ huynh không hỏi), đã biết tuổi bé và cơ sở → ảnh học phí của mỗi hệ (nhiều cơ sở khác hệ thì mỗi hệ một ảnh; Chùa Láng, Mỹ Đình dùng chung ảnh Quốc tế, nên tin xin học phí "2 hệ" khi chưa rõ cơ sở Quốc tế vẫn nhận ảnh học phí hệ Quốc tế, nhãn "học phí hệ Quốc tế" không nêu cơ sở, không hỏi cơ sở; review 2026-10-24) tháng hiện tại (hệ theo bảng cố định `CAMPUS_SYSTEMS` trong `app/media.py`: Chùa Láng, Mỹ Đình là Quốc tế, Kim Mã là Song ngữ, kể cả khi Drive thiếu thư mục cơ sở; cơ sở mới ngoài bảng theo thư mục hệ chứa nó trên Drive) giờ Việt Nam; mỗi phụ huynh mỗi tháng 1 lần (`fee:<hệ>:<YYYY-MM>`). Không để số khi được xin (tin bot trước có SĐT/Zalo) hoặc đã từ chối số, chưa có SĐT, mà tin này hoặc tin trước (cờ `fee_asked`) hỏi học phí: đã biết cơ sở thì gửi luôn, chưa biết tuổi cũng gửi (review vòng thời khoá biểu v3: hỏi học phí, bot xin SĐT, phụ huynh "thôi không để số đâu em" → gửi). "Hỏi học phí" ở đây là của phụ huynh (chủ đề "Học phí"/"Ưu đãi", hoặc chữ "học phí"/"bảng phí" trong tin), không phải token `[SEND:fee]` của câu trả lời; câu bot xin SĐT/Zalo "để em gửi bảng học phí chi tiết" (tư vấn viên gửi qua Zalo) không có token nên không gửi ảnh nào (review 2026-10-24: phụ huynh hỏi xe đưa đón, chưa biết tuổi, nhận ảnh học phí). Chưa có ảnh tháng này thì gửi tháng gần nhất trước đó và báo nhóm Telegram nhắc trường cập nhật; thư mục tháng không ghi năm nên ảnh sửa lần cuối trên Drive hơn 300 ngày trước (`FEE_STALE_AFTER`; học phí giữ nguyên vài tháng vẫn là ảnh mới; vd ảnh tháng 11/2026 còn để tới tháng 11/2027) cũng là ảnh cũ: vẫn gửi và báo nhóm như vậy (review 2026-10-23), mỗi hệ tối đa 1 lần mỗi ngày (nhớ trong bộ nhớ: khởi động lại có thể báo thêm 1 lần).
  - Thời khoá biểu (người vận hành 2026-10-24, thay quyết định cũ "chưa biết tuổi thì gửi ảnh nhóm 3–5 tuổi, chưa biết cơ sở thì Mỹ Đình/Kim Mã theo hệ quan tâm"; lý do: "chỉ cần hỏi là quan tâm tới cơ sở nào hoặc độ tuổi để cô gửi cho chuẩn"): chủ đề "Chương trình/phương pháp", hoặc tin có chữ "Cambridge", "thời khóa biểu", "thời gian biểu", "TKB", "lịch học" (không tính "lịch học thử", tuần học thử: xét trên chữ có dấu của phụ huynh, "thử" là học thử, "thứ" là thời khoá biểu; tin không dấu "lich hoc thu …" chỉ là thời khoá biểu khi theo sau là 2–7, "hai" hay "bay", vì "ba", "tu", "nam", "sau" còn nghĩa khác, review vòng thời khoá biểu v3: "lịch học thử 1 tuần/từ thứ 2/ba ngày" bị tính là thời khoá biểu; chọn theo chữ vì model gắn câu Cambridge vào "Tiếng Anh/GV nước ngoài", câu thời khoá biểu vào "Giờ học…") → chỉ gửi khi đã biết CƠ SỞ và TUỔI BÉ: ảnh của từng cơ sở phụ huynh quan tâm theo tuổi bé (tháng). Không có mặc định. Thiếu cơ sở và/hoặc tuổi bé: không gửi ảnh, dòng `[HỆ THỐNG]` dặn hỏi đúng cái còn thiếu "để em gửi đúng thời khoá biểu", không nói đã/sẽ gửi, không nói tư vấn viên sẽ gửi; cờ `timetable_asked` trong hồ sơ chờ, tin sau biết đủ thì gửi. Cờ xoá khi ảnh đã gửi hoặc Drive không có thời khoá biểu cho cơ sở/tuổi đó. Phụ huynh xin lại thời khoá biểu đã gửi: không gửi lại, dòng `[HỆ THỐNG]` dặn nói ảnh ở phía trên. Mỗi ảnh 1 lần cho mỗi phụ huynh.
  - Cơ sở vật chất: chủ đề "Cơ sở vật chất" và đã biết cơ sở → 4 ảnh của cơ sở đó (nhiều cơ sở: một cơ sở chưa gửi mỗi lượt, vì 2 cơ sở là 8 ảnh, quá trần 5). Chưa biết cơ sở: cờ `facilities_asked`, model hỏi cơ sở; biết cơ sở ở tin sau thì gửi. Cờ chỉ giữ khi chưa biết cơ sở (hoặc ảnh không vừa lượt); ảnh cơ sở đó đã gửi hoặc cơ sở không có ảnh thì xoá, để tin sau nhắc cơ sở khác không nhận ảnh (review 2026-10-23). Mỗi cơ sở 1 lần cho mỗi phụ huynh.
  - Thực đơn: chủ đề "Ăn uống/thực đơn" (hoặc model gắn ảnh thực đơn mẫu của Q&A) → ảnh thực đơn của hệ; chưa biết hệ thì hệ Quốc tế. Drive có ảnh thực đơn thì ảnh cũ `static/thuc-don-mau.jpg` không gửi nữa; Drive chưa có thì giữ ảnh cũ. Mỗi ảnh 1 lần cho mỗi phụ huynh.

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
- Trường làm việc thứ 2–6; cuối tuần phải sắp xếp riêng người đón tiếp.
- Hotline: 0989 059 838.
- Cambridge Early Years hệ Quốc tế (3–6 tuổi): hằng ngày thứ Hai–thứ Sáu, tổng ~1,5–2 giờ/ngày; sáng English ~30–40 phút; chiều ~14:45–16:00 luân phiên Mathematics hoặc Let's Explore. Kim Mã: Cambridge môn English khoảng 40 phút, cộng các giờ học khác bằng tiếng Anh với giáo viên nước ngoài.
- Khai giảng chính thức 05/09 hằng năm; nhận hồ sơ và nhập học quanh năm.
- Tặng 1 tuần học thử hoàn toàn miễn phí.
- Cam kết không tăng học phí cơ bản trong suốt thời gian con theo học; tiền ăn và các khoản phí khác vẫn điều chỉnh bình thường (trường xác nhận 2026-10-23).
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
2. Kể giá trị trước, con số sau: giáo viên nước ngoài toàn thời gian (hệ Quốc tế), Cambridge Early Years kết hợp Montessori, cam kết không tăng học phí cơ bản.
3. Tổng chi phí thực tế do tư vấn viên tính và gửi, không tính trên chat.
4. Dùng "học thử 1 tuần miễn phí" làm bước trung gian với khách còn phân vân.
5. CARE khi chê đắt/so sánh trường khác: Connect → Acknowledge → Resolve → Evaluate.
6. Luôn kết thúc bằng một bước tiếp theo cụ thể (xin SĐT, hẹn tham quan, hẹn học thử), trừ lúc vừa chốt lịch hẹn (chỉ xác nhận ngắn; chưa có SĐT và phụ huynh chưa từ chối để số thì xin SĐT/Zalo mềm 1 lần để tư vấn viên gọi xác nhận giờ, đã xin rồi thì không xin lại). Từ 2026-10-22 (mục 2f): mời mềm trước, phụ huynh đồng ý rồi mới hỏi thời gian.
7. Điều hướng xin SĐT để tư vấn qua Zalo hoặc gọi điện.
