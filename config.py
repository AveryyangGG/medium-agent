import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Medium settings
MEDIUM_API_TOKEN = os.getenv("MEDIUM_API_TOKEN")
MEDIUM_COOKIES = os.getenv("MEDIUM_COOKIES", "")

# Telegram settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 管理員設定
ADMIN_USER_IDS = os.getenv("ADMIN_USER_IDS", "").split(",")

# Anthropic settings for summarization
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-7-sonnet-latest")

# Voyage AI settings
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-large-2")

# Database settings
DB_PATH = os.getenv("DB_PATH", "data/medium_articles.db")
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", "data/vector_db")

# Web app settings
WEB_APP_HOST = os.getenv("WEB_APP_HOST", "0.0.0.0")
WEB_APP_PORT = int(os.getenv("WEB_APP_PORT", "8000"))

# 可公開訪問的URL基礎路徑，用於生成Telegram連結按鈕
# 例如：https://your-domain.com 或 http://your-public-ip
PUBLIC_URL_BASE = os.getenv("PUBLIC_URL_BASE", "")

# Number of top articles to fetch daily
TOP_ARTICLES_COUNT = int(os.getenv("TOP_ARTICLES_COUNT", "5")) 