# Lead sang Google Sheet

Mỗi sự kiện lead, bot gửi tin vào nhóm Telegram đang dùng và cùng lúc ghi thêm một hàng vào Google Sheet:

| Sự kiện | Khi nào | Tiêu đề tin Telegram |
|---|---|---|
| `new_phone` | Phụ huynh để lại SĐT lần đầu | 📞 KHÁCH ĐỂ LẠI SĐT |
| `phone_changed` | Phụ huynh gửi SĐT khác số đã có (so theo chữ số, nên cùng số viết khác kiểu không tính) | 📞 KHÁCH ĐỔI SĐT |
| `visit_request` | Phụ huynh chốt hẹn tham quan/học thử mới hoặc khác lần trước | 📅 KHÁCH HẸN THAM QUAN/HỌC THỬ |

Bot POST JSON tới một web app Google Apps Script gắn với Sheet (`app/leads_sheet.py`). Sheet lỗi hoặc chưa cấu hình thì phụ huynh vẫn nhận trả lời và Telegram vẫn nhận tin; log Render chỉ ghi loại sự kiện và customer_id, không ghi SĐT hay URL web app.

## Cột

Bot gửi các khóa dưới đây (cùng `token`). Script ghi đúng thứ tự này, hàng 1 là tiêu đề. Cần thêm cột thì chỉ thêm vào cuối `COLUMNS`, để các hàng cũ không lệch cột.

| Khóa | Cột | Nội dung |
|---|---|---|
| `time` | Thời gian | Giờ Việt Nam lúc bot gửi, `YYYY-MM-DD HH:MM:SS` |
| `event` | Sự kiện | SĐT mới / Đổi SĐT / Hẹn tham quan/học thử |
| `fb_name` | Tên Facebook | Tên trên Facebook của phụ huynh |
| `customer_id` | Customer ID | ID Messenger của khách (PSID) |
| `phone` | SĐT | SĐT/Zalo hiện tại trong hồ sơ |
| `kid_name` | Tên bé | |
| `kid_age` | Tuổi bé | |
| `campus` | Cơ sở/hệ | Cơ sở quan tâm, hệ quan tâm |
| `area` | Khu vực | Khu vực, địa chỉ |
| `expected_start` | Dự kiến nhập học | |
| `visit_request` | Hẹn tham quan/học thử | |
| `ad_title` | Quảng cáo | Tên quảng cáo khách bấm vào (nếu có) |
| `stage` | Giai đoạn | Mới / Đã biết tuổi/cơ sở / Đã có SĐT / Đã hẹn tham quan/học thử |
| `last_message` | Tin cuối của phụ huynh | Tin nhắn vừa sinh ra sự kiện |

Sheet chứa dữ liệu cá nhân của phụ huynh và trẻ: chỉ chia sẻ cho người tư vấn.

## 1. Tạo Sheet và script

1. Bằng tài khoản Google của trường, tạo một Google Sheet mới (vd "Casa – Lead Messenger").
2. Trong Sheet: **Tiện ích mở rộng → Apps Script** (Extensions → Apps Script). Xóa code mẫu trong `Code.gs`, dán toàn bộ đoạn dưới, bấm Lưu.
3. Tạo token: chạy `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` và giữ chuỗi in ra.
4. Trong Apps Script: **Project Settings** (bánh răng) → **Script Properties** → **Add script property**: Property `LEADS_TOKEN`, Value là chuỗi vừa tạo → Save.

```javascript
// Nhận lead từ bot Messenger Casa (app/leads_sheet.py), ghi thêm một hàng vào tab Leads.
const SHEET_NAME = 'Leads';
// [khóa trong JSON bot gửi, tiêu đề cột]. Thứ tự này là thứ tự cột: chỉ thêm cột mới vào cuối.
const COLUMNS = [
  ['time', 'Thời gian'],
  ['event', 'Sự kiện'],
  ['fb_name', 'Tên Facebook'],
  ['customer_id', 'Customer ID'],
  ['phone', 'SĐT'],
  ['kid_name', 'Tên bé'],
  ['kid_age', 'Tuổi bé'],
  ['campus', 'Cơ sở/hệ'],
  ['area', 'Khu vực'],
  ['expected_start', 'Dự kiến nhập học'],
  ['visit_request', 'Hẹn tham quan/học thử'],
  ['ad_title', 'Quảng cáo'],
  ['stage', 'Giai đoạn'],
  ['last_message', 'Tin cuối của phụ huynh'],
];
const EVENT_LABELS = {
  new_phone: 'SĐT mới',
  phone_changed: 'Đổi SĐT',
  visit_request: 'Hẹn tham quan/học thử',
};
const TIME_FORMAT = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;

function doPost(e) {
  let data;
  try {
    data = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply(false);
  }
  const token = PropertiesService.getScriptProperties().getProperty('LEADS_TOKEN');
  if (!token || !data || data.token !== token) {
    return reply(false);
  }

  // Hai lead tới cùng lúc không ghi đè lên cùng một hàng.
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    return reply(false);
  }
  try {
    leadsSheet().appendRow(COLUMNS.map(([key]) => cell(key, data[key])));
    return reply(true);
  } finally {
    lock.releaseLock();
  }
}

function leadsSheet() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = book.getSheetByName(SHEET_NAME) || book.insertSheet(SHEET_NAME);
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(COLUMNS.map(([, title]) => title));
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function cell(key, value) {
  let text = value === undefined || value === null ? '' : String(value);
  if (key === 'event') {
    text = EVENT_LABELS[text] || text;
  }
  if (key === 'time' && TIME_FORMAT.test(text)) {
    return text; // để Sheets hiểu là ngày giờ
  }
  // Dấu ' ở đầu: Sheets giữ nguyên chuỗi (số 0 đầu SĐT, Customer ID 16 chữ số)
  // và không chạy công thức nếu nội dung phụ huynh gõ bắt đầu bằng = + - @. Dấu ' không hiện trong ô.
  return text ? "'" + text : '';
}

function reply(ok) {
  return ContentService.createTextOutput(JSON.stringify({ ok: ok })).setMimeType(ContentService.MimeType.JSON);
}
```

Script trả `{"ok":true}` khi đã ghi hàng, `{"ok":false}` khi body không phải JSON, sai token hoặc không lấy được khóa. Bot chỉ coi là thành công khi nhận đúng `{"ok":true}`.

## 2. Deploy web app

1. Trong Apps Script: **Deploy → New deployment** → bánh răng cạnh "Select type" → **Web app**.
2. Đặt:
   - Description: tùy ý (vd "lead bot v1").
   - **Execute as: Me** (script ghi Sheet bằng quyền của tài khoản trường).
   - **Who has access: Anyone** (bot gọi không đăng nhập Google; `LEADS_TOKEN` là lớp chặn).
3. **Deploy** → **Authorize access** → chọn tài khoản trường. Google báo ứng dụng chưa được xác minh thì bấm **Advanced → Go to … (unsafe)** → **Allow** (đây là script của chính mình).
4. Copy **Web app URL** (dạng `https://script.google.com/macros/s/…/exec`).

URL và token cùng nhau là đủ để ghi hàng vào Sheet: không dán vào chat, issue hay repo.

Sửa code sau này: **Deploy → Manage deployments** → chọn deployment đang dùng → biểu tượng bút chì (**Edit**) → Version: **New version** → **Deploy**. URL giữ nguyên. Đừng bấm **New deployment** (tạo URL mới, bot vẫn gọi URL cũ đang chạy code cũ). Chỉ bấm Lưu mà không tạo version mới thì web app vẫn chạy code cũ.

## 3. Đặt biến trên Render

Trong service của bot trên Render → **Environment**:

| Biến | Giá trị |
|---|---|
| `LEADS_SHEET_WEBHOOK_URL` | Web app URL ở bước 2 |
| `LEADS_SHEET_TOKEN` | Đúng chuỗi đã đặt cho `LEADS_TOKEN` ở bước 1 |

Lưu rồi deploy lại để bot nhận biến mới. Để trống `LEADS_SHEET_WEBHOOK_URL` thì bot chỉ gửi Telegram, không gọi Sheet.

Đổi token: đổi `LEADS_TOKEN` trong Script Properties và `LEADS_SHEET_TOKEN` trên Render cùng lúc (trong lúc lệch nhau, hàng mới bị từ chối; Telegram vẫn nhận tin).

## 4. Thử

Gửi một lead giả (thay `<LEADS_TOKEN>` và URL):

```bash
curl -sL -H 'Content-Type: application/json' \
  -d '{"token":"<LEADS_TOKEN>","event":"new_phone","time":"2026-01-01 08:00:00","fb_name":"Thử kết nối","customer_id":"0000000000000000","phone":"0900000000","last_message":"thử kết nối"}' \
  'https://script.google.com/macros/s/<DEPLOYMENT_ID>/exec'
```

- In ra `{"ok":true}` và tab **Leads** có hàng mới, SĐT giữ số 0 đầu → xong. Xóa hàng thử.
- Đổi token sai → `{"ok":false}`, không có hàng mới.
- In ra trang HTML: URL sai, hoặc "Who has access" chưa là Anyone, hoặc script lỗi (xem **Executions** trong Apps Script).

`-L` là bắt buộc: web app trả 302 sang `script.googleusercontent.com`, kết quả nằm ở đó (bot cũng theo redirect như vậy).

Khi bot chạy, Sheet không nhận hàng thì xem log Render: `Lead … rejected by Google Sheet web app` (script trả khác `{"ok":true}`, thường là sai token) hoặc `Lead … not written to Google Sheet: <loại lỗi>` (mạng, timeout 15 giây, trang HTML).
