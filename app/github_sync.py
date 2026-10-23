import base64
import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

REPO = "pichu124/casa_preschool-messenger-bot"
FILE_PATH = "data/qa_database.json"
BRANCH = "main"
# Q&A is loaded while the app starts: do not hold the start up for long if GitHub is slow.
PULL_TIMEOUT = 10


def pull_qa_from_github() -> list[dict] | None:
    """qa_pairs of FILE_PATH on BRANCH, or None without GITHUB_TOKEN. Raises on any other outcome (network,
    non-200, broken JSON, missing/empty `qa_pairs`), so the caller never takes a broken copy for the real one."""
    token = settings.GITHUB_TOKEN
    if not token:
        return None
    # Raw media type: the file body itself, whatever its size (the default JSON one has empty `content` above 1 MB).
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.raw+json",
    }
    api_url = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
    resp = httpx.get(api_url, headers=headers, params={"ref": BRANCH}, timeout=PULL_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub returned {resp.status_code}")
    data = json.loads(resp.content)
    qa_pairs = data.get("qa_pairs") if isinstance(data, dict) else None
    if not isinstance(qa_pairs, list) or not qa_pairs or not all(isinstance(p, dict) for p in qa_pairs):
        raise ValueError("qa_pairs is missing, empty or not a list of objects")
    return qa_pairs


async def push_qa_to_github(qa_pairs: list[dict]):
    """Push updated qa_database.json to GitHub."""
    token = settings.GITHUB_TOKEN
    if not token:
        logger.warning("GITHUB_TOKEN not set, skipping GitHub sync")
        return False

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_url = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"

    async with httpx.AsyncClient() as client:
        # 1. Get current file SHA (needed to update)
        resp = await client.get(api_url, headers=headers, params={"ref": BRANCH}, timeout=15)
        if resp.status_code == 200:
            current_sha = resp.json()["sha"]
        else:
            logger.error(f"Failed to get file SHA: {resp.status_code}")
            return False

        # 2. Encode new content
        content = json.dumps({"qa_pairs": qa_pairs}, ensure_ascii=False, indent=2)
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        # 3. Push update
        resp = await client.put(
            api_url,
            headers=headers,
            json={
                "message": "[skip deploy] Auto-update Q&A database from admin reply",
                "content": encoded,
                "sha": current_sha,
                "branch": BRANCH,
            },
            timeout=15,
        )

        if resp.status_code == 200:
            logger.info(f"Q&A database pushed to GitHub ({len(qa_pairs)} pairs)")
            return True
        else:
            logger.error(f"Failed to push to GitHub: {resp.status_code} {resp.text}")
            return False
