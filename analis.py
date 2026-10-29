"""Divisi Analis dan Telemetri: laporan mingguan dan pemeriksaan kesehatan sistem, dikirim ke Telegram."""
import glob
from datetime import datetime, timedelta, timezone

import requests

from autopilot import baca_stok
from bot_uploader import G, token_halaman
from lib import iso_now, muat_json, parse_iso, publish, redact, secret, simpan_json, telegram


def hitung(tok, vid):
    try:
        j = requests.get(f"{G}/{vid}", timeout=30, params={"access_token": tok,
                         "fields": "likes.summary(true).limit(0),comments.summary(true).limit(0)"}).json()
        return j.get("likes", {}).get("summary", {}).get("total_count", 0), j.get("comments", {}).get("summary", {}).get("total_count", 0)
    except requests.RequestException:
        return 0, 0


def token_berlaku(tok):
    app, sec = secret("FB_APP_ID"), secret("FB_APP_SECRET")
    if not app or not sec:
        return None
    try:
        d = requests.get(f"{G}/debug_token", timeout=30, params={"input_token": tok, "access_token": f"{app}|{sec}"}).json().get("data", {})
        if not d.get("is_valid", False):
            return "tidak valid"
        exp = d.get("expires_at", 0)
        return "tidak kedaluwarsa" if not exp else f"kedaluwarsa {datetime.fromtimestamp(exp, timezone.utc):%d %b %Y}"
    except requests.RequestException:
        return None


def main():
    pages, sekarang = muat_json("pages.json", {}), datetime.now(timezone.utc)
    jobs = [j for p in glob.glob("queue/*.json") if (j := muat_json(p))]
    minggu = [j for j in jobs if parse_iso(j.get("selesai") or j.get("dibuat") or iso_now()) > sekarang - timedelta(days=7)]
    tayang = [j for j in minggu if j.get("status") == "selesai"]
    gagal = [j for j in minggu if j.get("status") == "gagal"]
    per, peringatan, skor = {}, [], []
    for j in tayang:
        akun = pages.get(j.get("fanpage"))
        if not akun or not j.get("video_id"):
            continue
        try:
            suka, komen = hitung(token_halaman(akun), j["video_id"])
        except Exception as e:  # noqa: BLE001
            peringatan.append(f"{akun['nama']}: {redact(e)[:80]}")
            continue
        per.setdefault(j["fanpage"], {"nama": akun["nama"], "reel": 0, "suka": 0, "komentar": 0})
        per[j["fanpage"]]["reel"] += 1
        per[j["fanpage"]]["suka"] += suka
        per[j["fanpage"]]["komentar"] += komen
        skor.append((suka + 3 * komen, j.get("deskripsi", "")[:50], akun["nama"]))
    for key, akun in pages.items():
        if key in per:
            status = token_berlaku(token_halaman(akun))
            if status and status != "tidak kedaluwarsa":
                peringatan.append(f"Token {akun['nama']}: {status}")
        sisa = len(baca_stok(key))
        if sisa and sisa < 5:
            peringatan.append(f"Stok {akun['nama']} tinggal {sisa}")
    menunggu = sum(1 for j in jobs if j.get("status") == "menunggu_persetujuan")
    if menunggu:
        peringatan.append(f"{menunggu} draft menunggu persetujuan Anda")
    if tayang and len(gagal) / max(1, len(tayang) + len(gagal)) > 0.2:
        peringatan.append(f"Tingkat gagal tinggi: {len(gagal)} dari {len(tayang) + len(gagal)} tugas")
    baris = [f"📊 Laporan mingguan: {len(tayang)} reel tayang, {len(gagal)} gagal"]
    baris += [f"• {v['nama']}: {v['reel']} reel, {v['suka']} suka, {v['komentar']} komentar" for v in per.values()]
    if skor:
        baris.append("Terbaik: " + "; ".join(f"{n} ({t}...)" for _, t, n in sorted(skor, reverse=True)[:3]))
    baris += ["⚠️ " + w for w in peringatan]
    laporan = "\n".join(baris)
    simpan_json("laporan/terbaru.json", {"dibuat": iso_now(), "tayang": len(tayang), "gagal": len(gagal), "halaman": per, "peringatan": peringatan})
    telegram(laporan)
    publish("Laporan mingguan")
    print(laporan)


if __name__ == "__main__":
    main()
