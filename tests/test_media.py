"""Ảnh từ thư mục Google Drive của trường (app/media.py): Apps Script liệt kê file, bot phân loại theo thư mục,
tải và thu nhỏ ảnh, giữ danh mục; lệnh /capnhatanh trong nhóm admin và GET /media. Apps Script, Drive và Telegram
là fake ở tầng httpx."""

import asyncio
import json
import logging
import socket
import time
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main
from app import media
from app.config import settings
from app.leads_sheet import VN_TZ

SHEET_URL = "https://script.google.com/macros/s/MEDIA-TEST/exec"
SHEET_TOKEN = "sheet-token-media-test"
WEBHOOK_SECRET = "tg-secret_media"
CHAT_ID = "-1009876543210"
BASE_URL = "https://bot.example.test"

QT, SN = "HỆ QUỐC TẾ", "HỆ SONG NGỮ"
CL, MD, KM = "CƠ SỞ CHÙA LÁNG", "CƠ SỞ MỸ ĐÌNH", "CƠ SỞ KIM MÃ"
TKB, CSVC = "THỜI KHÓA BIỂU", "ẢNH CƠ SỞ VẬT CHẤT"
OCT = "2026-10-01T02:00:00.000Z"


def drive_file(file_id, name, *path, modified=OCT):
    mime = "image/png" if name.endswith(".png") else "image/jpeg"
    return {"id": file_id, "name": name, "mimeType": mime, "modified": modified, "path": list(path)}


# Đúng cây thư mục "Ảnh cho Chatbot" của trường (tên ảnh cơ sở vật chất là ví dụ, trường chưa đặt tên riêng).
DRIVE_TREE = [
    drive_file("qt-fee-10", "7.png", QT, "HỌC PHÍ THÁNG 10"),
    drive_file("qt-menu", "Thực đơn mẫu.jpg", QT, "THỰC ĐƠN"),
    drive_file("cl-tkb-15-36", "TKB 15 tháng - 3 tuổi.jpg", QT, CL, TKB),
    drive_file("cl-tkb-36-60", "TKB 3-5 tuổi.jpg", QT, CL, TKB),
    drive_file("cl-tkb-60-72", "TKB 5-6 tuổi.jpg", QT, CL, TKB),
    *[drive_file(f"cl-csvc-{i}", f"IMG_{i:02}.jpg", QT, CL, CSVC) for i in range(1, 7)],
    drive_file("md-tkb-15-36", "TKB 15 tháng - 3 tuổi.png", QT, MD, TKB),
    drive_file("md-tkb-36-60", "TKB 3-5 tuổi.png", QT, MD, TKB),
    drive_file("md-tkb-60-72", "TKB 5-6 tuổi.png", QT, MD, TKB),
    *[drive_file(f"md-csvc-{i}", f"IMG_{i:02}.jpg", QT, MD, CSVC) for i in range(1, 8)],
    drive_file("sn-fee-10", "Học phí Kim Mã - Tháng 10.png", SN, "HỌC PHÍ THÁNG 10"),
    drive_file("sn-menu", "Thực đơn Kim Mã.png", SN, "THỰC ĐƠN"),
    drive_file("km-tkb-15-36", "TKB 15 tháng  -3 tuổi.png", SN, KM, TKB),
    drive_file("km-tkb-36-72", "TKB 3-6 tuổi.png", SN, KM, TKB),
    *[drive_file(f"km-csvc-{i}", f"IMG_{i:02}.jpg", SN, KM, CSVC) for i in range(1, 6)],
]


def png(width=40, height=30, color=(200, 30, 30, 255)) -> bytes:
    out = BytesIO()
    Image.new("RGBA", (width, height), color).save(out, "PNG")
    return out.getvalue()


class FakeGoogle:
    """Apps Script web app (302 sang script.googleusercontent.com như thật), link tải Drive (303 sang
    drive.usercontent.google.com) và Telegram, sau httpx."""

    def __init__(self):
        self.files = [dict(f) for f in DRIVE_TREE]
        self.images: dict[str, bytes] = {}
        self.script_answer = None  # None: {"ok": true, "files": self.files}
        self.down = False
        self.requests: list[tuple[str, str, str]] = []
        self.telegram: list[dict] = []
        # The bot's own public image URLs (PUBLIC_BASE_URL) as the internet answers them: "image", "html", "dns",
        # "timeout" or an HTTP status
        self.public: str | int = "image"

    def downloads(self) -> list[str]:
        return [path.rsplit("=", 1)[-1] for host, _, path in self.requests if host == "drive.google.com"]

    def respond(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.requests.append((url.host, request.method, f"{url.path}?{url.query.decode()}"))
        if url.host == "api.telegram.org":
            self.telegram.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7001}})
        if url.host == httpx.URL(BASE_URL).host:
            return self.public_answer(request)
        if self.down:
            raise httpx.ConnectError("network down", request=request)
        if url.host == "script.google.com":
            assert request.method == "POST" and str(url) == SHEET_URL
            assert json.loads(request.content) == {"type": "media", "token": SHEET_TOKEN}
            return httpx.Response(302, headers={"Location": "https://script.googleusercontent.com/macros/echo?u=1"})
        if url.host == "script.googleusercontent.com":
            return httpx.Response(200, json=self.script_answer or {"ok": True, "files": self.files})
        if url.host == "drive.google.com":
            assert url.path == "/uc" and url.params["export"] == "download"
            location = f"https://drive.usercontent.google.com/download?id={url.params['id']}&export=download"
            return httpx.Response(303, headers={"Location": location})
        if url.host == "drive.usercontent.google.com":
            data = self.images.get(url.params["id"]) or png()
            return httpx.Response(200, content=data, headers={"Content-Type": "image/png"})
        raise AssertionError(f"unexpected request {url}")

    def public_answer(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/static/media/") and request.url.path.endswith(".jpg")
        if self.public == "dns":
            # As httpx raises it for a name that does not exist: ConnectError from socket.gaierror
            try:
                raise socket.gaierror(-2, "Name or service not known")
            except socket.gaierror as e:
                raise httpx.ConnectError("[Errno -2] Name or service not known", request=request) from e
        if self.public == "timeout":
            raise httpx.ConnectTimeout("timed out", request=request)
        if self.public == "html":
            return httpx.Response(200, text="<html>Not Found</html>", headers={"Content-Type": "text/html"})
        if self.public == "image":
            return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"Content-Type": "image/jpeg"})
        return httpx.Response(self.public, text="Not Found")

    def public_checks(self) -> int:
        return sum(host == httpx.URL(BASE_URL).host for host, _, _ in self.requests)


@pytest.fixture
def google(monkeypatch, tmp_path):
    fake = FakeGoogle()

    def handle(self, request):
        return fake.respond(request)

    async def handle_async(self, request):
        return fake.respond(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async)
    monkeypatch.setattr(settings, "MEDIA_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "LEADS_SHEET_WEBHOOK_URL", SHEET_URL)
    monkeypatch.setattr(settings, "LEADS_SHEET_TOKEN", SHEET_TOKEN)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", BASE_URL)
    monkeypatch.setattr(media, "_link_alerted_at", None)
    return fake


def sync() -> dict:
    return asyncio.run(media.sync_media())


def media_dir() -> Path:
    return Path(settings.MEDIA_DIR)


def url(file_id: str) -> str:
    return f"{BASE_URL}/static/media/{file_id}.jpg"


def today_vn() -> date:
    return datetime.now(VN_TZ).date()


# --- phân loại theo thư mục và tên file ---


@pytest.mark.parametrize(
    ("name", "ages"),
    [
        ("TKB 15 tháng - 3 tuổi.jpg", (15, 36)),
        ("TKB 15 tháng  -3 tuổi.png", (15, 36)),
        ("TKB 3-5 tuổi.jpg", (36, 60)),
        ("TKB 5-6 tuổi.png", (60, 72)),
        ("TKB 3-6 tuổi.png", (36, 72)),
        ("TKB 3 – 5 tuổi.jpg", (36, 60)),
        ("tkb 5—6 TUOI.JPG", (60, 72)),
        ("TKB 18 tháng-24 tháng.jpg", (18, 24)),
        ("TKB lớp Mầm.jpg", None),
        ("TKB 5-3 tuổi.jpg", None),
    ],
)
def test_age_range_in_months_from_the_timetable_file_name(name, ages):
    assert media.age_range(name) == ages


EXPECTED = {
    "qt-fee-10": {"kind": "fee", "system": "quoc_te", "month": 10},
    "qt-menu": {"kind": "menu", "system": "quoc_te"},
    "cl-tkb-15-36": {"kind": "timetable", "system": "quoc_te", "campus": "Chùa Láng", "age_min": 15, "age_max": 36},
    "cl-tkb-36-60": {"kind": "timetable", "system": "quoc_te", "campus": "Chùa Láng", "age_min": 36, "age_max": 60},
    "cl-tkb-60-72": {"kind": "timetable", "system": "quoc_te", "campus": "Chùa Láng", "age_min": 60, "age_max": 72},
    "cl-csvc-1": {"kind": "facilities", "system": "quoc_te", "campus": "Chùa Láng"},
    "md-tkb-15-36": {"kind": "timetable", "system": "quoc_te", "campus": "Mỹ Đình", "age_min": 15, "age_max": 36},
    "md-csvc-7": {"kind": "facilities", "system": "quoc_te", "campus": "Mỹ Đình"},
    "sn-fee-10": {"kind": "fee", "system": "song_ngu", "month": 10},
    "sn-menu": {"kind": "menu", "system": "song_ngu"},
    "km-tkb-15-36": {"kind": "timetable", "system": "song_ngu", "campus": "Kim Mã", "age_min": 15, "age_max": 36},
    "km-tkb-36-72": {"kind": "timetable", "system": "song_ngu", "campus": "Kim Mã", "age_min": 36, "age_max": 72},
    "km-csvc-5": {"kind": "facilities", "system": "song_ngu", "campus": "Kim Mã"},
}


def test_every_file_of_the_school_drive_is_classified_by_its_folders():
    by_id = {f["id"]: media.classify(f["path"], f["name"]) for f in DRIVE_TREE}

    assert all(by_id.values()), [i for i, c in by_id.items() if not c]
    for file_id, expected in EXPECTED.items():
        got = by_id[file_id]
        assert {k: got.get(k) for k in expected} == expected, file_id
    kinds = [c["kind"] for c in by_id.values()]
    assert (kinds.count("fee"), kinds.count("menu"), kinds.count("timetable"), kinds.count("facilities")) == (2, 2, 8, 18)


@pytest.mark.parametrize(
    ("path", "name", "expected"),
    [
        # Không dấu, chữ thường, thừa dấu cách, kiểu dấu "KHOÁ"/"KHÓA" khác nhau: vẫn là khoá cơ sở của hồ sơ.
        (["he quoc te", "co so  chua lang", "thoi khoa bieu"], "TKB 3-5 tuoi.jpg", {"campus": "Chùa Láng", "age_min": 36}),
        ([SN, "CƠ SỞ KIM MÃ", "THỜI KHOÁ BIỂU"], "TKB 3-6 tuổi.png", {"campus": "Kim Mã", "age_max": 72}),
        # Cơ sở mới: thư mục "CƠ SỞ <TÊN>", không cần sửa code.
        ([QT, "CƠ SỞ CẦU GIẤY", CSVC], "a.jpg", {"kind": "facilities", "campus": "Cầu Giấy"}),
        ([SN, "HỌC PHÍ THÁNG 11"], "x.png", {"kind": "fee", "month": 11}),
    ],
)
def test_folder_names_match_without_accents_case_or_extra_spaces(path, name, expected):
    got = media.classify(path, name)

    assert got and {k: got.get(k) for k in expected} == expected


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ([QT], "logo.png"),  # thẳng trong thư mục hệ
        (["HỆ KHÁC", "THỰC ĐƠN"], "a.jpg"),
        ([QT, "HỌC PHÍ THÁNG 13"], "a.jpg"),
        ([QT, CL], "a.jpg"),
        ([QT, CL, "VIDEO"], "a.jpg"),
        ([QT, CL, TKB], "TKB lớp Mầm.jpg"),  # không đọc được nhóm tuổi
        ([], "a.jpg"),
    ],
)
def test_files_outside_the_folder_conventions_are_not_classified(path, name):
    assert media.classify(path, name) is None


# --- đồng bộ ---


def test_sync_downloads_every_image_resized_to_jpeg_and_serves_its_public_url(google):
    google.images["cl-csvc-1"] = png(3200, 1000)  # lớn hơn 1600 px, có kênh alpha

    report = sync()

    assert report["ok"] is True
    assert (report["total"], report["downloaded"], report["skipped"]) == (30, 30, [])
    assert sorted(google.downloads()) == sorted(f["id"] for f in DRIVE_TREE)
    with Image.open(media_dir() / "cl-csvc-1.jpg") as big:
        assert (big.format, big.mode, big.size) == ("JPEG", "RGB", (1600, 500))
    with Image.open(media_dir() / "qt-menu.jpg") as small:
        assert (small.format, small.size) == ("JPEG", (40, 30))
    assert media.menu_image("quoc_te") == url("qt-menu")
    assert media.menu_image("song ngữ") == url("sn-menu")


def test_catalog_is_written_next_to_the_images_and_read_back_after_a_restart(google, monkeypatch):
    sync()
    on_disk = json.loads((media_dir() / "catalog.json").read_text(encoding="utf-8"))
    assert {item["id"] for item in on_disk["items"]} == {f["id"] for f in DRIVE_TREE}

    monkeypatch.setattr(media, "_catalog", media.load_catalog())  # như lúc import sau khi restart
    assert media.menu_image("song_ngu") == url("sn-menu")
    assert sync()["downloaded"] == 0


def test_unchanged_files_are_not_downloaded_again_and_changed_ones_are(google):
    sync()
    google.requests.clear()
    google.files[1]["modified"] = "2026-10-20T09:00:00.000Z"  # trường thay ảnh thực đơn

    report = sync()

    assert google.downloads() == ["qt-menu"]
    assert (report["downloaded"], report["kept"]) == (1, 29)


def test_a_file_gone_from_drive_leaves_the_catalog_and_the_disk(google):
    sync()
    assert (media_dir() / "md-csvc-7.jpg").exists()
    google.files = [f for f in google.files if f["id"] != "md-csvc-7"]

    report = sync()

    assert report["removed"] == 1
    assert not (media_dir() / "md-csvc-7.jpg").exists()
    assert url("md-csvc-7") not in media.facility_images("Mỹ Đình", limit=10)
    assert "md-csvc-7" not in {item["id"] for item in media.catalog()["items"]}


def test_unclassified_files_are_skipped_and_reported(google):
    google.files.append(drive_file("stray", "logo.png", QT))

    report = sync()

    assert report["skipped"] == ["HỆ QUỐC TẾ/logo.png"]
    assert "stray" not in google.downloads()
    assert media.catalog()["skipped"] == ["HỆ QUỐC TẾ/logo.png"]


@pytest.mark.parametrize("failure", ["network", "ok_false", "not_json"])
def test_a_failed_sync_keeps_the_previous_catalog_and_logs_an_error_without_the_token(google, caplog, failure):
    sync()
    before = media.catalog()["items"]
    if failure == "network":
        google.down = True
    elif failure == "ok_false":
        google.script_answer = {"ok": False}
    else:
        google.script_answer = {"unexpected": "shape"}

    with caplog.at_level(logging.INFO):
        report = sync()

    assert report["ok"] is False and report["error"]
    assert media.catalog()["items"] == before
    assert media.menu_image("quoc_te") == url("qt-menu")
    assert (media_dir() / "qt-menu.jpg").exists()
    errors = [r for r in caplog.records if r.name == "app.media" and r.levelno == logging.ERROR]
    assert errors
    assert all(SHEET_TOKEN not in r.getMessage() and SHEET_URL not in r.getMessage() for r in caplog.records)


def test_a_file_that_fails_to_download_keeps_its_previous_image(google):
    sync()
    google.files[1]["modified"] = "2026-10-20T09:00:00.000Z"
    google.images["qt-menu"] = b"<html>Google Drive - quota exceeded</html>"

    report = sync()

    assert report["ok"] is True
    assert [f.split(":")[0] for f in report["failed"]] == ["HỆ QUỐC TẾ/THỰC ĐƠN/Thực đơn mẫu.jpg"]
    assert media.menu_image("quoc_te") == url("qt-menu")
    assert (media_dir() / "qt-menu.jpg").exists()


def test_drive_ids_that_are_not_plain_ids_are_never_used_as_file_names(google):
    google.files.append(drive_file("../../evil", "x.png", QT, "THỰC ĐƠN"))

    report = sync()

    assert report["total"] == 30
    assert not (media_dir().parent.parent / "evil.jpg").exists()


# --- truy vấn cho quy tắc gửi ảnh ---


@pytest.mark.parametrize(
    ("months", "today", "expected"),
    [
        ([10], date(2026, 10, 23), (10, False)),
        ([9, 10], date(2026, 10, 1), (10, False)),
        ([8, 9], date(2026, 10, 23), (9, True)),
        ([12], date(2027, 1, 3), (12, True)),  # sang năm mới: tháng 12 năm trước
        ([11, 1], date(2027, 1, 3), (1, False)),
        ([], date(2026, 10, 23), None),
    ],
)
def test_fee_image_is_this_month_or_the_latest_month_before_it(google, months, today, expected):
    google.files = [drive_file(f"fee-{m}", f"hp {m}.png", SN, f"HỌC PHÍ THÁNG {m}") for m in months]
    sync()

    fee = media.fee_image("song_ngu", today)

    if expected is None:
        assert fee is None
    else:
        assert (fee.month, fee.stale, fee.url) == (*expected, url(f"fee-{expected[0]}"))
    assert media.fee_image("quoc_te", today) is None


# Thư mục "HỌC PHÍ THÁNG N" không ghi năm: trường quên đổi ảnh tháng 11/2026 thì tháng 11/2027 ảnh đó không được coi
# là ảnh tháng này. Ảnh sửa lần cuối hơn 300 ngày trước là ảnh cũ (stale, bot nhắc trường); học phí giữ nguyên vài tháng thì không.
@pytest.mark.parametrize(
    ("modified", "old_since"),
    [
        ("2026-11-01T02:00:00.000Z", date(2026, 11, 1)),
        ("2027-01-01T02:00:00.000Z", date(2027, 1, 1)),
        ("2027-04-20T02:00:00.000Z", None),
        ("2027-10-30T09:00:00.000Z", None),
        (None, None),
    ],
)
def test_fee_image_last_changed_over_300_days_ago_is_stale(google, modified, old_since):
    google.files = [drive_file("fee-11", "hp.png", SN, "HỌC PHÍ THÁNG 11", modified=modified)]
    sync()

    fee = media.fee_image("song_ngu", date(2027, 11, 3))

    assert (fee.month, fee.stale, fee.old_since) == (11, old_since is not None, old_since)


def test_timetable_image_by_age(google):
    sync()

    assert media.timetable_image("chua lang", 20) == url("cl-tkb-15-36")
    assert media.timetable_image("Mỹ Đình", 36) == url("md-tkb-36-60")
    assert media.timetable_image("Mỹ Đình", 60) == url("md-tkb-60-72")
    assert media.timetable_image("Mỹ Đình", 72) == url("md-tkb-60-72")
    assert media.timetable_image("Cơ sở Kim Mã", 30) == url("km-tkb-15-36")
    assert media.timetable_image("Kim Mã", 10) is None
    assert media.timetable_image("Cầu Giấy", 48) is None


def test_facility_images_and_system_of_campus(google):
    sync()

    assert media.facility_images("Mỹ Đình") == [url(f"md-csvc-{i}") for i in range(1, 6)]
    assert media.facility_images("kim ma", limit=2) == [url("km-csvc-1"), url("km-csvc-2")]
    assert media.facility_images("Cầu Giấy") == []
    assert (media.system_of("Chùa Láng"), media.system_of("mỹ đình"), media.system_of("Kim Mã")) == (
        "quoc_te",
        "quoc_te",
        "song_ngu",
    )
    assert media.system_of("Cầu Giấy") is None


# Hệ của 3 cơ sở theo bảng cố định của trường: Drive thiếu thư mục một cơ sở thì phụ huynh cơ sở đó vẫn nhận đúng
# ảnh học phí của hệ. Cơ sở mới (ngoài bảng) lấy hệ theo thư mục chứa nó trên Drive.
def test_system_of_the_three_campuses_is_fixed_and_a_new_campus_follows_its_drive_folder(google):
    google.files = [
        drive_file("sn-fee-10", "hp.png", SN, "HỌC PHÍ THÁNG 10"),
        drive_file("cg-csvc-1", "a.jpg", SN, "CƠ SỞ CẦU GIẤY", CSVC),
        drive_file("km-in-qt", "a.jpg", QT, KM, CSVC),
    ]
    sync()

    assert [media.system_of(c) for c in ("Chùa Láng", "mỹ đình", "Kim Mã", "Cơ sở Kim Mã")] == [
        "quoc_te", "quoc_te", "song_ngu", "song_ngu"
    ]
    assert media.system_of("Cầu Giấy") == "song_ngu"
    assert media.system_of("Hoàn Kiếm") is None


# --- tắt khi chưa cấu hình ---


@pytest.mark.parametrize("missing", ["MEDIA_SYNC_ENABLED", "LEADS_SHEET_WEBHOOK_URL", "LEADS_SHEET_TOKEN"])
def test_without_configuration_nothing_goes_out_and_the_warning_is_logged_once(monkeypatch, caplog, missing):
    monkeypatch.setattr(settings, "MEDIA_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "LEADS_SHEET_WEBHOOK_URL", SHEET_URL)
    monkeypatch.setattr(settings, "LEADS_SHEET_TOKEN", SHEET_TOKEN)
    monkeypatch.setattr(settings, missing, False if missing == "MEDIA_SYNC_ENABLED" else "")

    with caplog.at_level(logging.WARNING, logger="app.media"):
        report = sync()  # mạng thật bị conftest chặn: có request là test đỏ
        with TestClient(main.app):
            pass
        with TestClient(main.app):
            pass

    assert report["ok"] is False
    warnings = [r for r in caplog.records if r.name == "app.media" and r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_the_bot_syncs_in_the_background_when_it_starts(google):
    with TestClient(main.app) as client:
        assert client.get("/").json()["status"] == "ok"
        deadline = time.time() + 10
        while time.time() < deadline and media.menu_image("quoc_te") is None:
            time.sleep(0.05)

    assert media.menu_image("quoc_te") == url("qt-menu")


# --- /capnhatanh và /media ---


@pytest.fixture
def admin_group(google, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "000:fake-bot")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", CHAT_ID)
    return google


def command(text="/capnhatanh", chat_id=CHAT_ID, message_id=900, **extra) -> httpx.Response:
    update = {
        "update_id": 1,
        "message": {
            "message_id": message_id,
            "chat": {"id": int(chat_id), "type": "supergroup"},
            "from": {"id": 111, "is_bot": False, "first_name": "Admin"},
            "text": text,
            **extra,
        },
    }
    return TestClient(main.app).post(
        "/telegram-webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}
    )


def drive_downloads(fake) -> int:
    return len(fake.downloads())


def test_capnhatanh_syncs_now_and_reports_counts_to_the_admin_group(admin_group):
    month = today_vn().month
    for f in admin_group.files:
        if f["path"][-1] == "HỌC PHÍ THÁNG 10":
            f["path"] = [f["path"][0], f"HỌC PHÍ THÁNG {month}"]
            f["modified"] = f"{today_vn():%Y-%m-%d}T00:00:00.000Z"
    admin_group.files.append(drive_file("stray", "logo.png", QT))

    resp = command("/capnhatanh@CasaBot")

    assert resp.status_code == 200
    assert drive_downloads(admin_group) == 30
    (sent,) = admin_group.telegram
    assert sent["chat_id"] == CHAT_ID
    text = sent["text"]
    assert "30 ảnh" in text
    assert f"Học phí: Quốc tế tháng {month}, Song ngữ tháng {month}" in text
    assert "Thời khoá biểu: Chùa Láng 3, Mỹ Đình 3, Kim Mã 2" in text
    assert "Cơ sở vật chất: Chùa Láng 6, Mỹ Đình 7, Kim Mã 5" in text
    assert "Thực đơn: Quốc tế 1, Song ngữ 1" in text
    assert "HỆ QUỐC TẾ/logo.png" in text
    assert "Chưa có ảnh học phí mới" not in text


def test_capnhatanh_warns_when_this_months_fee_image_is_missing(admin_group):
    month = today_vn().month
    previous = (month - 2) % 12 + 1
    changed = f"{today_vn():%Y-%m-%d}T00:00:00.000Z"
    admin_group.files = [drive_file("fee-old", "hp.png", SN, f"HỌC PHÍ THÁNG {previous}", modified=changed)]

    command()

    (sent,) = admin_group.telegram
    assert f"Chưa có ảnh học phí mới tháng {month}: Quốc tế, Song ngữ (Song ngữ đang dùng tháng {previous})" in sent["text"]


def test_capnhatanh_warns_when_this_months_fee_image_is_last_years(admin_group):
    month = today_vn().month
    last_year = today_vn().replace(year=today_vn().year - 1, day=1)
    admin_group.files = [
        drive_file("fee-old", "hp.png", SN, f"HỌC PHÍ THÁNG {month}", modified=f"{last_year:%Y-%m-%d}T02:00:00.000Z")
    ]

    command()

    (sent,) = admin_group.telegram
    assert (
        f"Chưa có ảnh học phí mới tháng {month}: Quốc tế, Song ngữ (Song ngữ đang dùng tháng {month} sửa lần cuối "
        f"{last_year:%d/%m/%Y})" in sent["text"]
    )


def test_capnhatanh_reports_a_failed_sync_and_the_images_kept(admin_group):
    command(message_id=901)
    admin_group.telegram.clear()
    admin_group.down = True

    command(message_id=902)

    (sent,) = admin_group.telegram
    assert "Không cập nhật được ảnh" in sent["text"] and "30 ảnh" in sent["text"]
    assert SHEET_TOKEN not in sent["text"]


# Thử thật trên Render 2026-10-24: PUBLIC_BASE_URL chưa đặt nên link ảnh mang tên miền mặc định không tồn tại, Graph
# trả "(#100) Upload failed" cho mọi ảnh và chỉ biết khi phụ huynh đã nhận câu xin lỗi. Sau mỗi lần đồng bộ có ảnh,
# bot tự mở một link ảnh công khai của chính nó như Messenger sẽ mở.
LINK_ALERT = "⚠️ Link ảnh không mở được"


def link_alerts(fake) -> list[str]:
    return [t["text"] for t in fake.telegram if t["text"].startswith(LINK_ALERT)]


def test_capnhatanh_reports_the_image_link_ok(admin_group):
    command()

    (sent,) = admin_group.telegram
    assert sent["text"].startswith("🖼 CẬP NHẬT ẢNH: 30 ảnh"), sent["text"]
    assert sent["text"].splitlines()[-1] == "Link ảnh: OK"
    assert admin_group.public_checks() == 1


@pytest.mark.parametrize(
    ("public", "reason"),
    [
        ("dns", "DNS: không tìm thấy tên miền"),
        (404, "HTTP 404"),
        ("html", "HTTP 200 nhưng không phải ảnh: text/html"),
        ("timeout", "timeout"),
    ],
)
def test_capnhatanh_tells_the_admin_group_when_the_image_link_does_not_open(admin_group, public, reason):
    admin_group.public = public

    command()

    summary = next(t["text"] for t in admin_group.telegram if t["text"].startswith("🖼"))
    assert summary.splitlines()[-1] == f"Link ảnh: lỗi ({reason})", summary
    assert "30 ảnh" in summary  # the sync itself went through
    (alert,) = link_alerts(admin_group)
    (checked,) = [path for host, _, path in admin_group.requests if host == httpx.URL(BASE_URL).host]
    link = BASE_URL + checked.rstrip("?")
    assert link in [i["url"] for i in media.catalog()["items"]]
    assert alert == (
        f"{LINK_ALERT} ({reason}): {link}. Kiểm PUBLIC_BASE_URL trên Render (hiện là {BASE_URL}), "
        "phải trùng địa chỉ service ở đầu trang Render."
    )
    assert SHEET_TOKEN not in alert and "fake-bot" not in alert


def test_a_broken_image_link_is_told_at_most_once_an_hour(admin_group, monkeypatch):
    admin_group.public = "dns"
    command(message_id=910)
    command(message_id=911)

    assert len(link_alerts(admin_group)) == 1
    assert [t["text"].splitlines()[-1] for t in admin_group.telegram if t["text"].startswith("🖼")] == [
        "Link ảnh: lỗi (DNS: không tìm thấy tên miền)"
    ] * 2

    monkeypatch.setattr(media, "_link_alerted_at", time.monotonic() - 3601)
    command(message_id=912)
    assert len(link_alerts(admin_group)) == 2


def test_the_image_link_is_checked_after_the_sync_when_the_bot_starts(admin_group):
    admin_group.public = 404

    with TestClient(main.app):
        deadline = time.time() + 10
        while time.time() < deadline and not link_alerts(admin_group):
            time.sleep(0.05)

    assert media.menu_image("quoc_te") == url("qt-menu")
    (alert,) = link_alerts(admin_group)
    assert "(HTTP 404)" in alert and "/static/media/" in alert, alert


def test_without_images_no_link_is_checked(admin_group):
    admin_group.files = []

    command()

    (sent,) = admin_group.telegram
    assert "Link ảnh" not in sent["text"]
    assert admin_group.public_checks() == 0


@pytest.mark.parametrize(
    "variant",
    [
        {"chat_id": "-1000000000001"},  # nhóm khác
        {"reply_to_message": {"message_id": 5, "text": "📞 KHÁCH ĐỂ LẠI SĐT", "from": {"id": 1, "is_bot": True}}},
        {"text": "cập nhật ảnh giúp em"},
    ],
)
def test_only_the_command_in_the_admin_group_syncs(admin_group, variant):
    command(**variant)

    assert admin_group.requests == []


def test_the_same_telegram_update_delivered_twice_syncs_once(admin_group):
    command(message_id=950)
    command(message_id=950)

    assert drive_downloads(admin_group) == 30
    assert len(admin_group.telegram) == 1


def test_media_endpoint_needs_the_secret_and_lists_the_catalog(admin_group):
    sync()
    client = TestClient(main.app)

    assert client.get("/media").status_code == 403
    assert client.get("/media", params={"secret": "wrong"}).status_code == 403
    body = client.get("/media", params={"secret": WEBHOOK_SECRET}).json()

    assert body["total"] == 30
    assert body["counts"] == {"fee": 2, "menu": 2, "timetable": 8, "facilities": 18}
    menu = next(item for item in body["items"] if item["id"] == "qt-menu")
    assert (menu["kind"], menu["system"], menu["url"]) == ("menu", "quoc_te", url("qt-menu"))
    assert menu["path"] == [QT, "THỰC ĐƠN"]


def test_media_mount_serves_images_but_not_the_catalog(tmp_path):
    """catalog.json lives next to the images (Drive paths and ids): /static/media/ serves only the .jpg files."""
    from fastapi import FastAPI

    (tmp_path / "abc.jpg").write_bytes(b"\xff\xd8jpeg")
    (tmp_path / media.CATALOG_FILE).write_text('{"items": []}', encoding="utf-8")
    probe = FastAPI()
    probe.mount("/static/media", main._ImagesOnly(directory=tmp_path), name="media")
    client = TestClient(probe)

    assert client.get("/static/media/abc.jpg").status_code == 200
    assert client.get(f"/static/media/{media.CATALOG_FILE}").status_code == 404
