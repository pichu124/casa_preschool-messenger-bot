# Kiểm kê dữ kiện trong prompt và code (2026-10-23)

Mục tiêu (người vận hành đã đồng ý): dữ kiện về trường chỉ nằm ở `data/qa_database.json`, để trường sửa thông tin thì chỉ sửa một chỗ. Phân loại:

- Dữ kiện, nội dung trả lời → Q&A.
- Luật hành xử (khi nào hỏi gì, không nói gì, xử lý tình huống) → prompt.
- Câu cố định trường duyệt nguyên văn, hoặc việc phải chắc chắn (mẫu nhắc lại, câu chuyển tư vấn viên, nút) → code.

Cách đọc: dòng ghi `trước → sau`, "trước" là commit 058f73c. Q&A đánh số như `QADatabase.build_context()` đưa vào prompt (từ 1), kèm câu hỏi đầu của cặp. Cặp admin dạy thêm chỉ nối vào cuối, nên số của các cặp dưới đây không đổi.

## Mâu thuẫn cần trường xác nhận

1. **Cam kết không tăng: "học phí" hay "học phí cơ bản"?**
   - Ghi "không tăng học phí": prompt `app/ai_engine.py:44 → 40` (kể giá trị trước khi nói học phí), câu ví dụ CARE `:109 → 105`, Q&A #56 "Học phí của trường như thế nào ạ?", Q&A #57 "Ưu đãi học phí như thế nào ạ?", `docs/quyet-dinh-noi-dung.md` mục 4 và mục 5.2.
   - Ghi "không tăng học phí cơ bản": Q&A #61 "Casa có cam kết ổn định học phí không?".
   - Câu hỏi cho trường: cam kết chỉ áp cho học phí cơ bản, hay cả tiền ăn và các khoản phí khác? Chưa sửa bên nào.

## Mâu thuẫn đã sửa theo quyết định mới nhất

- **Nhóm tuổi nhỏ nhất.** Q&A #97 "Các hoạt động ngoại khóa có phù hợp với từng độ tuổi không?" và Q&A #103 "Các bé nhỏ có được tham gia dã ngoại không?" ghi "18–36 tháng"; prompt (`:39 → 35`) và các cặp chương trình ghi "15 tháng–3 tuổi". Quyết định đợt 1 (`docs/quyet-dinh-noi-dung.md`, mục 1 ý 1 và mục 3) là nhận bé từ 15 tháng. "18–36 tháng" sót lại từ tuổi nhận cũ 18 tháng (test đã cấm "18 tháng–6 tuổi"), và bỏ sót bé 15–18 tháng. Đã sửa cả hai thành "15 tháng–3 tuổi"; `tests/test_knowledge.py::test_admission_age_is_15_months_walking_steadily` cấm "18–36 tháng".

## Bảng kiểm kê

### SYSTEM_PROMPT (`app/ai_engine.py`)

| # | Dữ kiện | Dòng | Q&A | Mâu thuẫn | Quyết định |
|---|---|---|---|---|---|
| P1 | Câu mở đầu: phụ huynh "có con 15 tháng–6 tuổi" | 15 → 15 | #1 "Casa dei Bambini là trường như thế nào?", #3 "Trường nhận bé từ bao nhiêu tháng tuổi?" | Không | Giữ nguyên (harness verify nhận diện lời gọi chat qua câu đầu) |
| P2 | 3 cơ sở và hệ: Quốc tế Chùa Láng, Quốc tế Mỹ Đình, Song ngữ Kim Mã | 28–31 → 28 | #2 "Trường ở đâu ạ?", #1 | Không | Giữ tóm tắt (tên cơ sở + hệ) |
| P3 | Địa chỉ đầy đủ (tầng, tòa Hongkong Tower/FLC Complex, số nhà, phường) | 29–31 → bỏ | #2 (giống từng chữ) | Không | Chuyển |
| P4 | Nhận bé từ 15 tháng, đã đi vững | 32 → 29 (thêm "đến 6 tuổi") | #3, #1 | Không | Giữ tóm tắt |
| P5 | Giáo viên nước ngoài: hệ Quốc tế cả ngày 8h30–17h00; hệ Song ngữ theo khung giờ cố định | 33 → bỏ | #29 "Khác nhau giữa hệ Song ngữ và hệ Quốc tế là gì ạ?", #40 "Trường có giáo viên nước ngoài thật không ạ hay chỉ quảng cáo?", #30 "Mỗi ngày con được học bao nhiêu tiết tiếng Anh?" | Không | Chuyển |
| P6 | Giờ đón chuẩn 17h30 | 34 → bỏ | #46 "Giờ đón muộn là mấy giờ ạ?" | Không | Chuyển |
| P7 | Khai giảng 05/09 hằng năm; nhận hồ sơ, nhập học quanh năm | 35 → bỏ | #4 "Ngày khai giảng là khi nào ạ?" | Không | Chuyển |
| P8 | Không nêu con số học phí | mục 2: 43, 45 → 39, 41; thêm vào CỐT LÕI: 30 | #56 (không có con số) | Không | Giữ tóm tắt (thêm vào CỐT LÕI theo brief); luật mục 2 giữ nguyên |
| P9 | Tặng 1 tuần học thử miễn phí | 50, 52 → 46, 48; thêm vào CỐT LÕI: 31 | #5 "Có cho con học thử được không ạ?", #8, #57 | Không | Giữ tóm tắt; luật mục 4, 5 giữ nguyên |
| P10 | Nhóm 15 tháng–3 tuổi: chăm sóc, thích nghi, ngôn ngữ, vận động, giác quan, tự lập, cảm xúc – xã hội qua Montessori; làm quen tiếng Anh với giáo viên nước ngoài | 39 → 35 | #23 "Trẻ 15 tháng–3 tuổi học gì nếu chưa học Cambridge?", #3, #9, #10 | Tên nhóm ở Q&A #97, #103 (đã sửa, xem trên) | Giữ tóm tắt 1 dòng (nền tảng qua Montessori, tiếng Anh với giáo viên nước ngoài); chi tiết theo Q&A |
| P11 | Nhóm 3–6 tuổi: Cambridge Early Years kết hợp Montessori; nội dung, thời lượng theo chương trình/cơ sở; chưa biết cơ sở thì nói chung | 40 → 36 | #9, #12, #13, #15 | Không | Giữ nguyên (luật trường đợt 7, mục 2g.4; test khoá) |
| P12 | Bé dưới 15 tháng hoặc chưa đi vững: xin ngày sinh | 41 → 37 | #3 | Không | Giữ nguyên (luật) |
| P13 | Giá trị kể trước học phí: giáo viên nước ngoài cả ngày (hệ Quốc tế), Cambridge Early Years kết hợp Montessori, cam kết không tăng học phí | 44 → 40 | #56, #61 | "học phí" hay "học phí cơ bản" (mục trên) | Giữ nguyên (luật kịch bản, nguyên tắc 2); chờ trường |
| P14 | Ưu đãi: không nêu %; anh chị em ruột, cư dân tòa nhà theo cơ sở | 48–49 → 44–45 | #57, #58 "Nhà trường có ưu đãi cho gia đình có nhiều con cùng học không?" | Không | Giữ nguyên (luật trường đợt 1; mức % đã ở Q&A) |
| P15 | Trường làm việc thứ 2–6; không hứa cuối tuần | 51 → 47 | #7 "Thứ 7, Chủ nhật có tham quan trường được không?" | Không | Giữ nguyên (bot từng hứa "xếp mẹ ghé thứ 7", mục 2g.3) |
| P16 | CARE: nêu giá trị, không gợi ý cơ sở rẻ hơn | 52 → 48 | – | Không | Giữ nguyên (luật đợt 3) |
| P17 | Xe bus: chưa có tuyến, đủ phụ huynh đăng ký thì mở tuyến; không nêu tuyến, phí, ưu đãi | 58 → 54 | #55 "Trường có xe bus đưa đón không ạ?" | Không | Giữ nguyên (luật "không nói gì" đợt 2–3; test khoá cả prompt lẫn nhắc nhở) |
| P18 | Câu chào tin đầu | 65 → 61 | – (câu cố định) | Không | Giữ nguyên |
| P19 | [ESCALATE] khi hỏi dữ kiện không có trong Q&A (tên giáo viên, ngày sự kiện, lịch chi tiết) | 74 → 70 | – | Không | Giữ nguyên (lỗi production 2026-10-22) |

Câu ví dụ "Em: …" (dạy giọng văn; nội dung khớp Q&A nên không đổi):

| # | Dữ kiện trong ví dụ | Dòng | Q&A | Mâu thuẫn | Quyết định |
|---|---|---|---|---|---|
| E1 | Học phí tùy độ tuổi và cơ sở | 95 → 91 | #56 | Không | Giữ |
| E2 | Nhận bé từ 15 tháng, đi vững; tự lập, vận động qua Montessori, tiếng Anh với cô nước ngoài | 97 → 93 | #3, #23 | Không | Giữ (test chống lệch kiểm con số 15 tháng) |
| E3 | Đã biết Mỹ Đình: Cambridge Early Years, cô nước ngoài ở lớp cả ngày | 103 → 99 | #29, #40 | Không | Giữ |
| E4 | Cô đồng hành sát sao, không ép; 1 tuần học thử miễn phí | 106 → 102 | #54 "Con đi học khóc thì cô có bế không ạ?", #5 | Không | Giữ |
| E5 | CARE: hệ Quốc tế có cô nước ngoài cả ngày, học phí không tăng | 109 → 105 | #29, #56, #61 | Như P13 | Giữ (xem ghi chú cuối file) |
| E6 | Ưu đãi hấp dẫn, tùy từng đợt/chương trình | 115 → 111 | #57 | Không | Giữ |
| E7 | Chưa có tuyến xe bus, đủ phụ huynh đăng ký sẽ mở tuyến | 118 → 114 | #55 | Không | Giữ |

Các ví dụ còn lại (xin SĐT, hỏi tuần học thử, chốt sáng mai) không mang dữ kiện.

### Khối NHẮC NHỞ (`AIEngine.get_response`, `app/ai_engine.py`)

| # | Dữ kiện | Dòng | Q&A | Mâu thuẫn | Quyết định |
|---|---|---|---|---|---|
| R1 | Câu chào tin đầu | 514 → 510 | – | Không | Giữ nguyên |
| R2 | Chưa biết cơ sở thì không kể khác biệt giữa các hệ (môn Cambridge, thời lượng, giáo viên nước ngoài) | 551 → 547 | #29 | Không | Giữ nguyên (luật đợt 7) |
| R3 | Câu nút "Em muốn đăng ký cho bé học thử 1 tuần ạ" | 559 → 555 | #5; = `app/messenger.py:35` | Không | Giữ nguyên |
| R4 | Học phí, ưu đãi: không nói con số, không nêu % | 563 → 559 | #56, #57 | Không | Giữ nguyên |
| R5 | Xe bus như P17 | 566 → 562 | #55 | Không | Giữ nguyên |
| R6 | Trường làm việc thứ 2–6 | 576 → 572 | #7 | Không | Giữ nguyên |

Không chuyển gì khỏi khối NHẮC NHỞ: mọi dữ kiện ở đây là một phần của một luật chặn lỗi đã gặp.

Prompt trích xuất hồ sơ (`extract_customer_info`, dòng 645–646 → 641–642): giá trị `interested_program` ("song ngữ"/"quốc tế") và `interested_campus` ("Chùa Láng"/"Mỹ Đình"/"Kim Mã"). Đây là giá trị của trường hồ sơ, giữ trong code.

### Code

| # | Dữ kiện | Nơi | Q&A | Mâu thuẫn | Quyết định |
|---|---|---|---|---|---|
| C1 | Nút: tên 3 cơ sở, nhóm tuổi (Dưới 2, 2-3, 3-5, 5-6 tuổi, trường duyệt đợt 3b), "học thử 1 tuần" | `app/messenger.py:13–50` | #2, #5 | Không | Giữ trong code (test chống lệch kiểm tên cơ sở và số tuần) |
| C2 | Ice breakers | `app/messenger.py:58–63` | – (câu hỏi trường duyệt đợt 3a) | Không | Giữ trong code |
| C3 | Hotline 0989 059 838 và câu chuyển tư vấn viên | `app/escalation.py:42–70` | Cặp hotline (cuối file) | Không | Giữ trong code (nguyên văn mục 2g.1; một hằng số `HOTLINE`); Q&A có cặp hotline cùng số, test khoá |
| C4 | Mẫu tin nhắc lại | `app/followup.py:52–70` | – | Không | Giữ nguyên văn |
| C5 | Regex nhận diện câu bot gửi đã nói tới trường: huỳnh thúc kháng, hong kong, phạm hùng, flc, ngõ 294, "3 cơ sở" | `app/coverage.py:16` | #2 | Không | Giữ trong code. Trường đổi địa chỉ thì sửa cả regex này |
| C6 | Kỳ vọng của bộ chấm: địa chỉ trong `SCHOOL_INFO` và kịch bản "truong_o_dau" | `scripts/eval_chat.py:137, 149` | #2 | Không | Giữ; model vẫn thấy địa chỉ qua Q&A |

`app/main.py`, `app/customer_memory.py`, `app/topics.py` không chứa dữ kiện về trường.

## Kết quả

- SYSTEM_PROMPT (không tính `{qa_context}`): 9985 → 9659 ký tự (tính cả placeholder: 9997 → 9671).
- THÔNG TIN CỐT LÕI còn: 3 cơ sở và hệ; nhận bé 15 tháng (đã đi vững) đến 6 tuổi; không nêu con số học phí; 1 tuần học thử miễn phí. Model vẫn thấy dữ kiện đã chuyển vì Q&A được nạp toàn bộ vào prompt.
- Chống lệch (`tests/test_prompt.py`): dữ kiện đã chuyển không còn trong prompt mà tới model qua Q&A; cơ sở và hệ, tuổi nhận, số tuần học thử, ngày làm việc trong prompt (và nút) khớp Q&A; giờ hay ngày còn trong prompt phải có trong Q&A. `tests/test_knowledge.py` kiểm Q&A còn giờ giáo viên nước ngoài theo hệ và nội dung nhóm 15 tháng–3 tuổi.
- Chưa có model thật để đo. Cần chạy `scripts/eval_chat.py` với API key trên bản trước (058f73c) và bản này rồi so kết quả.

## Ghi chú cho lead (luật hành xử, không sửa trong đợt này)

- Ví dụ CARE (`:105`) và luật kể giá trị (`:40`) nêu "giáo viên nước ngoài cả ngày (hệ Quốc tế)" khi chưa biết cơ sở. Khối NHẮC NHỞ (`:547`) lại dặn: chưa biết cơ sở thì không tự kể khác biệt giữa các hệ, kể cả giáo viên nước ngoài.
- Mục 2 (`:39`) "Chưa biết tuổi bé VÀ cơ sở quan tâm thì KHÔNG nói con số" có thể được hiểu là biết rồi thì được nói. CỐT LÕI (`:30`) và quyết định mục 3 thì không bao giờ nêu con số. Q&A không có con số nên rủi ro thấp.
- ~~Q&A không có cặp hotline~~: đã thêm cặp hotline (0d3b55f), số khớp `HOTLINE` trong app/escalation.py (test_hotline_is_in_qa_and_matches_the_handover_message).
