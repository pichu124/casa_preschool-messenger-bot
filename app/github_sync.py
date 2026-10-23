import base64
import json

import httpx

from app.config import settings

REPO = "pichu124/casa_preschool-messenger-bot"
FILE_PATH = "data/qa_database.json"
BRANCH = "main"
API_URL = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
# Q&A is loaded while the app starts: do not hold the start up for long if GitHub is slow.
PULL_TIMEOUT = 10
PUSH_TIMEOUT = 15


class GitHubError(Exception):
    """GitHub answered with an unexpected status. The message is the status only: never the request or its token."""

    def __init__(self, status_code: int):
        super().__init__(f"GitHub returned {status_code}")
        self.status_code = status_code


class StaleShaError(GitHubError):
    """PUT refused because FILE_PATH on BRANCH is no longer the version the sha names: someone committed since."""


def _headers(token: str) -> dict:
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}


def pull_qa_from_github() -> tuple[list[dict], str] | None:
    """(qa_pairs, blob sha) of FILE_PATH on BRANCH, or None without GITHUB_TOKEN. Raises on any other outcome
    (network, non-200, broken JSON, missing/empty `qa_pairs`), so the caller never takes a broken copy for the real one.

    JSON media type: the content comes with the sha a later PUT must name. Above 1 MB GitHub leaves `content` empty
    (encoding "none"; the file is ~100 KB): that raises too, instead of passing for an empty file."""
    token = settings.GITHUB_TOKEN
    if not token:
        return None
    resp = httpx.get(API_URL, headers=_headers(token), params={"ref": BRANCH}, timeout=PULL_TIMEOUT)
    if resp.status_code != 200:
        raise GitHubError(resp.status_code)
    meta = resp.json()
    if meta.get("encoding") != "base64":
        raise ValueError(f"file content not inlined (encoding {meta.get('encoding')!r})")
    data = json.loads(base64.b64decode(meta["content"]))
    qa_pairs = data.get("qa_pairs") if isinstance(data, dict) else None
    if not isinstance(qa_pairs, list) or not qa_pairs or not all(isinstance(p, dict) for p in qa_pairs):
        raise ValueError("qa_pairs is missing, empty or not a list of objects")
    return qa_pairs, meta["sha"]


def push_qa_to_github(qa_pairs: list[dict], sha: str) -> str:
    """Commit qa_pairs as FILE_PATH on BRANCH over the version `sha` ([skip deploy]); returns the new blob sha.
    Raises StaleShaError if BRANCH moved on since `sha` (409, or 422 for a sha GitHub does not know),
    GitHubError or an httpx error otherwise."""
    content = json.dumps({"qa_pairs": qa_pairs}, ensure_ascii=False, indent=2)
    resp = httpx.put(
        API_URL,
        headers=_headers(settings.GITHUB_TOKEN),
        json={
            "message": "[skip deploy] Auto-update Q&A database from admin reply",
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "sha": sha,
            "branch": BRANCH,
        },
        timeout=PUSH_TIMEOUT,
    )
    if resp.status_code in (409, 422):
        raise StaleShaError(resp.status_code)
    if resp.status_code not in (200, 201):
        raise GitHubError(resp.status_code)
    return resp.json()["content"]["sha"]
