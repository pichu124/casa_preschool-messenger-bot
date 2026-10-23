import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

from app.github_sync import pull_qa_from_github

logger = logging.getLogger(__name__)


class QADatabase:
    def __init__(self, path: str = "data/qa_database.json"):
        self.path = path
        self.qa_pairs: list[dict] = []
        self.load()

    def load(self):
        """Load Q&A pairs. With GITHUB_TOKEN, the copy on GitHub main wins over the disk copy (the one baked into
        the last deploy, which misses the pairs admins taught since: those are pushed with [skip deploy]) and is
        written to disk. If the pull fails, the disk copy is used and pushing stays off until the next successful
        load, so the possibly stale disk copy never overwrites the pairs learned on main."""
        try:
            remote = pull_qa_from_github()
        except Exception as e:
            remote = None
            self._pull_failed = True
            logger.error(
                f"Failed to load Q&A from GitHub ({type(e).__name__}: {e}): using the disk copy, "
                "GitHub sync for Q&A is OFF until the next successful load (restart or /reload-qa)"
            )
        else:
            self._pull_failed = False
        if remote is not None:
            self.qa_pairs = remote
            self.save()
            logger.info(f"Loaded {len(self.qa_pairs)} Q&A pairs from GitHub")
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.qa_pairs = data.get("qa_pairs", [])
            logger.info(f"Loaded {len(self.qa_pairs)} Q&A pairs from disk ({self.path})")
        except FileNotFoundError:
            logger.warning(f"Q&A database not found at {self.path}, starting empty")
            self.qa_pairs = []
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {self.path}: {e}")
            self.qa_pairs = []

    def reload(self):
        """Reload database, from GitHub as in load() (useful for hot-reload)."""
        self.load()

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
        """Add a new Q&A pair, save locally, and sync to GitHub.

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
        self.qa_pairs.append(pair)
        self.save()

        # Sync to GitHub so data persists across deploys and restarts
        from app.github_sync import push_qa_to_github
        if self._pull_failed:
            logger.error("Skipping GitHub sync for Q&A: loading from GitHub failed (restart or /reload-qa to retry)")
        else:
            try:
                await push_qa_to_github(self.qa_pairs)
            except Exception as e:
                logger.warning(f"GitHub sync failed but local save succeeded: {e}")

        logger.info(f"Added new Q&A: [{category}] {' / '.join(questions)[:50]}...")

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
