import base64
import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

REPO = "pichu124/casa_preschool-messenger-bot"
FILE_PATH = "data/qa_database.json"
BRANCH = "main"


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
                "message": "Auto-update Q&A database from admin reply",
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
