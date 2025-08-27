# monitor.py (minimal ping)
import os, requests
token = os.environ["TELEGRAM_BOT_TOKEN"]
chat  = os.environ["TELEGRAM_CHAT_ID"]
msg   = "🔧 GitHub Actions is set up. I'll add the real monitor next."
r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  data={"chat_id": chat, "text": msg, "disable_web_page_preview": True})
r.raise_for_status()
