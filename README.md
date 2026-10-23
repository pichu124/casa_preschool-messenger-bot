# Preschool Messenger Auto-Response Bot

He thong tu dong tra loi cau hoi khach hang tren Facebook Messenger cho truong mam non.

## Tinh nang

- Tu dong tra loi cau hoi phu huynh dua tren co so du lieu Q&A
- Ho tro nhieu AI model voi co che fallback (OpenAI -> Groq -> Gemini -> Mistral -> DeepSeek)
- Tu dong chuyen cau hoi kho cho admin khi AI khong tra loi duoc
- Luu lich su hoi thoai de tra loi theo ngu canh
- Ho tro nhap Q&A tu file Excel
- Hot-reload Q&A khong can khoi dong lai server

## Cai dat

### 1. Cai dat Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Tao file .env

```bash
cp .env.example .env
```

Sau do dien cac gia tri vao file `.env`.

### 3. Thiet lap Facebook Developer App

1. Truy cap https://developers.facebook.com/ va tao tai khoan Developer
2. Tao App moi: **Create App** -> chon **Business** -> dat ten
3. Trong Dashboard, them san pham **Messenger**
4. Vao **Messenger Settings**:
   - Muc **Access Tokens**: chon Facebook Page cua ban va **Generate Token** -> copy vao `FB_PAGE_ACCESS_TOKEN`
   - Muc **Webhooks**: click **Add Callback URL**
     - Callback URL: `https://your-domain.com/webhook` (hoac ngrok URL)
     - Verify Token: nhap gia tri giong `FB_VERIFY_TOKEN` trong file .env
   - Subscribe to: `messages`, `messaging_postbacks` (nut Bat dau, cau hoi goi y), `messaging_referrals` (khach mo chat tu quang cao hoac link m.me khi da tung nhan tin), `message_echoes` (tin nhan vien tu nhan tay trong hop thu Page; bat buoc truoc khi bat tin nhac lai, muc 10)
5. Trong **App Settings** -> **Basic**: copy **App Secret** vao `FB_APP_SECRET`
6. Dang ky nut Bat dau (Get Started) va 4 cau hoi goi y (`ICE_BREAKERS` trong `app/messenger.py`) voi Page: chay mot lan sau khi deploy, va chay lai moi khi doi cac cau hoi do:
   ```bash
   curl -X POST "https://your-domain.com/setup-messenger-profile?secret=<TELEGRAM_WEBHOOK_SECRET>"
   ```
   Ket qua `{"result": "success"}` la xong; co `error` thi xem `FB_PAGE_ACCESS_TOKEN`.

### 4. Thiet lap Admin Escalation

De nhan cau hoi escalate, ban can:
1. Co mot Facebook Page rieng cho admin (hoac dung Page hien tai)
2. Tao Page Access Token cho Page admin -> `FB_ADMIN_PAGE_ACCESS_TOKEN`
3. Lay PSID cua admin (gui tin nhan cho Page admin, PSID se hien trong webhook log) -> `FB_ADMIN_RECIPIENT_ID`

### 5. Thiet lap AI Model

Dien API key cua cac model ban muon su dung vao file .env.
Chi can it nhat 1 model co API key la duoc.

- OpenAI: https://platform.openai.com/api-keys
- Groq: https://console.groq.com/keys
- Gemini: https://aistudio.google.com/apikey
- Mistral: https://console.mistral.ai/api-keys
- DeepSeek: https://platform.deepseek.com/api_keys

Thu tu fallback cau hinh trong `AI_MODEL_ORDER`.

#### Model AI (bien moi truong)

Ten model cua tung nha cung cap dat qua bien moi truong; khong dat bien, hoac dat gia tri rong/chi co khoang trang, thi dung mac dinh:

| Bien | Provider trong `AI_MODEL_ORDER` | Mac dinh |
|---|---|---|
| `OPENAI_MODEL` | `openai` | `gpt-4o-mini` |
| `GROQ_MODEL` | `groq` | `openai/gpt-oss-120b` |
| `GROQ_SECOND_MODEL` | `groq_llama` (ten giu nguyen de khong pha cau hinh cu) | `qwen/qwen3.8-27b` |
| `MISTRAL_MODEL` | `mistral` | `mistral-small-latest` |
| `DEEPSEEK_MODEL` | `deepseek` | `deepseek-flash` |
| `GEMINI_MODEL` | `gemini` | `gemini-3.5-flash` |

Cac mac dinh nay thay model da bi nha cung cap ngung (Groq `deepseek-r1-distill-llama-70b`, `llama-3.3-70b-versatile`; DeepSeek `deepseek-chat`; Gemini `gemini-2.0-flash`). Chung lay tu tai lieu nha cung cap (2026-10), **CHUA duoc xac minh bang API key**; rieng `gemini-3.5-flash` con chua chac la ID dung. Truoc khi dua len Render, kiem tung model co trong danh sach cua nha cung cap:

```bash
curl -s https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"
curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"
curl -s https://api.mistral.ai/v1/models -H "Authorization: Bearer $MISTRAL_API_KEY"
curl -s https://api.deepseek.com/models -H "Authorization: Bearer $DEEPSEEK_API_KEY"
curl -s https://generativelanguage.googleapis.com/v1beta/models -H "x-goog-api-key: $GEMINI_API_KEY"
```

Roi cham hoi thoai voi model that: `.venv/bin/python scripts/eval_chat.py` (exit 0 = dat; 2 = chua co API key hoac moi model deu loi). Model sai ten chi hien trong log (`Model ... failed`) va bot chuyen sang model tiep theo trong `AI_MODEL_ORDER`.

### 6. Secret cho endpoint admin va Telegram webhook

- `TELEGRAM_WEBHOOK_SECRET`: chuoi ngau nhien, chi dung ky tu `A-Z a-z 0-9 _ -` (Telegram `secret_token` chi nhan cac ky tu nay, 1-256 ky tu). Tao bang `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
  - La gia tri `?secret=` cua moi endpoint admin, dong thoi la `secret_token` Telegram gui kem trong header `X-Telegram-Bot-Api-Secret-Token` toi `/telegram-webhook`.
  - De trong thi moi endpoint admin va `/telegram-webhook` tra 403 (log khoi dong co WARNING).
  - Sau khi dat hoac doi secret phai dang ky lai webhook Telegram, neu khong Telegram van gui secret cu va bi 403:
    ```bash
    curl -X POST "https://your-domain.com/setup-telegram-webhook?secret=<TELEGRAM_WEBHOOK_SECRET>"
    ```
- `FB_APP_SECRET`: de trong thi `/webhook` nhan request ma khong kiem chu ky Facebook (log khoi dong co WARNING). Nen dat.

### 7. Luu ho so khach (`data/customers.json`)

- `CUSTOMERS_GITHUB_REPO` (`owner/ten-repo`): repo bot dung de day va keo `data/customers.json` (nhanh `main`) bang `GITHUB_TOKEN`. File nay chua du lieu ca nhan cua phu huynh va tre: chi tro toi repo PRIVATE, khong bao gio tro toi repo code public nay.
  - `GITHUB_TOKEN` phai co quyen ghi Contents tren repo do. Nen tao repo kem README de co san nhanh `main`.
  - Luc khoi dong, repo do la nguon su that: bot keo `data/customers.json` tu repo truoc va ghi de ban tren dia. Repo chua co file (404) thi bot dung ban tren dia (khong co thi bat dau rong) va day len o tin nhan dau tien. Keo loi (mang, timeout, 5xx, 401/403, JSON hong) thi bot van tra loi voi ban tren dia nhung KHONG day len GitHub cho toi lan khoi dong sau (log ERROR), de khong de ban thieu len repo private.
  - `data/customers.json` hien con duoc track trong repo code public nay (va nam trong image deploy). Sau khi repo private da co ban day du, nguoi quan tri nen go file khoi repo public (vd `git rm --cached data/customers.json` va them vao `.gitignore`); lich su git cu van con file nay.
- De trong (mac dinh): ho so khach chi luu tren dia cuc bo, khong day len GitHub. Tren Render dia khong ben, nen ho so mat sau moi lan deploy hoac restart.

### 8. Lead sang nhom Telegram va Google Sheet

Phu huynh de lai SDT lan dau, doi SDT, hoac chot hen tham quan/hoc thu: bot gui tin vao nhom Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) va cung luc ghi mot hang vao Google Sheet qua web app Apps Script. Cach tao Sheet, script va deploy: [docs/google-sheet-leads.md](docs/google-sheet-leads.md).

- `LEADS_SHEET_WEBHOOK_URL`: Web app URL cua script (`https://script.google.com/macros/s/.../exec`). De trong (mac dinh) thi chi gui Telegram, khong goi Sheet.
- `LEADS_SHEET_TOKEN`: chuoi ngau nhien, phai trung Script Property `LEADS_TOKEN` cua script. Bot gui no trong body JSON; sai token thi script tu choi ghi.
- URL va token cung nhau du de ghi hang vao Sheet (co du lieu ca nhan cua phu huynh): chi dat tren Render, khong dua vao chat hay repo.

### 9. Anh tinh (`static/`)

File trong thu muc `static/` duoc phuc vu CONG KHAI, khong can secret, tai `{PUBLIC_BASE_URL}/static/<file>` (Facebook tai anh tu URL nay, nen `PUBLIC_BASE_URL` phai la URL cong khai cua app). Chi dat anh duoc phep cong khai (vd thuc don mau), khong dat du lieu ca nhan.

De bot gui anh kem cau tra loi, them duong dan vao cap Q&A trong `data/qa_database.json`:

```json
{"category": "Ăn uống", "questions": ["Cho em xem thực đơn mẫu"], "answer": "...", "images": ["static/thuc-don-mau.jpg"]}
```

### 10. Tin nhac lai khach (follow-up, mac dinh TAT)

Moi gio 2 lan, phut 17 va phut 47, GitHub Actions (`.github/workflows/followup.yml`) goi `POST /followup/run` (GitHub Actions hay chay tre hoac bo luot theo lich, nen chay 2 lan cho chac; moi phu huynh van chi nhan 1 tin vi bot ghi `followup_sent_at` va khong cho 2 lan chay chong nhau). Bot gui MOT tin co dinh (khong goi AI, `app/followup.py`) cho phu huynh dang tu van do dang, NGAY TRUOC khi het cua so 24 gio cua Messenger.

Vi sao: Messenger chi cho Page gui tin thuong trong 24 gio ke tu tin cuoi cua phu huynh; sau do Graph API tu choi, va gan tag `HUMAN_AGENT` cho tin tu dong de vuot qua la vi pham chinh sach Messenger. Nen bot doi lau nhat co the roi moi nhac:

- Han chot = tin cuoi cua phu huynh + 23 gio (chua 1 gio truoc khi cua so dong).
- Gui muon nhat = han chot khi han chot tu 10h00 den 20h59 (2 gio truoc han chot khong som hon 8h00); ngoai ra lui ve 20h59 gan nhat truoc han chot. Vi du: tin cuoi 11h00 (han chot 10h00 hom sau) thi gui 8h00 den 10h00 sang hom sau; tin cuoi 20h50 thi 17h50 den 19h50 hom sau; tin cuoi 10h00 (han chot 9h00 hom sau) thi 18h59 den 20h59 cung ngay; tin cuoi 23h00 (han chot 22h00 hom sau) thi 18h59 den 20h59 hom sau; tin cuoi 3h00 sang (han chot 2h00 hom sau) thi 18h59 den 20h59 cung ngay.
- Bot nhac trong 2 gio truoc thoi diem gui muon nhat, va ca 2 gio do luon nam tron trong khung gui (8h00 den 20h59 gio Viet Nam), nen moi phu huynh deu co it nhat 3 lan chay (phut 17 va 47), lan dau con it nhat 1 gio truoc thoi diem gui muon nhat.

Bot chi nhac khi DU tat ca dieu kien:

- Dang trong khoang gui o tren, va tin cuoi cua phu huynh cach day it nhat 3 gio.
- Tin cuoi trong hoi thoai la cua bot, va khong phai cau chuyen tu van vien (tu van vien dang lo).
- Chua co SDT, chua hen tham quan/hoc thu.
- Chua nhac lan nao ke tu tin cuoi cua phu huynh (`followup_sent_at` trong ho so khach).
- Nhan vien chua tu nhan tay cho phu huynh trong hop thu Page ke tu tin cuoi cua phu huynh (`staff_replied_at` trong ho so khach). Bot gui moi tin kem `metadata` `casa-bot`; Facebook gui lai (echo) moi tin Page gui di, echo khong co `casa-bot` la tin nhan vien nhan tay. Can dang ky truong webhook `message_echoes` (muc 3), thieu thi bot khong biet nhan vien da nhan va van nhac.
  - Tin tu dong cua Page trong Meta Business Suite (Instant Reply, Away message) cung tao echo khong co `casa-bot`, nen bi tinh la nhan vien da nhan va khach do se khong bao gio duoc nhac. Tat cac tin tu dong nay truoc khi bat tin nhac lai.
- Gio Viet Nam tu 8h00 den truoc 21h00.

Mau tin (nguyen van cua truong, theo nhan cua truong; `docs/quyet-dinh-noi-dung.md` muc 3), theo thu tu: da tu van tuong doi du (biet tuoi be va co so quan tam, bot da noi du cac nhom thong tin) thi mau 3, moi tham quan; chua biet tuoi be thi mau 1, hoi tuoi; con lai thi mau 2, xin SDT/Zalo, ke ca khi phu huynh da tu choi de lai so. Graph API tu choi (ngoai cua so 24 gio, khach chan Page) thi bo qua khach do. Tin da gui duoc ghi vao lich su hoi thoai, khong tang so tin nhan cua khach. Gio trong lich su la gio may chu khong co mui gio, duoc coi la UTC (Render chay UTC).

Cach bat (truoc het dang ky truong webhook `message_echoes`, muc 3; sau do can ca hai noi):

1. Render: dat bien moi truong `FOLLOWUP_ENABLED=true`. Chua dat thi `/followup/run` chi dem so khach du dieu kien, khong gui gi.
2. GitHub repo -> Settings -> Secrets and variables -> Actions:
   - Variables: `FOLLOWUP_ENABLED` = `true` (chua dat thi workflow khong chay).
   - Secrets: `BOT_BASE_URL` (vd `https://casa-preschool-messenger-bot.onrender.com`, khong co `/` cuoi) va `BOT_ADMIN_SECRET` (= `TELEGRAM_WEBHOOK_SECRET` tren Render).

Repo nay public nen log Actions cung public: workflow chi in ma HTTP, khong in noi dung tra ve. Muon xem truoc ai se duoc nhac ma khong gui:

```bash
curl -X POST "https://your-domain.com/followup/run?secret=<TELEGRAM_WEBHOOK_SECRET>&dry_run=1&verbose=1"
```

Ket qua `{"due": n, "sent": m, "enabled": true|false}`; `verbose=1` them danh sach mau tin + 4 ky tu cuoi ID khach (khong co ten, SDT, noi dung tin).

### 11. Dashboard: pheu tu van

`/dashboard?secret=` co muc "Pheu tu van": tong khach, co tuoi be, co co so quan tam, co SDT, da hen tham quan/hoc thu, tu quang cao, va so khach theo giai doan (Moi -> Da biet tuoi/co so -> Da co SDT -> Da hen). Pheu tinh tu ho so khach (`data/customers.json`), khong tu `analytics.jsonl`. Cac o tin nhan, nguoi dung, escalation va ti le chuyen tu van vien tinh tu `analytics.jsonl`, file nay mat moi lan deploy, nen chi phan anh tu lan deploy gan nhat. `/customers/export` co them cot Khu vuc, Du kien nhap hoc, Hen tham quan/hoc thu, Nguon (tieu de quang cao), Giai doan, Da tu choi SDT.

## Chay ung dung

### Development (local)

```bash
# Chay server
uvicorn app.main:app --reload --port 8000

# Mo tunnel de Facebook gui webhook (cai ngrok truoc)
ngrok http 8000
```

Copy URL ngrok (vd: `https://abc123.ngrok.io`) vao Facebook Webhook Callback URL.

### Production

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API Endpoints

`?secret=` la gia tri `TELEGRAM_WEBHOOK_SECRET` (xem muc 6). Chua dat bien nay thi cac endpoint can `?secret=` deu tra 403.

| Method | Path | Mo ta | Xac thuc |
|--------|------|-------|----------|
| GET | `/` | Health check | khong |
| GET | `/webhook` | Facebook webhook verification | `hub.verify_token` = `FB_VERIFY_TOKEN` |
| POST | `/webhook` | Nhan tin nhan tu Messenger | chu ky `X-Hub-Signature-256` (chi khi dat `FB_APP_SECRET`) |
| POST | `/telegram-webhook` | Nhan admin reply tu Telegram | header `X-Telegram-Bot-Api-Secret-Token` |
| POST | `/setup-telegram-webhook` | Dang ky webhook Telegram voi secret hien tai | `?secret=` |
| POST | `/setup-messenger-profile` | Dang ky nut Bat dau va cau hoi goi y voi Page | `?secret=` |
| GET | `/static/<file>` | Anh tinh trong `static/` | khong (cong khai) |
| GET | `/dashboard` | Dashboard analytics | `?secret=` |
| GET | `/analytics/stats`, `/analytics/messages` | Du lieu analytics (JSON) | `?secret=` |
| POST | `/analytics/reset` | Xoa du lieu analytics | `?secret=` |
| GET | `/customers`, `/customers/export` | Ho so khach (JSON / Excel) | `?secret=` |
| POST | `/customers/{customer_id}/reset` | Xoa ho so cua MOT khach (ho so, lich su, tom tat, the lead, escalation dang cho); tra `{"status":"reset","existed":true\|false}` | `?secret=` |
| GET | `/qa-database`, `/qa-learned` | Xem Q&A (tat ca / hoc tu admin) | `?secret=` |
| POST | `/reload-qa` | Tai lai Q&A database | `?secret=` |
| POST | `/import-excel?file_path=path` | Nhap Q&A tu Excel | `?secret=` |
| POST | `/test-chat` | Thu hoi thoai khong qua Facebook | `?secret=` |
| POST | `/followup/run` | Gui tin nhac lai khach (muc 10); `dry_run=1` chi dem, `verbose=1` them danh sach | `?secret=` |

### Thu lai nhu phu huynh moi

Tai khoan Facebook da nhan thu voi bot thi bot nho ho so va lich su (khach cu). De thu lai tu dau voi cung tai khoan: lay PSID cua tai khoan (khoa trong `/customers?secret=`, hoac dong `🆔 ID` tren tin Telegram), goi reset, roi nhan lai tren Messenger; tin do duoc coi la tin dau tien. Moi lan chi xoa mot PSID; PSID khong co ho so thi tra `"existed":false`. Ban `data/customers.json` sau khi xoa duoc day len `CUSTOMERS_GITHUB_REPO` (muc 7) nhu moi lan ghi. Tin Telegram, dong Google Sheet va `analytics.jsonl` cu van giu nguyen. Goi khi tai khoan do khong dang nhan tin.

```bash
curl -X POST "https://casa-preschool-messenger-bot.onrender.com/customers/<PSID>/reset?secret=<TELEGRAM_WEBHOOK_SECRET>"
```

PowerShell (Windows):

```powershell
(Invoke-WebRequest -Method Post -UseBasicParsing -Uri "https://casa-preschool-messenger-bot.onrender.com/customers/<PSID>/reset?secret=<TELEGRAM_WEBHOOK_SECRET>").Content
```

## Quan ly Q&A Database

### Format JSON (`data/qa_database.json`)

```json
{
  "qa_pairs": [
    {
      "category": "ten_danh_muc",
      "questions": ["Cau hoi 1?", "Cau hoi 2?"],
      "answer": "Cau tra loi...",
      "keywords": ["tu khoa 1", "tu khoa 2"]
    }
  ]
}
```

### Nhap tu Excel

File Excel can co cac cot: `category | question | answer | keywords`

```bash
curl -X POST "http://localhost:8000/import-excel?file_path=data/qa_database_sample.xlsx&secret=<TELEGRAM_WEBHOOK_SECRET>"
```

### Bot hoc tu admin (Telegram)

Tu van vien reply tin "CAN TRO GIUP" tren Telegram thi bot them cap Q&A moi vao `data/qa_database.json` va day len nhanh `main` voi commit `[skip deploy]` (Render khong deploy lai); xem cac cap da hoc o `/qa-learned`. Vi dia tren Render chi co ban cua lan deploy gan nhat, moi lan khoi dong (va moi lan `/reload-qa`) bot co `GITHUB_TOKEN` thi keo `data/qa_database.json` moi nhat tu `main` va ghi de ban tren dia, nen restart khong lam mat cac cap da hoc. Keo loi (mang, timeout, 404, 401/403, 5xx, JSON hong, `qa_pairs` thieu hoac rong) thi bot dung ban tren dia va KHONG day Q&A len GitHub cho toi lan nap thanh cong sau (log ERROR), de ban tren dia khong de mat cac cap da hoc tren `main`.

### Reload sau khi chinh sua

```bash
curl -X POST "http://localhost:8000/reload-qa?secret=<TELEGRAM_WEBHOOK_SECRET>"
```

Co `GITHUB_TOKEN` thi reload lay ban tren `main` chu khong lay file vua sua tren dia: sua Q&A bang commit len `main`.

## Cau truc du an

```
app/
  main.py          - FastAPI app chinh
  config.py        - Cau hinh (doc tu .env)
  messenger.py     - Gui/nhan tin nhan Facebook Messenger
  ai_engine.py     - AI fallback chain (nhieu model)
  qa_database.py   - Quan ly co so du lieu Q&A
  escalation.py    - Chuyen cau hoi cho admin
  followup.py      - Tin nhac lai khach trong cua so 24 gio
data/
  qa_database.json - Du lieu Q&A
static/            - Anh cong khai cho Q&A (vd thuc don mau)
```
