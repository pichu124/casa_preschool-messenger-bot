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

    # AI Model API Keys
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # AI Model fallback order
    AI_MODEL_ORDER: list[str] = os.getenv("AI_MODEL_ORDER", "openai,groq,gemini,mistral,deepseek").split(",")

    # Confidence threshold for escalation
    CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))

    # Facebook Graph API
    FB_GRAPH_API_URL: str = "https://graph.facebook.com/v21.0"

    # Q&A Database path
    QA_DATABASE_PATH: str = os.getenv("QA_DATABASE_PATH", "data/qa_database.json")


settings = Settings()
