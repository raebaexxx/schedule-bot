import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_TOKEN_ALL = os.getenv("BOT_TOKEN_ALL", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
if not ADMIN_IDS:
    ADMIN_IDS = {579546093}  # владелец проекта
BOT_VERSION = os.getenv("BOT_VERSION", "2.0")
