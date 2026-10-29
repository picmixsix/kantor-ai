"""Fungsi bersama untuk semua bot kantor-ai."""
import json, os, re, subprocess, time
from datetime import datetime, timedelta, timezone

import requests

WIB = timezone(timedelta(hours=7))

try:
    ALL = json.loads(os.getenv("ALL_SECRETS") or "{}")
except ValueError:
    ALL = {}
RAHASIA = [v for v in ALL.values() if isinstance(v, str) and len(v) >= 8]


def secret(nama, default=""):
    return ALL.get(nama) or os.getenv(nama) or default


def redact(teks):
    teks = str(teks)
    for s in RAHASIA:
        teks = teks.replace(s, "***")
    return teks


def sh(*a, check=True):
    return subprocess.run(a, check=check, capture_output=True, text=True)


def publish(pesan, folder=("queue", "state", "laporan")):
    """Simpan perubahan ke repo (aman terhadap tabrakan dengan panel)."""
    ada = [f for f in folder if os.path.isdir(f)]
    if not ada:
        return
    sh("git", "add", *ada)
    if sh("git", "diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    sh("git", "commit", "-m", pesan)
    for _ in range(3):
        sh("git", "pull", "--rebase", "--autostash", check=False)
        if sh("git", "push", check=False).returncode == 0:
            return
        time.sleep(3)


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(s):
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def drive_id(url):
    m = re.search(r"/d/([\w-]{10,})", url or "") or re.search(r"[?&]id=([\w-]{10,})", url or "")
    return m.group(1) if m else None


def muat_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def simpan_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def telegram(teks, tombol=None):
    """Kirim pesan ke Telegram Anda. Diam saja jika Telegram belum diatur."""
    tok, chat = secret("TELEGRAM_TOKEN"), secret("TELEGRAM_CHAT")
    if not tok or not chat:
        return False
    payload = {"chat_id": chat, "text": teks[:3900], "disable_web_page_preview": True}
    if tombol:
        payload["reply_markup"] = {"inline_keyboard": tombol}
    try:
        return requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json=payload, timeout=20).ok
    except requests.RequestException:
        return False
