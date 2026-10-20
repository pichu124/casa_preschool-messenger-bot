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
   - Subscribe to: `messages`, `messaging_postbacks`
5. Trong **App Settings** -> **Basic**: copy **App Secret** vao `FB_APP_SECRET`

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
- De trong (mac dinh): ho so khach chi luu tren dia cuc bo, khong day len GitHub. Tren Render dia khong ben, nen ho so mat sau moi lan deploy hoac restart.

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
| GET | `/dashboard` | Dashboard analytics | `?secret=` |
| GET | `/analytics/stats`, `/analytics/messages` | Du lieu analytics (JSON) | `?secret=` |
| POST | `/analytics/reset` | Xoa du lieu analytics | `?secret=` |
| GET | `/customers`, `/customers/export` | Ho so khach (JSON / Excel) | `?secret=` |
| GET | `/qa-database`, `/qa-learned` | Xem Q&A (tat ca / hoc tu admin) | `?secret=` |
| POST | `/reload-qa` | Tai lai Q&A database | `?secret=` |
| POST | `/import-excel?file_path=path` | Nhap Q&A tu Excel | `?secret=` |
| POST | `/test-chat` | Thu hoi thoai khong qua Facebook | `?secret=` |

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

### Reload sau khi chinh sua

```bash
curl -X POST "http://localhost:8000/reload-qa?secret=<TELEGRAM_WEBHOOK_SECRET>"
```

## Cau truc du an

```
app/
  main.py          - FastAPI app chinh
  config.py        - Cau hinh (doc tu .env)
  messenger.py     - Gui/nhan tin nhan Facebook Messenger
  ai_engine.py     - AI fallback chain (nhieu model)
  qa_database.py   - Quan ly co so du lieu Q&A
  escalation.py    - Chuyen cau hoi cho admin
data/
  qa_database.json - Du lieu Q&A
```
