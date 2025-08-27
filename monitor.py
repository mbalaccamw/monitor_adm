# monitor.py — ADM convocazioni monitor (GitHub Actions)
# - Controlla https://www.adm.gov.it/portale/-/convocazioni-3
# - Rileva QUALSIASI modifica al testo visibile o ai link PDF
# - Invia alert su Telegram
# - Salva un piccolo stato in repo: state/adm_state.json (così i run futuri vedono se è cambiato)

import os, sys, json, time, hashlib
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

URL = "https://www.adm.gov.it/portale/-/convocazioni-3"
STATE_PATH = os.environ.get("STATE_PATH", "state/adm_state.json")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
TIMEOUT = 25

def send_telegram(text: str) -> None:
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(api, data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}, timeout=15)
    r.raise_for_status()

def fetch_page(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ADM-Monitor/1.0"}
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text, r.url  # html e URL finale dopo eventuali redirect

def extract_signature(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    # Rimuovi elementi volatili
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())

    # Elenco PDF assoluti
    pdfs = []
    for a in soup.find_all("a", href=True):
        href_abs = urljoin(base_url, a["href"])
        if href_abs.lower().endswith(".pdf"):
            pdfs.append(href_abs)
    pdfs = sorted(set(pdfs))

    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    pdfs_hash = hashlib.sha256(("\n".join(pdfs)).encode("utf-8")).hexdigest()
    combined  = hashlib.sha256((text_hash + "|" + pdfs_hash).encode("utf-8")).hexdigest()
    return {"text_hash": text_hash, "pdfs_hash": pdfs_hash, "combined_hash": combined, "pdfs": pdfs, "ts": int(time.time())}

def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_state(sig) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(sig, f, ensure_ascii=False, indent=2)

def main():
    try:
        html, final_url = fetch_page(URL)
    except Exception as e:
        # Se la pagina non è raggiungibile, avvisa (puoi commentare se non vuoi alert in caso d’errore)
        try:
            send_telegram(f"⚠️ ADM monitor: errore fetch pagina: {e}")
        except Exception:
            pass
        print(f"[ERR] fetch: {e}", file=sys.stderr)
        sys.exit(0)

    sig = extract_signature(html, final_url)
    old = load_state()

    if not old:
        save_state(sig)
        try:
            send_telegram("✅ ADM monitor attivato. Ti avviserò per qualsiasi modifica.\nPagina: " + final_url)
        except Exception as e:
            print(f"[WARN] Telegram init failed: {e}", file=sys.stderr)
        print("[INFO] Stato inizializzato (prima esecuzione).")
        return

    changed = sig["combined_hash"] != old.get("combined_hash")
    if not changed:
        print("[OK] Nessuna modifica.")
        return

    new_pdfs = sorted(set(sig["pdfs"]) - set(old.get("pdfs", [])))
    lines = ["🔔 La pagina ADM è cambiata.", f"Pagina: {final_url}"]
    if new_pdfs:
        lines.append("📄 Nuovi PDF:")
        lines += [f"- {u}" for u in new_pdfs]
    else:
        lines.append("ℹ️ Nessun nuovo PDF, ma il contenuto è variato.")

    msg = "\n".join(lines)
    try:
        send_telegram(msg)
    finally:
        save_state(sig)
        print("[INFO] Modifica rilevata e stato aggiornato.")

if __name__ == "__main__":
    main()
