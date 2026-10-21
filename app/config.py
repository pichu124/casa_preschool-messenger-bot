import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Facebook Messenger
    FB_PAGE_ACCESS_TOKEN: str = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
    FB_VERIFY_TOKEN: str = os.getenv("FB_VERIFY_TOKEN", "")
    FB_APP_SECRET: str = os.getenv("FB_APP_SECRET", "")

    # Admin escalation via Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

    # Leads -> Google Sheet: Apps Script web app URL (docs/google-sheet-leads.md); empty = Telegram only
    LEADS_SHEET_WEBHOOK_URL: str = os.getenv("LEADS_SHEET_WEBHOOK_URL", "")
    # Sent in the JSON body (Apps Script cannot read request headers); must equal the script's LEADS_TOKEN
    LEADS_SHEET_TOKEN: str = os.getenv("LEADS_SHEET_TOKEN", "")

    # Follow-up message to parents who went quiet (app/followup.py); off unless set to "true"
    FOLLOWUP_ENABLED: bool = os.getenv("FOLLOWUP_ENABLED", "").strip().lower() == "true"

    # GitHub auto-sync
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    # owner/name of a PRIVATE repo for data/customers.json; empty = keep customer data on local disk only
    CUSTOMERS_GITHUB_REPO: str = os.getenv("CUSTOMERS_GITHUB_REPO", "")

    # AI Model API Keys
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Model IDs; defaults replace models the providers retired (see README "Model AI")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o-mini"
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "").strip() or "openai/gpt-oss-120b"
    # Used by provider "groq_llama" in AI_MODEL_ORDER (name kept for existing deployments)
    GROQ_SECOND_MODEL: str = os.getenv("GROQ_SECOND_MODEL", "").strip() or "qwen/qwen3.8-27b"
    MISTRAL_MODEL: str = os.getenv("MISTRAL_MODEL", "").strip() or "mistral-small-latest"
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "").strip() or "deepseek-flash"
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.5-flash"

    # AI Model fallback order
    AI_MODEL_ORDER: list[str] = os.getenv("AI_MODEL_ORDER", "openai,groq,gemini,mistral,deepseek").split(",")

    # Confidence threshold for escalation
    CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))

    # Facebook Graph API
    FB_GRAPH_API_URL: str = "https://graph.facebook.com/v21.0"

    # Public base URL where this app is reachable (used for webhook registration)
    PUBLIC_BASE_URL: str = os.getenv(
        "PUBLIC_BASE_URL",
        "https://casa-preschool-messenger-bot.onrender.com",
    )

    # Q&A Database path
    QA_DATABASE_PATH: str = os.getenv("QA_DATABASE_PATH", "data/qa_database.json")

    # Analytics log path
    ANALYTICS_LOG_PATH: str = os.getenv("ANALYTICS_LOG_PATH", "data/analytics.jsonl")


settings = Settings()
