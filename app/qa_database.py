import json
import logging
from pathlib import Path

import openpyxl

logger = logging.getLogger(__name__)


class QADatabase:
    def __init__(self, path: str = "data/qa_database.json"):
        self.path = path
        self.qa_pairs: list[dict] = []
        self.load()

    def load(self):
        """Load Q&A pairs from JSON file."""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.qa_pairs = data.get("qa_pairs", [])
            logger.info(f"Loaded {len(self.qa_pairs)} Q&A pairs from {self.path}")
        except FileNotFoundError:
            logger.warning(f"Q&A database not found at {self.path}, starting empty")
            self.qa_pairs = []
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {self.path}: {e}")
            self.qa_pairs = []

    def reload(self):
        """Reload database from file (useful for hot-reload)."""
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

    async def add_qa_pair(self, category: str, questions: str | list[str], answer: str, keywords: list[str] | None = None):
        """Add a new Q&A pair, save locally, and sync to GitHub."""
        if isinstance(questions, str):
            questions = [questions]
        self.qa_pairs.append({
            "category": category,
            "questions": questions,
            "answer": answer,
            "keywords": keywords or [],
        })
        self.save()

        # Sync to GitHub so data persists across deploys
        from app.github_sync import push_qa_to_github
        await push_qa_to_github(self.qa_pairs)

        logger.info(f"Added new Q&A: [{category}] {question[:50]}...")

    def build_context(self) -> str:
        """Build a context string from all Q&A pairs for the AI prompt."""
        if not self.qa_pairs:
            return "Chua co du lieu cau hoi/tra loi nao trong he thong."

        lines = []
        for i, pair in enumerate(self.qa_pairs, 1):
            category = pair.get("category", "")
            questions = pair.get("questions", [])
            answer = pair.get("answer", "")
            q_text = " / ".join(questions)
            lines.append(f"{i}. [{category}] Q: {q_text}\n   A: {answer}")

        return "\n\n".join(lines)
