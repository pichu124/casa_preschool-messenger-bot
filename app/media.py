"""Images from the school's Google Drive folder "Ảnh cho Chatbot", sorted by its folders (README "Ảnh từ Google
Drive"): the Apps Script web app of the leads Sheet lists the image files (type "media", docs/google-sheet-leads.md),
the bot downloads new or changed ones, shrinks them to JPEG in MEDIA_DIR (served at /static/media/) and keeps a
catalog in memory and in MEDIA_DIR/catalog.json. Lookups give the public URL Messenger downloads.

Folder conventions under the root ("HỆ QUỐC TẾ" / "HỆ SONG NGỮ"):
    <HỆ>/HỌC PHÍ THÁNG <N>/*                   fee of month N
    <HỆ>/THỰC ĐƠN/*                            menu
    <HỆ>/CƠ SỞ <TÊN>/THỜI KHÓA BIỂU/*          timetable; the file name gives the age group ("TKB 3-5 tuổi")
    <HỆ>/CƠ SỞ <TÊN>/ẢNH CƠ SỞ VẬT CHẤT/*      facilities
Names match without accents, case or extra spaces. Any other file is skipped and reported.
"""
import asyncio
import json
import logging
import re
import socket
import time
import unicodedata
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import httpx
from PIL import Image, ImageOps

from app import escalation
from app.config import settings
from app.leads_sheet import VN_TZ
from app.messenger import QUICK_REPLIES

logger = logging.getLogger(__name__)

SYSTEMS = {"he quoc te": "quoc_te", "he song ngu": "song_ngu"}
SYSTEM_NAMES = {"quoc_te": "Quốc tế", "song_ngu": "Song ngữ"}
# Campus keys as parent profiles store interested_campus (the campus buttons); a new campus folder keeps its own name.
CAMPUSES = tuple(title for title, _ in QUICK_REPLIES["campus"])
# The system of each campus (docs/quyet-dinh-noi-dung.md, mục 4), whatever Drive holds; a new campus: its Drive folder.
CAMPUS_SYSTEMS = {"Chùa Láng": "quoc_te", "Mỹ Đình": "quoc_te", "Kim Mã": "song_ngu"}
KINDS = ("fee", "menu", "timetable", "facilities")
DOWNLOAD_URL = "https://drive.google.com/uc"
MAX_SIDE = 1600
JPEG_QUALITY = 85
CATALOG_FILE = "catalog.json"
# "HỌC PHÍ THÁNG N" has no year: a fee image last changed longer ago than this is taken for last year's.
FEE_STALE_AFTER = timedelta(days=300)
# After a sync with images the bot opens one of its public image URLs as Messenger will (check_link): a wrong
# PUBLIC_BASE_URL fails every image ("(#100) Upload failed") and the admin group hears of it at most once an hour.
LINK_CHECK_TIMEOUT = 10
LINK_ALERT_EVERY = 3600  # seconds

_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−"})
_AGES = re.compile(r"(\d+)\s*(thang|tuoi)?\s*-\s*(\d+)\s*(thang|tuoi)")
_FEE = re.compile(r"hoc phi thang (\d{1,2})")
_DRIVE_ID = re.compile(r"[A-Za-z0-9_-]+")


class FeeImage(NamedTuple):
    url: str
    month: int
    stale: bool  # no image for this month (the latest month before it), or an old one
    old_since: date | None = None  # its last change on Drive, when older than FEE_STALE_AFTER


def fold(text: str) -> str:
    """Lowercase, no accents, single spaces: "THỜI KHOÁ  BIỂU" -> "thoi khoa bieu"."""
    text = unicodedata.normalize("NFD", str(text).replace("đ", "d").replace("Đ", "D"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.lower().split())


def age_range(name: str) -> tuple[int, int] | None:
    """(from, to) in months of a timetable file name: "TKB 15 tháng - 3 tuổi.jpg" -> (15, 36)."""
    m = _AGES.search(fold(Path(name).stem.translate(_DASHES)))
    if not m:
        return None
    low, low_unit, high, high_unit = int(m[1]), m[2] or m[4], int(m[3]), m[4]
    low, high = (low if low_unit == "thang" else low * 12), (high if high_unit == "thang" else high * 12)
    return (low, high) if low < high else None


_KID_AGE = re.compile(
    r"(duoi\s+)?(\d+(?:[.,]5)?)\s*(?:-\s*\d+(?:[.,]5)?\s*)?(thang|tuoi)(?:\s*(\d+)\s*thang)?"
)


# A birth date: "sinh năm 2022", "sinh tháng 3/2022", "sinh tháng 3 năm 2022", "sinh 12/2023", "sinh ngày 5/3/2022";
# not "tuyển sinh 2025" nor "học sinh năm 2024".
_BORN = re.compile(r"(?<!tuyen )(?<!hoc )\bsinh (?:nam |(?:ngay )?(?:\d{1,2}/)?(?:thang )?(\d{1,2})(?:/|-| nam | ))?((?:19|20)\d{2})\b")
# The month of a birth year said without it: mid-year, at most 6 months off.
BORN_MONTH_UNKNOWN = 7


def age_months(kid_age: str, today: date | None = None) -> int | None:
    """Months of a kid age as parents and the profile write it: "20 tháng" -> 20, "3 tuổi" -> 36, "2-3 tuổi" -> 24
    (the lower end), "dưới 2 tuổi" -> 18, "2 tuổi 3 tháng" -> 27, a bare number is years ("3" -> 36), a birth date
    up to `today` (Vietnam's today by default; "sinh tháng 3/2022" -> 55 in October 2026, a year alone counts from
    BORN_MONTH_UNKNOWN); else None."""
    folded = fold(str(kid_age or "")).translate(_DASHES)
    if folded.isdigit():
        # A bare number is years ("3"); a bare year ("2022") is the birth year, never 24264 months
        if len(folded) == 4:
            return age_months(f"sinh nam {folded}", today)
        return int(folded) * 12 if int(folded) <= 7 else None
    m = _KID_AGE.search(folded)
    if not m:
        born = _BORN.search(folded)
        if not born:
            return None
        today = today or datetime.now(VN_TZ).date()
        month = int(born[1] or BORN_MONTH_UNKNOWN)
        months = (today.year - int(born[2])) * 12 + today.month - month
        return months if 1 <= month <= 12 and months >= 0 else None
    value = float(m[2].replace(",", "."))
    if m[3] == "thang":
        return int(value)
    return int(value * 12) - (6 if m[1] else 0) + int(m[4] or 0)


def campus_in(text: str) -> str | None:
    """The one campus key named in `text` ("Em quan tâm cơ sở Kim Mã ạ" -> "Kim Mã"); None for none or several."""
    folded = fold(str(text or ""))
    named = [c for c in CAMPUSES if re.search(rf"\b{fold(c)}\b", folded)]
    return named[0] if len(named) == 1 else None


def campuses_in(text: str) -> list[str]:
    """Every campus key named in `text`, in the order named: "Chùa Láng và Kim Mã" -> ["Chùa Láng", "Kim Mã"]."""
    folded = fold(str(text or ""))
    found = {c: m.start() for c in CAMPUSES if (m := re.search(rf"\b{fold(c)}\b", folded))}
    return sorted(found, key=found.get)


def campus_key(name: str) -> str:
    folded = fold(name)
    return next((c for c in CAMPUSES if fold(c) == folded), " ".join(name.split()).title())


def classify(path: list[str], name: str) -> dict | None:
    """kind, system, month, campus, age_min, age_max of a file at `path` (folders below the root), or None."""
    folders = [fold(p) for p in path]
    if not folders or folders[0] not in SYSTEMS:
        return None
    item = {"kind": None, "system": SYSTEMS[folders[0]], "month": None, "campus": None, "age_min": None, "age_max": None}
    rest = folders[1:]
    if len(rest) == 1:
        fee = _FEE.fullmatch(rest[0])
        if fee and 1 <= int(fee[1]) <= 12:
            return {**item, "kind": "fee", "month": int(fee[1])}
        if rest[0] == "thuc don":
            return {**item, "kind": "menu"}
        return None
    if len(rest) != 2 or not rest[0].startswith("co so "):
        return None
    item["campus"] = campus_key(" ".join(path[1].split()[2:]))
    if rest[1] == "anh co so vat chat":
        return {**item, "kind": "facilities"}
    ages = age_range(name) if rest[1] == "thoi khoa bieu" else None
    if not ages:
        return None
    return {**item, "kind": "timetable", "age_min": ages[0], "age_max": ages[1]}


def _empty() -> dict:
    return {"synced_at": None, "last_error": None, "items": {}, "skipped": []}


def _media_dir() -> Path:
    return Path(settings.MEDIA_DIR)


def load_catalog() -> dict:
    """The catalog MEDIA_DIR/catalog.json saved, keeping the items whose image is still on disk."""
    path = _media_dir() / CATALOG_FILE
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        items = {i["id"]: i for i in saved["items"] if (_media_dir() / f"{i['id']}.jpg").exists()}
        return {**_empty(), "synced_at": saved.get("synced_at"), "items": items, "skipped": saved.get("skipped", [])}
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Media catalog {path} unreadable ({type(e).__name__}): the next sync downloads every image")
        return _empty()


_catalog = load_catalog()
_lock = asyncio.Lock()
_off_warned = False
# Set once the first sync since start_sync_task has ended (done or failed), at once when sync is off or images of
# the last run are on disk; None before start_sync_task (no app started).
_first_sync: asyncio.Event | None = None
# time.monotonic() of the last broken-link alert (check_link); in memory
_link_alerted_at: float | None = None


def _configured() -> bool:
    return bool(settings.MEDIA_SYNC_ENABLED and settings.LEADS_SHEET_WEBHOOK_URL and settings.LEADS_SHEET_TOKEN)


def _enabled() -> bool:
    global _off_warned
    if _configured():
        return True
    if not _off_warned:
        _off_warned = True
        logger.warning(
            "Media sync off: needs MEDIA_SYNC_ENABLED=true, LEADS_SHEET_WEBHOOK_URL and LEADS_SHEET_TOKEN "
            "(docs/google-sheet-leads.md, mục 7)"
        )
    return False


class _SyncError(Exception):
    pass


async def _list_drive() -> list[dict]:
    body = {"type": "media", "token": settings.LEADS_SHEET_TOKEN}
    try:
        # The web app runs doPost, then answers 302 to script.googleusercontent.com where its output is.
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            resp = await client.post(settings.LEADS_SHEET_WEBHOOK_URL, json=body)
        result = resp.json()
    except Exception as e:  # the URL and token stay out of the log: str(e) of httpx errors carries the URL
        raise _SyncError(type(e).__name__) from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        why = str(result.get("error"))[:200] if isinstance(result, dict) and result.get("error") else "script without type media?"
        raise _SyncError(f"Apps Script answered HTTP {resp.status_code} without ok:true ({why})")
    if not isinstance(result.get("files"), list):
        raise _SyncError("Apps Script answered without a file list")
    return result["files"]


def _save_jpeg(data: bytes, out: Path) -> None:
    """At most MAX_SIDE px on the long side, JPEG; transparency on white. CPU-bound: run in a thread."""
    with Image.open(BytesIO(data)) as img:
        img.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG: decode at a smaller scale (photos up to 14 MB)
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            rgba = img.convert("RGBA")
            img = Image.new("RGB", rgba.size, "white")
            img.paste(rgba, mask=rgba.getchannel("A"))
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        tmp = out.with_name(out.name + ".part")
        img.save(tmp, "JPEG", quality=JPEG_QUALITY, optimize=True)
    tmp.replace(out)


async def _download(client: httpx.AsyncClient, file_id: str) -> None:
    resp = await client.get(DOWNLOAD_URL, params={"export": "download", "id": file_id})
    resp.raise_for_status()
    await asyncio.to_thread(_save_jpeg, resp.content, _media_dir() / f"{file_id}.jpg")


def _where(f: dict) -> str:
    return "/".join([*map(str, f.get("path") or []), str(f.get("name", ""))])


def _write_catalog(catalog: dict) -> None:
    path = _media_dir() / CATALOG_FILE
    saved = {"synced_at": catalog["synced_at"], "items": list(catalog["items"].values()), "skipped": catalog["skipped"]}
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _report(**fields) -> dict:
    return {"ok": False, "error": None, "total": len(_catalog["items"]), "downloaded": 0, "kept": 0, "removed": 0,
            "skipped": [], "failed": [], **fields}


async def sync_media() -> dict:
    """List the Drive folder, download what is new or changed, drop what is gone. Never raises: on any failure
    the previous catalog stays (logged ERROR). Returns counts for the admin summary (sync_summary)."""
    global _catalog
    if not _enabled():
        return _report(error="off")
    async with _lock:
        try:
            files = await _list_drive()
        except _SyncError as e:
            logger.error(f"Media sync failed, keeping {len(_catalog['items'])} images: {e}")
            _catalog = {**_catalog, "last_error": str(e)}
            return _report(error=str(e))
        try:
            return await _apply(files)
        except Exception as e:
            logger.exception(f"Media sync failed, keeping {len(_catalog['items'])} images")
            _catalog = {**_catalog, "last_error": type(e).__name__}
            return _report(error=type(e).__name__)


async def _apply(files: list[dict]) -> dict:
    global _catalog
    old = _catalog["items"]
    items, skipped, failed, downloaded = {}, [], [], 0
    _media_dir().mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, connect=15)) as client:
        for f in files:
            file_id = str(f.get("id", "")) if isinstance(f, dict) else ""
            sort = classify(f.get("path") or [], str(f.get("name", ""))) if file_id else None
            if not sort or not _DRIVE_ID.fullmatch(file_id) or not str(f.get("mimeType", "")).startswith("image/"):
                skipped.append(_where(f) if isinstance(f, dict) else repr(f))
                continue
            item = {"id": file_id, "name": f["name"], "path": f["path"], "modified": f.get("modified"), **sort}
            previous = old.get(file_id)
            if previous and previous["modified"] == item["modified"] and (_media_dir() / f"{file_id}.jpg").exists():
                items[file_id] = item
                continue
            try:
                await _download(client, file_id)
            except Exception as e:  # one bad file (HTML instead of an image, timeout) does not stop the others
                failed.append(f"{_where(f)}: {type(e).__name__}")
                logger.error(f"Media {file_id} not downloaded: {type(e).__name__}")
                if previous:
                    items[file_id] = previous
                continue
            items[file_id] = item
            downloaded += 1
    for file_id in old.keys() - items.keys():
        (_media_dir() / f"{file_id}.jpg").unlink(missing_ok=True)
    _catalog = {"synced_at": datetime.now(VN_TZ).isoformat(timespec="seconds"), "last_error": None,
                "items": items, "skipped": skipped}
    _write_catalog(_catalog)
    removed = len(old.keys() - items.keys())
    logger.info(f"Media synced: {len(items)} images, {downloaded} downloaded, {removed} removed, "
                f"{len(skipped)} skipped, {len(failed)} failed")
    return _report(ok=True, total=len(items), downloaded=downloaded, kept=len(items) - downloaded,
                   removed=removed, skipped=skipped, failed=failed)


async def sync_forever(first_sync: asyncio.Event) -> None:
    started = time.monotonic()
    try:
        report = await sync_media()
    finally:
        first_sync.set()
    outcome = "done" if report["ok"] else f"failed ({report['error']})"
    logger.info(f"Media first sync since start {outcome} in {time.monotonic() - started:.1f}s: {report['total']} images")
    while True:
        if report["total"]:
            await check_link()
        await asyncio.sleep(max(1, settings.MEDIA_SYNC_MINUTES) * 60)
        report = await sync_media()


def start_sync_task() -> asyncio.Task | None:
    """Sync now and every MEDIA_SYNC_MINUTES in the background (lifespan of app/main.py); None when off."""
    global _first_sync
    enabled = _enabled()
    _first_sync = asyncio.Event()
    if not enabled or _catalog["items"]:
        _first_sync.set()
    return asyncio.create_task(sync_forever(_first_sync)) if enabled else None


async def ready(timeout: float) -> bool:
    """Wait at most `timeout` seconds for the first sync since start (see _first_sync); True once it has ended.
    Never raises."""
    first_sync = _first_sync
    if first_sync is None or first_sync.is_set():
        return True
    try:
        await asyncio.wait_for(first_sync.wait(), timeout)
    except TimeoutError:
        return False
    return True


def _link_failure(error: Exception) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    cause = error
    while cause is not None:
        if isinstance(cause, socket.gaierror):
            return "DNS: không tìm thấy tên miền"
        cause = cause.__cause__ or cause.__context__
    return "không kết nối được" if isinstance(error, httpx.ConnectError) else type(error).__name__


async def check_link() -> str | None:
    """Open the public URL of one catalog image over the internet, as Messenger downloads it: None when it answers
    200 with an image (or the catalog has none), else a short reason ("DNS: …", "HTTP 404", "timeout", "HTTP 200 nhưng
    không phải ảnh: text/html"), also told to the admin group at most once every LINK_ALERT_EVERY. Never raises."""
    global _link_alerted_at
    if not _catalog["items"]:
        return None
    link = public_url(_catalog["items"][min(_catalog["items"])])
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=LINK_CHECK_TIMEOUT) as client:
            resp = await client.get(link)
        content_type = resp.headers.get("content-type", "")
        if resp.status_code != 200:
            reason = f"HTTP {resp.status_code}"
        elif not content_type.startswith("image/"):
            reason = f"HTTP 200 nhưng không phải ảnh: {content_type.split(';')[0] or 'không có Content-Type'}"
        else:
            return None
    except Exception as e:
        reason = _link_failure(e)
    logger.error(f"Media link {link} does not open: {reason}")
    if _link_alerted_at is None or time.monotonic() - _link_alerted_at >= LINK_ALERT_EVERY:
        _link_alerted_at = time.monotonic()
        await escalation._send_telegram(
            f"⚠️ Link ảnh không mở được ({reason}): {link}. Kiểm PUBLIC_BASE_URL trên Render (hiện là "
            f"{settings.PUBLIC_BASE_URL or 'chưa đặt'}), phải trùng địa chỉ service ở đầu trang Render."
        )
    return reason


# --- lookups ---


def public_url(item: dict) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/static/media/{item['id']}.jpg"


def _system(value: str) -> str | None:
    folded = fold(value).replace("_", " ").removeprefix("he ")
    return SYSTEMS.get(f"he {folded}")


def _campus_named(name: str, campus: str) -> bool:
    return fold(name) == fold(campus).removeprefix("co so ").strip()


def _same_campus(item: dict, campus: str) -> bool:
    return bool(item["campus"]) and _campus_named(item["campus"], campus)


def _items(kind: str, **match) -> list[dict]:
    found = [i for i in _catalog["items"].values() if i["kind"] == kind and all(i[k] == v for k, v in match.items())]
    return sorted(found, key=lambda i: (fold(i["name"]), i["id"]))


def _changed_on(item: dict) -> date | None:
    try:
        return datetime.fromisoformat(item["modified"]).astimezone(VN_TZ).date()
    except (TypeError, ValueError):
        return None


def fee_image(system: str, today_vn: date) -> FeeImage | None:
    """This month's fee image of "quoc_te"/"song_ngu" (or "Quốc tế", "hệ song ngữ"); none: the latest month
    before it, stale=True (January looks at December first). Also stale: an image last changed on Drive longer
    than FEE_STALE_AFTER ago (a month folder of last year left in place)."""
    for back in range(12):
        month = (today_vn.month - 1 - back) % 12 + 1
        found = _items("fee", system=_system(system), month=month)
        if found:
            changed = _changed_on(found[0])
            old_since = changed if changed and today_vn - changed > FEE_STALE_AFTER else None
            return FeeImage(public_url(found[0]), month, back > 0 or old_since is not None, old_since)
    return None


def fee_in_use(fee: FeeImage) -> str:
    """The stale fee image parents get, for the admin group: "tháng 9", "tháng 11 sửa lần cuối 01/11/2026"."""
    return f"tháng {fee.month}" + (f" sửa lần cuối {fee.old_since:%d/%m/%Y}" if fee.old_since else "")


def menu_image(system: str) -> str | None:
    found = _items("menu", system=_system(system))
    return public_url(found[0]) if found else None


def has_timetables(campus: str | None = None) -> bool:
    """Whether Drive has a timetable of the campus (any campus when None)."""
    return any(campus is None or _same_campus(i, campus) for i in _items("timetable"))


def timetable_image(campus: str, age_months: int) -> str | None:
    """Timetable of the campus for a kid of `age_months` (from <= age < to, or the group ending at it)."""
    groups = sorted((i for i in _items("timetable") if _same_campus(i, campus)), key=lambda i: i["age_min"])
    found = [i for i in groups if i["age_min"] <= age_months < i["age_max"]]
    found = found or [i for i in groups if i["age_max"] == age_months]
    return public_url(found[0]) if found else None


def facility_images(campus: str, limit: int = 5) -> list[str]:
    return [public_url(i) for i in _items("facilities") if _same_campus(i, campus)][:limit]


def system_of(campus: str) -> str | None:
    fixed = next((s for c, s in CAMPUS_SYSTEMS.items() if _campus_named(c, campus)), None)
    return fixed or next((i["system"] for i in _catalog["items"].values() if _same_campus(i, campus)), None)


# --- admin views ---


def catalog() -> dict:
    """The catalog as GET /media shows it."""
    items = sorted(_catalog["items"].values(), key=lambda i: (KINDS.index(i["kind"]), _where(i)))
    return {
        "enabled": _configured(),
        "synced_at": _catalog["synced_at"],
        "last_error": _catalog["last_error"],
        "total": len(items),
        "counts": {kind: sum(i["kind"] == kind for i in items) for kind in KINDS},
        "items": [{**i, "url": public_url(i)} for i in items],
        "skipped": _catalog["skipped"],
    }


def _campus_order(campus: str) -> tuple:
    return (CAMPUSES.index(campus) if campus in CAMPUSES else len(CAMPUSES), campus)


def _per_campus(kind: str) -> str:
    counts: dict[str, int] = {}
    for i in _items(kind):
        counts[i["campus"]] = counts.get(i["campus"], 0) + 1
    return ", ".join(f"{c} {counts[c]}" for c in sorted(counts, key=_campus_order)) or "chưa có"


def _listed(names: list[str], limit: int = 10) -> str:
    """Names joined for Telegram (a message holds at most 4096 characters)."""
    more = f"; … và {len(names) - limit} file khác" if len(names) > limit else ""
    return "; ".join(names[:limit]) + more


def sync_summary(report: dict, today_vn: date) -> str:
    """Telegram text for /capnhatanh: counts per kind and campus, skipped files, this month's fee missing."""
    if report["error"] == "off":
        return ("🖼 Đồng bộ ảnh đang tắt: cần MEDIA_SYNC_ENABLED=true, LEADS_SHEET_WEBHOOK_URL và "
                "LEADS_SHEET_TOKEN trên Render (docs/google-sheet-leads.md, mục 7).")
    if not report["ok"]:
        return (f"⚠️ Không cập nhật được ảnh ({report['error']}). "
                f"Bot vẫn dùng {report['total']} ảnh của lần đồng bộ trước.")
    fees = []
    for system, label in SYSTEM_NAMES.items():
        months = sorted({i["month"] for i in _items("fee", system=system)})
        if months:
            fees.append(f"{label} tháng {', '.join(map(str, months))}")
    menus = [f"{label} {len(_items('menu', system=system))}" for system, label in SYSTEM_NAMES.items()]
    lines = [
        f"🖼 CẬP NHẬT ẢNH: {report['total']} ảnh (tải mới {report['downloaded']}, giữ nguyên {report['kept']}, "
        f"xoá {report['removed']})",
        f"Học phí: {', '.join(fees) or 'chưa có'}",
        f"Thực đơn: {', '.join(menus)}",
        f"Thời khoá biểu: {_per_campus('timetable')}",
        f"Cơ sở vật chất: {_per_campus('facilities')}",
    ]
    missing, older = [], []
    for system, label in SYSTEM_NAMES.items():
        fee = fee_image(system, today_vn)
        if not fee or fee.stale:
            missing.append(label)
        if fee and fee.stale:
            older.append(f"{label} đang dùng {fee_in_use(fee)}")
    if missing:
        note = f" ({', '.join(older)})" if older else ""
        lines.append(f"⚠️ Chưa có ảnh học phí mới tháng {today_vn.month}: {', '.join(missing)}{note}")
    if report["skipped"]:
        lines.append(f"⚠️ Bỏ qua {len(report['skipped'])} file không đúng quy ước thư mục: {_listed(report['skipped'])}")
    if report["failed"]:
        lines.append(f"⚠️ Không tải được {len(report['failed'])} file (giữ ảnh cũ nếu có): {_listed(report['failed'])}")
    return "\n".join(lines)
