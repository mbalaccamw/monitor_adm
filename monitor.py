# monitor.py — Multi-URL ADM monitor (GitHub Actions)
# - Controlla più pagine ADM (testo visibile + link PDF)
# - Stato separato per URL in: state/<slug>.json + riepilogo in state/combined_state.json
# - Invia un messaggio Telegram per ogni pagina che cambia
#
# Env richieste (GitHub Secrets nel workflow):
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
#
# Dipendenze: requests, beautifulsoup4

import os, sys, json, time, hashlib, re
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

URLS = [
    "https://www.adm.gov.it/portale/-/convocazioni-3",
    "https://www.adm.gov.it/portale/concorso-pubblico-a-complessivi-415-posti-area-assistenti-di-cui-10-riservati-alla-provincia-autonoma-di-bolzano-presso-l-agenzia-delle-dogane-e-dei-monopoli",
]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
TIMEOUT   = 25
STATE_DIR = "state"

KEYWORDS = ["graduatoria", "graduatorie", "vincitori", "scorrimento", "convocazione", "convocazioni", "esito"]

def slugify(url: str) -> str:
    p = urlparse(url)
    path = p.path.strip("/").replace("/", "-")
    base = f"{p.netloc}-{path}" if path else p.netloc
    base = re.sub(r"[^a-zA-Z0-9\-]+", "-", base).strip("-").lower()
    if len(base) > 120:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        base = base[:110] + "-" + h
    return base or "root"

def state_path_for(url: str) -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, slugify(url) + ".json")

def send_telegram(text: str) -> None:
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(api, data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}, timeout=15)
    r.raise_for_status()

def fetch_page(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ADM-Monitor/2.0"}
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text, r.url  # html e URL finale dopo redirect

def extract_signature(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = " ".join(soup.get_text(separator=" ").split())
    pdfs = []
    for a in soup.find_all("a", href=True):
        href_abs = urljoin(base_url, a["href"])
        if href_abs.lower().endswith(".pdf"):
            pdfs.append(href_abs)
    pdfs = sorted(set(pdfs))

    lowered = text.lower()
    found_keys = sorted({kw for kw in KEYWORDS if kw in lowered})

    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    pdfs_hash = hashlib.sha256(("\n".join(pdfs)).encode("utf-8")).hexdigest()
    combined  = hashlib.sha256((text_hash + "|" + pdfs_hash).encode("utf-8")).hexdigest()

    return {
        "text_hash": text_hash,
        "pdfs_hash": pdfs_hash,
        "combined_hash": combined,
        "pdfs": pdfs,
        "keywords": found_keys,
        "ts": int(time.time()),
        "final_url": base_url,
    }

def load_state(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_state(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def describe_diff(old, new):
    lines = []
    new_pdfs = sorted(set(new.get("pdfs", [])) - set(old.get("pdfs", [])))
    removed_pdfs = sorted(set(old.get("pdfs", [])) - set(new.get("pdfs", [])))
    new_keys = sorted(set(new.get("keywords", [])) - set(old.get("keywords", [])))

    if new_pdfs:
        lines.append("📄 Nuovi PDF:")
        lines += [f"- {u}" for u in new_pdfs[:10]]
        if len(new_pdfs) > 10:
            lines.append(f"... (+{len(new_pdfs)-10} altri)")
    if removed_pdfs:
        lines.append("🗑️ PDF rimossi:")
        lines += [f"- {u}" for u in removed_pdfs[:5]]
        if len(removed_pdfs) > 5:
            lines.append(f"... (+{len(removed_pdfs)-5} altri)")
    if new_keys:
        lines.append("🧭 Nuove parole chiave: " + ", ".join(new_keys))

    if not lines:
        lines.append("ℹ️ Contenuto variato (testo/link).")
    return "\n".join(lines)

def write_combined_state():
    combined = {}
    for fn in os.listdir(STATE_DIR):
        if not fn.endswith(".json") or fn == "combined_state.json":
            continue
        try:
            with open(os.path.join(STATE_DIR, fn), "r", encoding="utf-8") as f:
                data = json.load(f)
            url = data.get("final_url") or fn
            combined[url] = {
                "ts": data.get("ts"),
                "keywords": data.get("keywords", []),
                "pdfs": data.get("pdfs", []),
                "text_hash": data.get("text_hash"),
                "pdfs_hash": data.get("pdfs_hash"),
                "combined_hash": data.get("combined_hash"),
            }
        except Exception:
            pass
    with open(os.path.join(STATE_DIR, "combined_state.json"), "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    for url in URLS:
        spath = state_path_for(url)
        try:
            html, final_url = fetch_page(url)
        except Exception as e:
            # Avvisa ma continua con gli altri URL
            try:
                send_telegram(f"⚠️ ADM monitor: errore fetch\nURL: {url}\nDettagli: {e}")
            except Exception:
                pass
            print(f"[ERR] fetch: {url} -> {e}", file=sys.stderr)
            continue

        sig = extract_signature(html, final_url)
        old = load_state(spath)

        if not old:
            save_state(spath, sig)
            try:
                send_telegram("✅ Monitor attivato per:\n" + final_url)
            except Exception as e:
                print(f"[WARN] Telegram init failed ({url}): {e}", file=sys.stderr)
            print(f"[INFO] Baseline creata per {url}")
            continue

        if sig["combined_hash"] == old.get("combined_hash"):
            print(f"[OK] Nessuna modifica: {url}")
            continue

        diff_text = describe_diff(old, sig)
        msg = f"🔔 Pagina ADM aggiornata\n{final_url}\n\n{diff_text}"
        try:
            send_telegram(msg)
        finally:
            save_state(spath, sig)
            print(f"[INFO] Modifica rilevata e stato aggiornato per {url}")

    # Scrivi riepilogo combinato
    write_combined_state()

if __name__ == "__main__":
    main()
