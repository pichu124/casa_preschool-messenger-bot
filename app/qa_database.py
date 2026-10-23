import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

from app import github_sync

logger = logging.getLogger(__name__)


def _key(pair: dict) -> str:
    # JSON, not a tuple: a hand-edited pair with a list/dict answer must not crash startup on an unhashable key.
    return json.dumps([pair.get("questions") or [], pair.get("answer")], sort_keys=True, ensure_ascii=False)


def _reason(e: Exception) -> str:
    """What went wrong, without str(e): httpx/h11 errors can quote the request, Authorization header included."""
    status = getattr(e, "status_code", None)
    return f"{type(e).__name__} {status}" if status else type(e).__name__


class QADatabase:
    """Q&A pairs. With GITHUB_TOKEN the copy on GitHub main is the real one: the disk only has the copy baked into
    the last deploy, and admins teach pairs since (pushed to main with [skip deploy])."""

    def __init__(self, path: str = "data/qa_database.json"):
        self.path = path
        self.qa_pairs: list[dict] = []
        # Blob sha of the file on main as last pulled or pushed. None: main not read yet, so never push (a stale
        # disk copy would overwrite the pairs learned on main).
        self._base_sha: str | None = None
        # Pairs taught here that main is not known to have: merged into every pull, kept until a push succeeds.
        self._unpushed: list[dict] = []
        # Load, reload and push run in worker threads (asyncio.to_thread) and may overlap.
        self._lock = threading.RLock()
        self.load()

    def load(self):
        """Pull main (plus the pairs not pushed yet) and write it to disk, then push those pairs if any. If the pull
        fails: a process that has pulled before keeps its memory (main as it was then, plus what it learned); one that
        never has uses the disk copy, and pushes nothing until a pull succeeds. Without GITHUB_TOKEN: the disk copy."""
        with self._lock:
            pulled = self._pull()
            if pulled:
                self._push()
            elif pulled is None or self._base_sha is None:
                self._read_disk()
                if pulled is False:
                    logger.error("Using the disk copy of Q&A: taught pairs are not pushed to GitHub until a pull succeeds")
            else:
                logger.error(f"Keeping the {len(self.qa_pairs)} Q&A pairs in memory (GitHub main as last pulled)")

    def reload(self):
        """Reload database, from GitHub as in load() (useful for hot-reload)."""
        self.load()

    def _merged(self, pairs: list[dict]) -> list[dict]:
        known = {_key(p) for p in pairs}
        return pairs + [p for p in self._unpushed if _key(p) not in known]

    def _pull(self) -> bool | None:
        """qa_pairs = main plus the unpushed pairs main lacks, saved to disk. True on success, None without
        GITHUB_TOKEN, False if the pull failed (logged)."""
        try:
            pulled = github_sync.pull_qa_from_github()
        except Exception as e:
            logger.error(f"Failed to load Q&A from GitHub ({_reason(e)})")
            return False
        if pulled is None:
            return None
        remote, self._base_sha = pulled
        known = {_key(p) for p in remote}
        self._unpushed = [p for p in self._unpushed if _key(p) not in known]
        self.qa_pairs = self._merged(remote)
        self.save()
        logger.info(f"Loaded {len(remote)} Q&A pairs from GitHub ({len(self._unpushed)} taught here not pushed yet)")
        return True

    def _read_disk(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pairs = data.get("qa_pairs", [])
            logger.info(f"Loaded {len(pairs)} Q&A pairs from disk ({self.path})")
        except FileNotFoundError:
            logger.warning(f"Q&A database not found at {self.path}, starting empty")
            pairs = []
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {self.path}: {e}")
            pairs = []
        self.qa_pairs = self._merged(pairs)

    def _push(self):
        """Commit qa_pairs to main if it holds unpushed pairs. Main moved on since the last pull (a manual commit,
        another instance during a deploy): pull, merge the unpushed pairs into it and retry once."""
        for attempt in range(2):
            if attempt or self._base_sha is None:
                pulled = self._pull()
                if pulled is None:
                    logger.warning("GITHUB_TOKEN not set: Q&A kept on local disk only")
                    return
                if not pulled:
                    break
            if not self._unpushed:
                return
            try:
                self._base_sha = github_sync.push_qa_to_github(self.qa_pairs, self._base_sha)
            except github_sync.StaleShaError:
                continue
            except Exception as e:
                logger.error(f"Failed to push Q&A to GitHub ({_reason(e)})")
                break
            self._unpushed = []
            logger.info(f"Q&A database pushed to GitHub ({len(self.qa_pairs)} pairs)")
            return
        logger.error(
            f"{len(self._unpushed)} taught Q&A pairs not pushed to GitHub: kept in memory and on disk, "
            "retried on the next taught pair or /reload-qa (lost on restart until then)"
        )

    def import_from_excel(self, excel_path: str):
        """Import Q&A pairs from Excel file.

        Expected columns: category | question | answer | keywords
        Multiple questions for same answer can be on separate rows with same category.
        """
        wb = openpyxl.load_workbook(excel_path, read_only=True)
        ws = wb.active

        pairs_by_category: dict[str, dict] = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            category = str(row[0]).strip()
            question = str(row[1]).strip() if row[1] else ""
            answer = str(row[2]).strip() if row[2] else ""
            keywords_str = str(row[3]).strip() if len(row) > 3 and row[3] else ""
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

            if category in pairs_by_category:
                if question:
                    pairs_by_category[category]["questions"].append(question)
                if answer:
                    pairs_by_category[category]["answer"] = answer
                if keywords:
                    pairs_by_category[category]["keywords"].extend(keywords)
            else:
                pairs_by_category[category] = {
                    "category": category,
                    "questions": [question] if question else [],
                    "answer": answer,
                    "keywords": keywords,
                }

        wb.close()
        self.qa_pairs = list(pairs_by_category.values())
        self.save()
        logger.info(f"Imported {len(self.qa_pairs)} Q&A pairs from {excel_path}")

    def save(self):
        """Save current Q&A pairs to JSON file."""
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"qa_pairs": self.qa_pairs}, f, ensure_ascii=False, indent=2)

    async def add_qa_pair(
        self,
        category: str,
        questions: str | list[str],
        answer: str,
        keywords: list[str] | None = None,
        source: str | None = None,
    ):
        """Add a new Q&A pair, save locally, and push it to GitHub main (in a worker thread).

        source (vd "admin") đánh dấu nguồn của cặp, kèm learned_at theo UTC.
        """
        if isinstance(questions, str):
            questions = [questions]
        pair = {
            "category": category,
            "questions": questions,
            "answer": answer,
            "keywords": keywords or [],
        }
        if source:
            pair["source"] = source
            pair["learned_at"] = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(self._add, pair)
        logger.info(f"Added new Q&A: [{category}] {' / '.join(questions)[:50]}...")

    def _add(self, pair: dict):
        with self._lock:
            self.qa_pairs.append(pair)
            self._unpushed.append(pair)
            self.save()
            self._push()

    def build_context(self) -> str:
        """Build a context string from all Q&A pairs for the AI prompt."""
        if not self.qa_pairs:
            return "Chua co du lieu cau hoi/tra loi nao trong he thong."

        lines = []
        for i, pair in enumerate(self.qa_pairs, 1):
            category = pair.get("category", "")
            questions = pair.get("questions", [])
            answer = pair.get("answer", "")
            images = pair.get("images", [])
            q_text = " / ".join(questions)
            entry = f"{i}. [{category}] Q: {q_text}\n   A: {answer}"
            if images:
                entry += f"\n   Images: {','.join(images)}"
            lines.append(entry)

        return "\n\n".join(lines)
