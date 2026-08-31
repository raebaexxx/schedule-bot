import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_TOKEN_ALL = os.getenv("BOT_TOKEN_ALL", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
