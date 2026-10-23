---
name: verify-casa-bot
description: Chạy bot Messenger Casa dei Bambini (FastAPI, app/main.py) thật trên máy, cách ly hoàn toàn khỏi internet, rồi đóng vai Facebook và Telegram gửi sự kiện vào (tin chữ, quick reply, postback, referral, echo, admin reply) và đọc lại những gì bot gửi ra Graph API, Telegram, Google Sheet, GitHub, model AI (OpenAI, Gemini). Dùng khi cần bằng chứng hành vi người dùng thấy cho một thay đổi trong app/ (verifier, implementer tự thử), không dùng cho chuyện chỉ cần pytest.
---

# Kiểm chứng bot Casa trên app thật

Bề mặt chính là **HTTP service**: Facebook gọi `POST /webhook`, Telegram gọi `POST /telegram-webhook`, admin gọi các endpoint có `?secret=`. Bot trả lời bằng cách **gọi ra ngoài** (Graph API, Telegram, Apps Script, GitHub, model AI), nên bằng chứng chính là các request đi ra đó.

Harness nằm trong [harness/](harness/), chỉ dùng stdlib (app chạy bằng `.venv` của repo):

| Script | Việc |
|---|---|
| `ctl.py` | `up`, `doctor`, `env`, `scenario`, `down` một instance cách ly |
| `send_event.py` | gửi sự kiện Messenger/Telegram giả, in các request bot gửi ra vì nó |
| `read_back.py` | đọc lại outbox, hồ sơ khách (`/customers` hoặc file của bản sao), log app |
| `fake_server.py` | thay mọi dịch vụ ngoài, ghi từng request vào `outbox.jsonl`, trả lời theo kịch bản |
| `launcher.py` | chạy `app.main:app` trong bản sao: chặn mạng, viết lại httpx về fake |
| `scenario.default.json` | kịch bản trả lời của model giả (token như `ASK_AGE`, `HARD_QUESTION`) |

Feature map: [features/README.md](features/README.md).

## An toàn: vì sao phải đi qua harness

Môi trường agent có `GITHUB_TOKEN`/`GH_TOKEN` **thật**, và `app/github_sync.py` đẩy `data/qa_database.json` lên `main` của repo **public** `pichu124/casa_preschool-messenger-bot` (push lên `main` là deploy) mỗi khi admin trả lời qua Telegram. `app/config.py` gọi `load_dotenv()`, đọc `.env` thật nếu tìm thấy. Vì vậy:

- **Không** chạy `uvicorn app.main:app` trực tiếp trong repo để kiểm chứng. Luôn dùng `ctl.py up`.
- `ctl.py up` chép working tree (file tracked và untracked chưa bị ignore; **không** chép `.env*`, `data/customers.json`, `artifacts/`) sang `$TMPDIR/casa-verify/<slug>/app`, nằm ngoài mọi repo, nên `load_dotenv()` không tìm được `.env`. `data/customers.json` của bản sao là `{}`: dữ liệu phụ huynh thật không bao giờ vào bản sao hay bằng chứng.
- App và fake chạy dưới `/usr/bin/env -i` với mọi biến trong `app/config.py` đặt sẵn giá trị giả có run id: `GITHUB_TOKEN=fake-github-token-…`, không có `GH_TOKEN`. `launcher.py` từ chối khởi động nếu thấy `GH_TOKEN`, `GITHUB_TOKEN` không bắt đầu bằng `fake-`, `GEMINI_API_KEY` có giá trị không bắt đầu bằng `fake`, `GEMINI_API_KEY` có giá trị khi `aiohttp` được cài (google-genai sẽ gửi qua aiohttp, lọt khỏi chỗ viết lại httpx), biến proxy bất kỳ (`HTTP_PROXY`, `https_proxy`, `ALL_PROXY`, … mọi tên kết thúc bằng `_PROXY` trừ `NO_PROXY`: httpx sẽ gửi request qua proxy đó), hoặc `.env` ở thư mục cha.
- `launcher.py` chặn DNS tới mọi tên không phải loopback và TCP connect tới mọi đích trừ port của fake và của app trên loopback (proxy của môi trường agent chạy ở `127.0.0.1` cũng bị chặn; ghi `BLOCKED` vào `netlog.txt`), viết lại mọi request httpx (cả OpenAI SDK và google-genai của Gemini: client của nó kế thừa `httpx.AsyncClient`) về fake, và ép uvicorn dùng loop `asyncio` (uvloop connect bằng C, lọt qua guard).
- Không request internet thật, không gửi tin cho phụ huynh thật. `--env` của `ctl.py up` từ chối `GH_TOKEN`, `GITHUB_PAT`, `GITHUB_TOKEN` thật, `GEMINI_API_KEY` không bắt đầu bằng `fake` và biến `*_PROXY` (trừ `NO_PROXY`); `doctor` báo `FAIL` nếu process app có biến proxy hoặc `GEMINI_API_KEY` thật.

## Launch

Từ gốc repo hoặc worktree cần kiểm (bản sao lấy đúng code đang có trên đĩa, kể cả chưa commit):

```bash
python3 .claude/skills/verify-casa-bot/harness/ctl.py up --slug <slug>
# tuỳ chọn: --env FOLLOWUP_ENABLED=true   --env TOPICS_SHEET_ENABLED=true   --scenario <file.json>   --source <thư mục repo khác>
```

Mặc định model là OpenAI giả (`AI_MODEL_ORDER=openai`, các key khác rỗng). Kiểm provider Gemini (SDK google-genai): `ctl.py up --slug <slug> --env GEMINI_API_KEY=fake --env AI_MODEL_ORDER=gemini`, thêm `--env GEMINI_MODEL=<tên>` để thử tên model khác (mặc định `gemini-3.5-flash` của `app/config.py`). Chuỗi dự phòng: `--env AI_MODEL_ORDER=openai,gemini` cùng `fail.openai` trong kịch bản.

`<slug>` ngắn, không dấu, vd `gd36-quick-age`; mọi lệnh sau dùng `--slug <slug>` hoặc `export CASA_VERIFY_SLUG=<slug>`. Port app và fake do hệ điều hành cấp, secret sinh mới mỗi lần, nên nhiều instance (slug khác nhau) chạy song song được.

**Sẵn sàng** khi lệnh in `READY http://127.0.0.1:<port> slug=… run_id=…` và exit 0. `up` chỉ in READY khi cả ba đúng: fake trả đúng run id; `GET /` trả `status: ok` với `qa_pairs > 0` (Q&A đã nạp); `GET /webhook?hub.mode=subscribe&hub.verify_token=<token của run>` trả lại challenge. App chết hoặc 40 giây chưa sẵn sàng thì `up` tự tắt những gì vừa bật, in đuôi `app.log` và exit 1.

Đổi code sau khi `up` thì bản sao đã cũ: `down` rồi `up` lại (`doctor` báo `STALE`).

## Doctor

```bash
python3 .claude/skills/verify-casa-bot/harness/ctl.py doctor --slug <slug>
```

Chỉ đọc. In `DOCTOR OK` (exit 0) khi: hai pid còn sống và mang `CASA_VERIFY_RUN_ID` của run này (không phải pid tái dùng của ai khác); app dùng được như ở Launch; môi trường của process app không có `GH_TOKEN` và `GITHUB_TOKEN` là giả; `netlog.txt` không có dòng `BLOCKED` (app chưa từng thử ra internet); outbox không có host lạ; bản sao còn khớp working tree của nguồn. Dòng `build:` cho biết commit nguồn và có thay đổi chưa commit hay không. Sai điều nào thì in `FAIL …` và exit 1. Chỉ drive instance mà `doctor` của chính mình báo OK.

## Drive

Lấy biến để dùng với curl: `eval "$(python3 .claude/skills/verify-casa-bot/harness/ctl.py env --slug <slug>)"` cho `CASA_APP`, `CASA_SECRET`, `CASA_VERIFY_TOKEN`, `CASA_COPY`, `CASA_EVIDENCE`, `CASA_OUTBOX`, `CASA_FAKE` (fake server; `POST $CASA_FAKE/__fake/github-commit?path=…` giả một commit khác lên GitHub, xem [features/escalation-admin-reply.md](features/escalation-admin-reply.md)).

**Sự kiện Messenger** (đường thật của Facebook: `POST /webhook`, body ký `X-Hub-Signature-256` bằng `FB_APP_SECRET` của run). `PSID` là id phụ huynh giả, dùng chuỗi số dài khác nhau cho mỗi phụ huynh, vd `9000000000000001`:

```bash
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> text 9000000000000001 "ASK_AGE Cho em hỏi về trường ạ"
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> quick 9000000000000001 QR:age:1 --text "2-3 tuổi"   # bấm nút trả lời nhanh
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> phone 9000000000000001 0912345678                    # nút SĐT của Messenger
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> postback 9000000000000002 GET_STARTED --referral ADS --ad-id AD1 --ad-title "Khai giảng"
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> postback 9000000000000002 IB_1                       # ice breaker
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> referral 9000000000000003 --referral SHORTLINK --ref casa   # mở thread, chưa nhắn
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> echo 9000000000000001 "Chị gọi lại nhé"              # nhân viên tự nhắn trong hộp thư Page
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> echo 9000000000000001 "..." --bot                    # echo tin của chính bot
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> raw event.json                                       # sự kiện tự viết
python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> tg-reply "Cô Lan chủ nhiệm lớp Mầm"                  # admin reply escalation gần nhất
```

Cờ hay dùng: `--mid X` (gửi lại cùng mid để thử dedup), `--bad-signature`, `--no-signature`, `--bad-secret` (tg-reply), `--no-wait`, `--full` (in nguyên bản ghi outbox). Cờ chung `--slug`, `--no-wait`, `--full` đứng trước tên lệnh con.

`send_event.py` in `SENT <lệnh> -> HTTP <code> <body>` rồi chờ tới khi bot ngừng gửi ra 1,5 giây (tối đa 30 giây), in mỗi request gửi ra một dòng, vd:

```
#6   200 FB  to=9000000000000001 TEXT "Dạ Casa chào Ba/Mẹ ạ 🌿 Bé nhà mình năm nay mấy tuổi ạ?" QUICK=["QR:age:0", ...]
#14  200 SHEET {"event": "new_phone", "customer_id": "...", "phone": "0912345678", ...}
#16  200 SHEET {"type": "topic", "customer_id": "...", "topics": "Học phí", "escalated": "Không", "question": "HOC_PHI ...", ...}
#15  200 TG  sendMessage message_id=5003 header='📞 KHÁCH ĐỂ LẠI SĐT'
#22  200 TG  sendMessage message_id=5006 reply_to=5003 header='🔄 Test Parent: Hẹn: tham quan buổi sáng'
```

Webhook trả 200 ngay rồi xử lý nền, nên HTTP 200 **không** chứng minh gì; dòng outbox mới là kết quả.

**Model AI giả.** Mọi lời gọi model (trả lời, trích xuất hồ sơ, viết lại admin reply, phân loại Q&A, tóm tắt) đi tới fake, được phân loại theo câu mở đầu system prompt trong `app/ai_engine.py`, và trả lời theo rule đầu tiên khớp trong kịch bản. `chat` và `extract` so `contains` với **đúng phần phụ huynh viết** (fake cắt ra khỏi prompt); loại khác so với cả tin. Kịch bản mặc định ([harness/scenario.default.json](harness/scenario.default.json)):

| Phụ huynh viết chứa | Model trả lời |
|---|---|
| `ASK_AGE` | câu hỏi tuổi + `[QUICK:age]` |
| `ASK_PHONE` | xin SĐT + `[QUICK:phone]` |
| `ASK_VISIT` | hỏi sáng/chiều + `[QUICK:visit_time]` (bước sau khi phụ huynh đồng ý tham quan) |
| `INVITE_VISIT` | mời tham quan dạng hỏi ý + `[QUICK:visit_invite]` (Đặt lịch tham quan / Tìm hiểu thêm) |
| `Em muốn đặt lịch tham quan trường` | (nghĩa của nút `QR:visit_invite:0` và `QR:topics:2`) hỏi sáng/chiều + `[QUICK:visit_time]`; extract `visit_request: tham quan trường` |
| `SEND_MENU` | chữ + `[IMAGES:static/thuc-don-mau.jpg][QUICK:age]` |
| `BAD_QUICK` | `[QUICK:khong_co_nut_nay]` (key không tồn tại) |
| `HARD_QUESTION` | `[ESCALATE]` |
| `TOUR_CAMPUS` | cơ sở Mỹ Đình (FLC, 36 Phạm Hùng), lớp 80–90 m², Cambridge + Montessori, mời tham quan + `[QUICK:visit_invite]`; extract `interested_campus: Mỹ Đình` |
| `TOUR_MENU` | thực đơn đủ nhóm chất, mời học thử 1 tuần miễn phí + `[QUICK:trial_invite]` |
| `TOUR_EXTRA` | ngoại khóa (Science, Cooking, Art, Music, dã ngoại). Ba câu `TOUR_*` cộng lại phủ đủ nhóm của `app/coverage.py` (tư vấn tương đối đủ) |
| `Bé nhà em 2-3 tuổi` | nghĩa của nút `QR:age:1`: trả lời + `[QUICK:visit_invite]`; extract `kid_age: 2-3 tuổi` (nhãn nút) |
| `PHONE_A` / `PHONE_B` | extract `phone` 0912345678 / 0987654321 |
| `VISIT_AM`, `Em muốn hẹn tham quan buổi sáng` | (nghĩa của nút `QR:visit_time:0`) extract `visit_request: tham quan buổi sáng` |
| `VISIT_TOMORROW` | extract `visit_request: tham quan sáng mai` (đổi lịch hẹn) |
| `START_DEC` | extract `expected_start: tháng 12` (lead nói thêm thông tin) |
| `DECLINE` | extract `phone_declined: true` |
| `UPSET` | extract `upset: true, phone_declined: true` (phụ huynh khó chịu, đòi thông tin qua chat: bot gửi câu xin lỗi và chuyển tư vấn viên) |
| `HOC_PHI` | extract `topics: ["Học phí"]` (chủ đề của tin: dashboard, tab "Chủ đề" của Sheet) |
| (khác) | `Dạ Casa chào Ba/Mẹ ạ, em hỗ trợ ngay ạ.`; extract `{}` |

Chữ trên nút (`--text`), nghĩa của nút và câu ice breaker lấy từ `QUICK_REPLIES` và `ICE_BREAKERS` trong `app/messenger.py`; `tests/test_verify_skill.py` đỏ khi kịch bản, feature map hay ví dụ ở đây lệch khỏi đó.

Fake trả lời theo cùng kịch bản cho cả hai dạng request: OpenAI-style `POST …/chat/completions` (system là message `system`, tin là message cuối) và Gemini REST `POST generativelanguage.googleapis.com/v1beta/models/<model>:generateContent` (system là `systemInstruction`, tin là phần tử cuối của `contents`; trả `candidates[0].content.parts[0].text`, role `model`, `finishReason: STOP`). Đọc request Gemini: `read_back.py outbox --host ai` in `AI chat rule='ASK_AGE' model=gemini-3.5-flash` (model lấy từ path); `--full` cho `path`, `body.systemInstruction.parts[0].text` (cắt còn 200 ký tự kèm độ dài), `body.contents` (role `user`/`model`, lịch sử trước tin cuối) và `body.generationConfig`. Key Gemini đi trong header `x-goog-api-key`, không ghi vào outbox.

Cần câu trả lời khác thì chép file đó, sửa `rules` (thứ tự quan trọng), rồi `ctl.py scenario --slug <slug> <file>`; fake đọc lại kịch bản ở mỗi request, không cần restart. Cùng file đó điều khiển lỗi ở ranh giới (`fail.graph_send`, `fail.telegram`, `fail.telegram_reply` (Telegram từ chối mọi tin trả lời, như khi thẻ lead đã bị xoá), `fail.openai`, `fail.github_put`: true; `fail.sheet`: `ok`/`false`/`500`; `fail.openai` chỉ làm hỏng `/chat/completions`, Gemini không có công tắc lỗi), giờ hiện tại mà `app/followup.py` thấy (`now_utc`, ISO có múi giờ; `null` là giờ thật) và tên Facebook trả cho mọi PSID (`fb_profile`).

**Endpoint admin**: `curl "$CASA_APP/customers?secret=$CASA_SECRET"`; danh sách đầy đủ trong [features/admin-endpoints.md](features/admin-endpoints.md).

## Evidence

Mọi thứ của run nằm ở `artifacts/verify/<slug>/` của repo nguồn (đã gitignore):

| File | Nội dung |
|---|---|
| `outbox.jsonl` | mỗi request bot gửi ra: `seq`, `method`, `host`, `path`, `query`, `authorization`, `body` (system prompt và nội dung base64 bị cắt ngắn), `status`, `response`; với AI có `kind`, `rule`, `model` |
| `app.log` | stdout/stderr của uvicorn và app |
| `netlog.txt` | mỗi lần viết lại URL, mọi lần bị chặn (`BLOCKED`) |
| `github/repos/<owner>/<repo>/contents/<path>` | nội dung đã giải mã của mỗi lần PUT lên GitHub giả |
| `data_after/` | `ctl.py down` chép `data/` của bản sao: `customers.json`, `analytics.jsonl`, `pending_escalations.json`, `escalation_log.json`, `qa_database.json` |

Lưu transcript: `python3 .claude/skills/verify-casa-bot/harness/send_event.py --slug <slug> ... | tee -a artifacts/verify/<slug>/transcript.txt`. Đọc lại:

```bash
python3 .claude/skills/verify-casa-bot/harness/read_back.py --slug <slug> outbox [--host fb|tg|sheet|gh|ai] [--since SEQ] [--full]
python3 .claude/skills/verify-casa-bot/harness/read_back.py --slug <slug> profile 9000000000000001 --fields phone,kid_age,visit_request   # qua GET /customers
python3 .claude/skills/verify-casa-bot/harness/read_back.py --slug <slug> profile 9000000000000001 --fields phone --disk                  # file của bản sao
python3 .claude/skills/verify-casa-bot/harness/read_back.py --slug <slug> log --grep "Lead new_phone"
```

Tiêu chuẩn: đi đường của Facebook/Telegram/admin, không gọi hàm trong `app/`, không dùng `/test-chat` làm bằng chứng cho hành vi Messenger (nó bỏ qua webhook, quick reply, lead, escalation). Ghi **hành động** (lệnh `send_event.py`) và **kết quả** (dòng outbox, hồ sơ đọc lại). Thay đổi dữ liệu phải được đọc lại từ một view khác: `/customers` và `--disk`, hoặc outbox và `data_after/`. Chỉ mock ở ranh giới ngoài (fake server, đồng hồ), không bao giờ trong app.

## Cleanup

```bash
python3 .claude/skills/verify-casa-bot/harness/ctl.py down --slug <slug>
```

Chỉ tắt hai pid ghi trong `state.json` của slug đó, và chỉ khi pid còn mang run id của nó (không kill theo tên process). Chép `data/` của bản sao vào `data_after/`, xoá thư mục run `$TMPDIR/casa-verify/<slug>` (chỉ khi có file đánh dấu của harness), giữ nguyên `artifacts/verify/<slug>/` và in danh sách file bằng chứng. Sau một lần `up` hỏng, `up` đã tự tắt; chạy lại `up` cùng slug sẽ xoá thư mục run cũ.

## Helpers

- Python: `ctl.py` tìm interpreter có fastapi/uvicorn/httpx/openai ở `.venv` của nguồn, rồi `.venv` của checkout chính (worktree của agent không có `.venv` riêng), rồi `python3`. Thiếu thì chạy `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.
- `CASA_VERIFY_ROOT` đổi chỗ đặt thư mục run (mặc định `$TMPDIR/casa-verify`); không đặt nó bên trong repo (`up` từ chối nếu thư mục cha có `.env`).
- Đã chạy thử end-to-end ngày 2026-10-21 trên commit 2ca7261: up, doctor, tin chữ có `[QUICK:age]`, nút SĐT ra lead Telegram và Sheet, đổi SĐT, hẹn tham quan, ảnh, postback, referral, echo, dedup, chữ ký sai, escalation và admin reply, dựng lại escalation từ text, secret của mọi endpoint admin, follow-up (dry run và gửi thật với `now_utc`), xuất Excel, Graph API và Sheet hỏng, down. Chưa chạy: `fail.telegram`, `fail.github_put`, `/import-excel`, ảnh thật trong `static/`. Chạy lại ngày 2026-10-21 trên c027d3b cộng guard proxy: up, doctor, `ASK_AGE`, nút `QR:age:1` → `kid_age` 2-3 tuổi (qua `/customers` và `--disk`), `IB_1`, access log che `secret` và `hub.verify_token`, down. Chạy với Gemini ngày 2026-10-21 trên afeeafd cộng harness Gemini: up `GEMINI_API_KEY=fake AI_MODEL_ORDER=gemini`, doctor, `ASK_AGE` → FB có `QUICK=[...age...]`, request Gemini mang `gemini-3.5-flash` và `systemInstruction` đủ (58977 ký tự); up lại với `GEMINI_MODEL=verify-gem-x` → path và `model=` đổi theo, nút `QR:age:1` → `kid_age` 2-3 tuổi; netlog không có `BLOCKED`; down. Chạy ngày 2026-10-21 trên ae75b8a cộng kịch bản `TOUR_*`: hành trình của [features/followup.md](features/followup.md) với …0041–0049, `topics_covered` của …0047 đủ 7 nhóm (qua `/customers` và `--disk`), dry run và gửi thật ra đúng mẫu ở cả 6 PSID đến hạn, gọi lại không nhắc lần hai; down. Chạy lại ngày 2026-10-21 trên a4919da (mẫu nhắc lại đợt 5): cùng hành trình, …0048 (có tuổi, từ chối số, chưa đủ) ra `ask_phone`, 6 dòng FB trùng từng ký tự nguyên văn của trường, gọi lại không nhắc lần hai; down. Chạy lại ngày 2026-10-21 trên d172661 (gửi ngay trước khi hết cửa sổ 24 giờ): ba kịch bản `before`/`in`/`after` của [features/followup.md](features/followup.md) từ tin cuối 14:33 giờ VN → dry run `before` (11:03 hôm sau) `due: 0`, `after` (13:38) `due: 0`, `in` (12:33) `due: 6` đúng PSID và mẫu; gửi thật 6 dòng FB nguyên văn mẫu, gọi lại không nhắc lần hai, `followup_sent_at` bằng `now_utc` (`--disk`); netlog không có `BLOCKED`; down. Chạy ngày 2026-10-22 với code của 56cccc8 (một thẻ lead mỗi phụ huynh): …0011 `send phone` → `VISIT_AM` → `VISIT_TOMORROW` ra TG đúng 1 thẻ `📞 KHÁCH ĐỂ LẠI SĐT` và 2 tin `🔄 …` `reply_to=` id thẻ, 3 dòng SHEET cùng `customer_id`, `lead_card_msg_id` qua `/customers` và `--disk`; `tg-reply` vào tin `🔄` và vào thẻ → `no_escalation_found`, không có dòng FB; …0013 với `fail.telegram_reply` → TG 400 rồi thẻ mới, đổi lịch sau trả lời vào thẻ mới; app.log không có SĐT; netlog không có `BLOCKED`; down. Chạy ngày 2026-10-23 với code của info_update (chưa commit, trên 760ef76): …0014 `VISIT_AM` → `send phone` → `START_DEC Tầm tháng 12` ra TG 1 thẻ và 2 tin `🔄 …` `reply_to=` id thẻ, tin cuối `🔄 Test Parent: Dự kiến nhập học: tháng 12`, SHEET cuối `event` `Cập nhật thông tin` với `expected_start` `tháng 12`; gửi lại và PSID chưa là lead (…0015) không ra TG/SHEET; app.log không có SĐT; netlog không có `BLOCKED`; down. Chạy ngày 2026-10-23 với code kéo Q&A từ GitHub lúc nạp (chưa commit, trên c69e222): up → `GH GET …/qa_database.json` 200 đầu outbox, log `Loaded 105 Q&A pairs from GitHub`; …0061 `HARD_QUESTION` → `tg-reply` → `GH PUT` 106 cặp; ghi lại bản HEAD vào đĩa bản sao (105 cặp, không có cặp mới) rồi `POST /reload-qa` → `qa_pairs: 106`, `/qa-database` cuối là `Cô Lan chủ nhiệm lớp Mầm` `source: admin`, đĩa được ghi lại 106 cặp; chưa có lệnh restart thật; netlog không có `BLOCKED`; down. Chạy ngày 2026-10-23 với code sha/409 của Q&A (chưa commit harness, trên 557ece4): up → `GH GET` 200, `Loaded 105 Q&A pairs from GitHub`; …0061 `HARD_QUESTION` → `tg-reply` → một `GH PUT` 200 (không GET trước); ghi lại bản HEAD vào đĩa rồi `/reload-qa` → 106, cặp cuối `Cô Lan chủ nhiệm lớp Mầm` `source: admin`; `__fake/github-commit` một bản sửa tay (xoá cặp đầu, thêm `MANUAL_EDIT`) → …0062 `tg-reply` → `GH PUT` 409, `GH GET` 200, `GH PUT` 200, file trên GitHub giả 107 cặp có `MANUAL_EDIT`, `Cô Lan…` và cặp mới, cặp đã xoá không quay lại; `fail.github_put` → …0063 PUT 500, log ERROR `1 taught Q&A pairs not pushed`; bỏ lỗi → …0064 PUT 200, file 109 cặp có cả hai cặp; app.log không có token; doctor OK, netlog không có `BLOCKED`; down. Chạy ngày 2026-10-23 với code tab Chủ đề (chưa commit, trên 2dd8cf8): up `--env TOPICS_SHEET_ENABLED=true`; …0021 `HOC_PHI …, zalo 0912345678` → FB trả lời, SHEET `new_phone` rồi SHEET `type: topic` `topics: Học phí` `escalated: Không` `question` có `[SĐT]`; …0022 `HARD_QUESTION` → SHEET topic `Khác`/`Có`; …0023 `Chào trường ạ` → không có SHEET; …0024 `GET_STARTED` có `--ad-title "Khai giảng"`, `QR:age:1`, `HOC_PHI …` → SHEET topic có `ad_title: Khai giảng`, `kid_age: 2-3 tuổi`, không có `fb_name`; `fail.sheet: 500` → FB vẫn trả lời, log `Topic row not written to Google Sheet: JSONDecodeError`; `/analytics/stats` có `top_topics_7d` Học phí 2, Khác 1 và `recent_escalations` 1 câu; hồ sơ không có `topics` (`/customers`, `--disk`, `data_after/`); app.log không có SĐT hay nội dung tin; netlog không có `BLOCKED`; down.
- Bảo trì: chạy lại `/create-verify-skill` hoặc giao `verifier` đối chiếu feature map với app mỗi tuần. Map lệch app thì sửa map trong PR riêng; map phát hiện lỗi sản phẩm thì báo lỗi, không sửa map để che.
