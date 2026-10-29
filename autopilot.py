"""Autopilot: menyiapkan tugas Reels dari stok tiap fanpage sesuai jam rutin.
Dijalankan harian oleh GitHub Actions. Hasilnya masuk antrean (queue/) untuk disetujui atau langsung tayang."""
import glob, hashlib, json, os, random, re
from datetime import datetime, timedelta, timezone

import requests

import kepatuhan
import shopee
from lib import WIB, iso_now, muat_json, parse_iso, publish, redact, secret, simpan_json, telegram

KONFIG = muat_json("autopilot.json", {})
PAGES = muat_json("pages.json", {})
AI = KONFIG.get("ai", {})
MODEL = AI.get("model", "claude-haiku-5-5")
SISA_AI = [int(AI.get("maks_panggilan_per_run", 12)) if AI.get("aktif") else 0]


def baca_stok(key):
    """Format baris di stok/KEY.txt:  link_video | judul | link_produk_shopee(opsional)
    atau  gambar: link1, link2, link3 | judul | link_produk(opsional)"""
    item = []
    try:
        with open(f"stok/{key}.txt", encoding="utf-8") as f:
            for baris in f:
                baris = baris.strip()
                if not baris or baris.startswith("#"):
                    continue
                bagian = [b.strip() for b in baris.split("|")] + ["", ""]
                render = bagian[0].lower().startswith("gambar:")
                sumber = bagian[0][7:].strip() if render else bagian[0]
                item.append({"hash": hashlib.sha1(baris.encode()).hexdigest()[:12], "render": render,
                             "sumber": [s.strip() for s in sumber.split(",") if s.strip()] if render else sumber,
                             "judul": bagian[1] or "Video pilihan", "produk": bagian[2]})
    except OSError:
        pass
    return item


def ai_json(prompt):
    key = secret("ANTHROPIC_API_KEY")
    if not key or SISA_AI[0] <= 0:
        return None
    SISA_AI[0] -= 1
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, json={
            "model": MODEL, "max_tokens": 700, "messages": [{"role": "user", "content": prompt}]},
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        r.raise_for_status()
        teks = "".join(b.get("text", "") for b in r.json().get("content", []))
        return json.loads(teks[teks.index("{"): teks.rindex("}") + 1])
    except Exception as e:  # noqa: BLE001
        print("AI gagal:", redact(e)[:120])
        return None


def tulis(cfg, item, umpan=""):
    prompt = (f"Kamu Sari, copywriter reel Facebook berbahasa Indonesia. Gaya: {cfg.get('gaya', 'santai dan ramah')}. "
              f"Tema halaman: {cfg.get('tema', 'umum')}. Judul video: {item['judul']}. "
              "Tulis deskripsi singkat (maksimal 300 karakter, kalimat pertama berupa hook), 5 sampai 8 tagar tanpa tanda #, "
              "dan komentar pertama 1 sampai 2 kalimat berisi ajakan. Dilarang: klaim berlebihan (pasti untung, dijamin, 100 persen), "
              "klaim kesehatan, mengaku produk milik sendiri, atau menyebut link. "
              + (f"Perbaiki sesuai catatan ini: {umpan}. " if umpan else "")
              + 'Balas HANYA JSON: {"deskripsi":"","tagar":[],"komentar":"","slide":["teks pendek per gambar"]}')
    return ai_json(prompt)


def nilai(hasil):
    j = ai_json("Nilai draft reel ini 1-100 (hook kuat 25, manfaat jelas 20, sesuai produk nyata 20, tidak berlebihan atau menyesatkan 20, "
                'ajakan jelas 15). Balas HANYA JSON {"skor":0,"alasan":"satu kalimat"}. Draft: ' + json.dumps(hasil, ensure_ascii=False))
    return (int(j.get("skor", 0)), j.get("alasan", "")) if j else (None, "")


def susun(cfg, item):
    hasil, skor = tulis(cfg, item), None
    if hasil:
        skor, alasan = nilai(hasil)
        if skor is not None and skor < 75:
            hasil = tulis(cfg, item, alasan) or hasil
            skor = f"{skor}, direvisi"
    if not hasil:  # cadangan tanpa AI
        hasil = {"deskripsi": f"{item['judul']}\n\nTonton sampai habis ya!", "tagar": [], "komentar": cfg.get("komentar_default", "Yuk cek detailnya di sini."),
                 "slide": [item["judul"]]}
    hasil["tagar"] = list(dict.fromkeys([t.lstrip("#") for t in cfg.get("tagar_tetap", []) + hasil.get("tagar", []) if t]))[:12]
    return hasil, skor


def slot_berikut(jam_list, sekarang):
    hasil = set()
    for hari in range(3):
        tgl = (sekarang.astimezone(WIB) + timedelta(days=hari)).date()
        for jam in jam_list:
            h, m = map(int, jam.split(":"))
            dt = datetime(tgl.year, tgl.month, tgl.day, h, m, tzinfo=WIB).astimezone(timezone.utc)
            if sekarang + timedelta(hours=1) <= dt <= sekarang + timedelta(hours=30):
                hasil.add(dt)
    return sorted(hasil)


def main():
    sekarang = datetime.now(timezone.utc)
    antrean = [j for p in glob.glob("queue/*.json") if (j := muat_json(p))]
    ada = {j.get("kunci") for j in antrean}
    terpakai = muat_json("state/terpakai.json", {})
    dibuat = 0
    for key, cfg in KONFIG.get("halaman", {}).items():
        if not cfg.get("aktif") or key not in PAGES:
            continue
        stok = [s for s in baca_stok(key) if s["hash"] not in terpakai.get(key, [])]
        habis = False
        riwayat = [j.get("deskripsi", "") for j in antrean if j.get("fanpage") == key][-20:]
        for slot in slot_berikut(cfg.get("jam", []), sekarang):
            kunci = f"{key}:{slot:%Y%m%d%H%M}"
            hari_ini = [j for j in antrean if j.get("fanpage") == key and j.get("status") not in ("ditolak", "kedaluwarsa")
                        and parse_iso(j["jadwal"]).astimezone(WIB).date() == slot.astimezone(WIB).date()]
            if kunci in ada or len(hari_ini) >= int(cfg.get("maks_per_hari", 3)):
                continue
            if not stok:
                telegram(f"⚠️ Stok video {PAGES[key]['nama']} habis. Tambahkan baris di stok/{key}.txt")
                habis = True
                break
            item = stok.pop(0)
            terpakai.setdefault(key, []).append(item["hash"])
            hasil, skor = susun(cfg, item)
            link = cfg.get("link_default", "")
            if item["produk"]:
                try:
                    link = shopee.short_link(item["produk"], [f"{key[:12]}{slot:%d%H%M}"])
                except Exception as e:  # noqa: BLE001
                    print("Short link gagal:", redact(e)[:120])
                    link = item["produk"] if cfg.get("pakai_link_asli") else link
            j = {"id": f"{sekarang:%Y%m%d%H%M%S}-{key[:8].lower()}-{random.randint(100, 999)}", "kunci": kunci, "asal": "autopilot",
                 "fanpage": key, "deskripsi": hasil["deskripsi"], "tagar": hasil["tagar"], "redirect_link": link,
                 "link_di": cfg.get("link_di", "komentar"), "komentar": hasil.get("komentar", ""), "jadwal": slot.isoformat(timespec="seconds"),
                 "petugas": cfg.get("petugas", "Budi"), "skor": skor, "dibuat": iso_now(), "percobaan": 0,
                 "status": "menunggu_persetujuan" if cfg.get("persetujuan", True) else "menunggu"}
            if item["render"]:
                j["render"] = {"gambar": item["sumber"], "teks": hasil.get("slide", []), "detik": cfg.get("detik_per_slide", 3)}
            else:
                j["gdrive_link"] = item["sumber"]
            masalah = kepatuhan.periksa(j, riwayat)
            if masalah:
                telegram(f"🚫 Kepatuhan menolak draft {PAGES[key]['nama']}: {'; '.join(masalah)[:300]}")
                continue
            simpan_json(f"queue/{j['id']}.json", j)
            antrean.append(j)
            ada.add(kunci)
            riwayat.append(j["deskripsi"])
            dibuat += 1
            pesan = f"📝 Draft untuk {PAGES[key]['nama']}\nTayang: {slot.astimezone(WIB):%d %b %H:%M} WIB\nSkor: {skor}\n\n{j['deskripsi'][:500]}"
            if j["status"] == "menunggu_persetujuan":
                telegram(pesan, [[{"text": "Setuju", "callback_data": "ok:" + j["id"]}, {"text": "Tolak", "callback_data": "no:" + j["id"]}]])
            else:
                telegram(pesan)
        if not habis and len(stok) < 5:
            telegram(f"ℹ️ Stok {PAGES[key]['nama']} tinggal {len(stok)} item.")
    simpan_json("state/terpakai.json", terpakai)
    publish(f"Autopilot: {dibuat} tugas baru")
    print(f"{dibuat} tugas dibuat.")


if __name__ == "__main__":
    main()
