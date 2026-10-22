# Lead sang Google Sheet

Mỗi sự kiện lead, bot báo vào nhóm Telegram đang dùng và cùng lúc ghi vào Google Sheet. Mỗi phụ huynh (Customer ID) chỉ có **một thẻ** Telegram và **một hàng** Sheet:

- Telegram: lead đầu tiên của phụ huynh là thẻ đầy đủ (tiêu đề theo bảng dưới). Thay đổi sau đó là tin ngắn **trả lời vào thẻ đó**, chỉ nêu phần đổi, vd `🔄 Lan Thử: Hẹn: tham quan buổi sáng → tham quan sáng mai`, `🔄 Lan Thử: SĐT: 0900000401 → 0911000402`, `🔄 Lan Thử: để lại SĐT 0900000401`, kèm giờ Việt Nam. Thẻ bị xoá khỏi nhóm thì lần sau bot gửi thẻ đầy đủ mới và các thay đổi sau trả lời vào thẻ mới. Reply thẻ hay tin ngắn không gửi gì tới phụ huynh.
- Sheet: hàng đầu tiên thêm khi có lead đầu tiên; mỗi sự kiện sau cập nhật đúng hàng đó (mọi cột theo dữ liệu mới, "Sự kiện" là sự kiện mới nhất), giữ "Lần đầu liên hệ".

| Sự kiện | Khi nào | Tiêu đề thẻ Telegram (khi là lead đầu tiên) |

|---|---|---|
| `new_phone` | Phụ huynh để lại SĐT lần đầu | 📞 KHÁCH ĐỂ LẠI SĐT |
| `phone_changed` | Phụ huynh gửi SĐT khác số đã có (so theo chữ số, nên cùng số viết khác kiểu không tính) | 📞 KHÁCH ĐỔI SĐT |
| `visit_request` | Phụ huynh chốt hẹn tham quan/học thử mới hoặc khác lần trước | 📅 KHÁCH HẸN THAM QUAN/HỌC THỬ |

Bot POST JSON tới một web app Google Apps Script gắn với Sheet (`app/leads_sheet.py`). Sheet lỗi hoặc chưa cấu hình thì phụ huynh vẫn nhận trả lời và Telegram vẫn nhận tin; log Render chỉ ghi loại sự kiện và customer_id, không ghi SĐT hay URL web app.

## Cột

Bot gửi các khóa dưới đây (cùng `token`), trừ hai cột cuối do script tự điền từ `time`. Script ghi đúng thứ tự này, hàng 1 là tiêu đề, tìm hàng của phụ huynh theo `customer_id`. Cần thêm cột thì chỉ thêm vào cuối `COLUMNS`, để các hàng cũ không lệch cột.

| Khóa | Cột | Nội dung |
|---|---|---|
| `time` | Thời gian | Giờ Việt Nam lúc bot gửi sự kiện mới nhất, `YYYY-MM-DD HH:MM:SS` |
| `event` | Sự kiện | Sự kiện mới nhất: SĐT mới / Đổi SĐT / Hẹn tham quan/học thử |
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
| `first_contact` | Lần đầu liên hệ | Script điền: giờ Việt Nam của lead đầu tiên, không đổi khi hàng được cập nhật |
| `updated_at` | Cập nhật lúc | Script điền: giờ Việt Nam của lần cập nhật này |

Sheet chứa dữ liệu cá nhân của phụ huynh và trẻ: chỉ chia sẻ cho người tư vấn.

## 1. Tạo Sheet và script

1. Bằng tài khoản Google của trường, tạo một Google Sheet mới (vd "Casa – Lead Messenger").
2. Trong Sheet: **Tiện ích mở rộng → Apps Script** (Extensions → Apps Script). Xóa code mẫu trong `Code.gs`, dán toàn bộ đoạn dưới, bấm Lưu.
3. Tạo token: chạy `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` và giữ chuỗi in ra.
4. Trong Apps Script: **Project Settings** (bánh răng) → **Script Properties** → **Add script property**: Property `LEADS_TOKEN`, Value là chuỗi vừa tạo → Save.

```javascript
// Nhận lead từ bot Messenger Casa (app/leads_sheet.py) vào tab Leads: mỗi phụ huynh (Customer ID) một hàng.
const SHEET_NAME = 'Leads';
// [khóa, tiêu đề cột]. Thứ tự này là thứ tự cột: chỉ thêm cột mới vào cuối.
// Hai cột cuối script tự điền từ `time` của bot, các cột khác là khóa trong JSON bot gửi.
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
  ['first_contact', 'Lần đầu liên hệ'],
  ['updated_at', 'Cập nhật lúc'],
];
const EVENT_LABELS = {
  new_phone: 'SĐT mới',
  phone_changed: 'Đổi SĐT',
  visit_request: 'Hẹn tham quan/học thử',
};
const TIME_KEYS = ['time', 'first_contact', 'updated_at'];
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
  data.first_contact = data.time;
  data.updated_at = data.time;

  // Hai lead tới cùng lúc không ghi đè lên nhau, không tạo hai hàng cho cùng một phụ huynh.
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    return reply(false);
  }
  try {
    const sheet = leadsSheet();
    const values = COLUMNS.map(([key]) => cell(key, data[key]));
    const row = findRow(sheet, String(data.customer_id || ''));
    if (row) {
      // Cập nhật hàng của phụ huynh, giữ "Lần đầu liên hệ". Hàng ghi trước khi có cột này: lấy "Thời gian" cũ.
      const range = sheet.getRange(row, 1, 1, COLUMNS.length);
      const old = range.getValues()[0];
      const first = column('first_contact') - 1;
      values[first] = old[first] || old[column('time') - 1] || values[first];
      range.setValues([values]);
    } else {
      sheet.appendRow(values);
    }
    return reply(true);
  } catch (err) {
    if (err instanceof HeaderTaken) {
      return reply(false, err.message);
    }
    throw err;
  } finally {
    lock.releaseLock();
  }
}

class HeaderTaken extends Error {}

function leadsSheet() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = book.getSheetByName(SHEET_NAME) || book.insertSheet(SHEET_NAME);
  if (sheet.getMaxColumns() < COLUMNS.length) {
    sheet.insertColumnsAfter(sheet.getMaxColumns(), COLUMNS.length - sheet.getMaxColumns());
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(COLUMNS.map(([, title]) => title));
    sheet.setFrozenRows(1);
    return sheet;
  }
  // Sheet tạo bằng script cũ: thêm tiêu đề các cột mới ở cuối, hàng cũ giữ nguyên vị trí.
  // Ô tiêu đề của cột mới đã có chữ khác (cột người tư vấn tự thêm): không ghi gì, để không ghi đè dữ liệu của cột đó.
  const header = sheet.getRange(1, 1, 1, COLUMNS.length).getValues()[0];
  const added = column('first_contact') - 1;
  const taken = COLUMNS.findIndex(([, title], i) => i >= added && header[i] !== '' && header[i] !== title);
  if (taken >= 0) {
    throw new HeaderTaken(
      'Ô ' + String.fromCharCode(65 + taken) + '1 là "' + header[taken] + '", script cần "' + COLUMNS[taken][1] +
        '": chuyển cột tự thêm ra sau cột P (docs/google-sheet-leads.md, mục 5)'
    );
  }
  COLUMNS.forEach(([, title], i) => {
    if (header[i] === '') {
      sheet.getRange(1, i + 1).setValue(title);
    }
  });
  return sheet;
}

// Số hàng (từ 2) của phụ huynh `customerId`, 0 khi chưa có. Sheet cũ có nhiều hàng một phụ huynh: lấy hàng dưới cùng.
function findRow(sheet, customerId) {
  const last = sheet.getLastRow();
  if (!customerId || last < 2) {
    return 0;
  }
  const ids = sheet.getRange(2, column('customer_id'), last - 1, 1).getValues();
  for (let i = ids.length - 1; i >= 0; i--) {
    // Ô ghi là '9000… (xem cell()); Sheets trả giá trị không có dấu '.
    if (String(ids[i][0]).replace(/^'/, '') === customerId) {
      return i + 2;
    }
  }
  return 0;
}

function column(key) {
  return COLUMNS.findIndex(([k]) => k === key) + 1;
}

function cell(key, value) {
  let text = value === undefined || value === null ? '' : String(value);
  if (key === 'event') {
    text = EVENT_LABELS[text] || text;
  }
  if (TIME_KEYS.includes(key) && TIME_FORMAT.test(text)) {
    return text; // để Sheets hiểu là ngày giờ
  }
  // Dấu ' ở đầu: Sheets giữ nguyên chuỗi (số 0 đầu SĐT, Customer ID 16 chữ số)
  // và không chạy công thức nếu nội dung phụ huynh gõ bắt đầu bằng = + - @. Dấu ' không hiện trong ô.
  return text ? "'" + text : '';
}

function reply(ok, error) {
  const body = error ? { ok: ok, error: error } : { ok: ok };
  return ContentService.createTextOutput(JSON.stringify(body)).setMimeType(ContentService.MimeType.JSON);
}
```

Script trả `{"ok":true}` khi đã thêm hoặc cập nhật hàng, `{"ok":false}` khi body không phải JSON, sai token hoặc không lấy được khóa, `{"ok":false,"error":"…"}` (không ghi gì) khi ô tiêu đề O1 hoặc P1 đã có chữ khác "Lần đầu liên hệ"/"Cập nhật lúc" (vd cột người tư vấn tự thêm). Bot chỉ coi là thành công khi nhận đúng `{"ok":true}`.

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

- In ra `{"ok":true}` và tab **Leads** có hàng mới, SĐT giữ số 0 đầu, "Lần đầu liên hệ" và "Cập nhật lúc" là `2026-01-01 08:00:00`.
- Gửi lại lệnh trên với `"event":"visit_request","time":"2026-01-01 08:05:00","visit_request":"tham quan buổi sáng"` (cùng `customer_id`) → vẫn **một** hàng: "Sự kiện" là Hẹn tham quan/học thử, "Cập nhật lúc" 08:05, "Lần đầu liên hệ" vẫn 08:00 → xong. Xóa hàng thử.
- Đổi token sai → `{"ok":false}`, không có hàng mới.
- In ra trang HTML: URL sai, hoặc "Who has access" chưa là Anyone, hoặc script lỗi (xem **Executions** trong Apps Script).

`-L` là bắt buộc: web app trả 302 sang `script.googleusercontent.com`, kết quả nằm ở đó (bot cũng theo redirect như vậy).

Khi bot chạy, Sheet không nhận hàng thì xem log Render: `Lead … rejected by Google Sheet web app` (script trả khác `{"ok":true}`, thường là sai token) hoặc `Lead … not written to Google Sheet: <loại lỗi>` (mạng, timeout 15 giây, trang HTML).

## 5. Cập nhật Sheet đang chạy (mỗi phụ huynh một hàng, 2026-10-22)

Sheet tạo theo bản cũ của trang này ghi thêm một hàng mỗi sự kiện. Đổi sang bản mỗi phụ huynh một hàng (người vận hành làm, không cần sửa gì trên Render):

1. Trong tab **Leads**, kiểm tra cột O và P đang trống (script mới ghi "Lần đầu liên hệ" và "Cập nhật lúc" vào đó). Nếu đã tự thêm cột ở đó (vd "Đã gọi", "Ghi chú") thì chèn 2 cột trống trước cột tự thêm, hoặc chuyển cột tự thêm ra sau cột P; không thì script từ chối mọi lead (`{"ok":false,"error":"…"}`, log Render `rejected by Google Sheet web app`) cho tới khi O và P trống.
2. Mở Sheet → **Tiện ích mở rộng → Apps Script**. Trong `Code.gs`, xoá hết code cũ, dán toàn bộ script ở bước 1 → **Lưu**.
3. **Deploy → Manage deployments** → chọn deployment đang dùng → biểu tượng bút chì (**Edit**) → Version: **New version** → **Deploy**. URL web app giữ nguyên, `LEADS_TOKEN` giữ nguyên. Đừng bấm **New deployment**.
4. Xoá tay 3 hàng thử cũ trong tab **Leads**.
5. Thử như bước 4 (hai lệnh curl, cùng `customer_id`) → một hàng, rồi xoá hàng thử.

Lead đầu tiên sau khi cập nhật, script tự thêm tiêu đề "Lần đầu liên hệ" và "Cập nhật lúc" vào hai cột cuối; các hàng cũ không lệch cột. Phụ huynh đã có nhiều hàng từ trước thì script cập nhật hàng dưới cùng của Customer ID đó (lấy "Thời gian" cũ của hàng làm "Lần đầu liên hệ"); các hàng trên của cùng Customer ID có thể xoá tay nếu muốn.
