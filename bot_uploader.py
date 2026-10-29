"""Bot Auto Uploader FB Reels v2.
Membaca antrean di queue/, mengunggah tugas yang sudah waktunya, mengomentari, mencoba ulang jika gagal,
menandai tugas yang kedaluwarsa atau macet, lalu menyimpan status ke repo."""
import glob, os, tempfile, time
from datetime import datetime, timedelta, timezone

import requests

from kepatuhan import LABEL
from lib import RAHASIA, WIB, drive_id, iso_now, muat_json, parse_iso, publish, redact, secret, simpan_json, telegram

G = f"https://graph.facebook.com/{os.getenv('FB_VER', 'v25.0')}"
MAKS_PER_RUN, MAKS_PER_HARI, MAKS_ULANG, SIMPAN_HARI = 3, 25, 2, 30
FINAL = ("selesai", "gagal", "ditolak", "kedaluwarsa")


def cek(r):
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code >= 400 or "error" in j:
        e = j.get("error", {})
        raise RuntimeError(f"Facebook {r.status_code}: {e.get('message', r.text[:200])}")
    return j


def token_halaman(akun):
    tok = secret(akun["secret_key"])
    if not tok:
        raise RuntimeError(f"Secret {akun['secret_key']} belum diisi di GitHub Secrets")
    try:  # token pengguna -> ambil token halaman; token halaman -> pakai apa adanya
        baru = requests.get(f"{G}/{akun['page_id']}", params={"fields": "access_token", "access_token": tok}, timeout=30).json().get("access_token")
        if baru:
            RAHASIA.append(baru)
        return baru or tok
    except requests.RequestException:
        return tok


def _link(j):
    return f"{LABEL}: {j['redirect_link'].strip()}" if j.get("redirect_link") else ""


def caption(j):
    bagian = [j.get("deskripsi", "").strip()]
    if j.get("link_di") in ("deskripsi", "keduanya"):
        bagian.append(_link(j))
    tagar = " ".join("#" + t.lstrip("#") for t in j.get("tagar", []) if t.strip())
    return "\n\n".join(b for b in bagian + [tagar] if b)


def komentar(j):
    bagian = [j.get("komentar", "").strip()]
    if j.get("link_di") in ("komentar", "keduanya"):
        bagian.append(_link(j))
    return "\n".join(b for b in bagian if b)


def siapkan_video(j, folder):
    f = os.path.join(folder, "video.mp4")
    if j.get("render"):
        import render_video
        return render_video.buat(j["render"], f)
    if j.get("video_url"):
        with requests.get(j["video_url"], stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(f, "wb") as out:
                for blok in r.iter_content(1 << 20):
                    out.write(blok)
        return f
    fid = drive_id(j.get("gdrive_link", ""))
    if not fid:
        raise RuntimeError("Link Google Drive tidak dikenali")
    import gdown
    if not gdown.download(id=fid, output=f, quiet=True) or os.path.getsize(f) < 1000:
        raise RuntimeError("Gagal mengunduh dari Google Drive. Pastikan aksesnya: siapa saja yang memiliki link")
    return f


def upload(page_id, tok, path, teks, komen):
    j = cek(requests.post(f"{G}/{page_id}/video_reels", data={"upload_phase": "start", "access_token": tok}, timeout=60))
    vid, url = j["video_id"], j["upload_url"]
    with open(path, "rb") as f:
        cek(requests.post(url, headers={"Authorization": "OAuth " + tok, "offset": "0", "file_size": str(os.path.getsize(path))}, data=f, timeout=900))
    fin = cek(requests.post(f"{G}/{page_id}/video_reels", data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                                               "description": teks, "access_token": tok}, timeout=60))
    hasil = {"video_id": vid}  # mulai dari sini reel dianggap tayang: kegagalan berikutnya tidak boleh memicu unggah ulang
    try:
        for _ in range(20):
            s = requests.get(f"{G}/{vid}", params={"fields": "status", "access_token": tok}, timeout=30).json().get("status", {})
            if s.get("video_status") == "ready" or s.get("publishing_phase", {}).get("status") == "complete":
                break
            if s.get("video_status") == "error":
                raise RuntimeError("Facebook gagal memproses video: " + redact(str(s))[:150])
            time.sleep(15)
        if komen:
            hasil["komentar_ok"] = False
            for _ in range(6):
                for target in [vid] + [x for x in (fin.get("post_id"), f"{page_id}_{vid}") if x]:
                    r = requests.post(f"{G}/{target}/comments", data={"message": komen, "access_token": tok}, timeout=30)
                    if r.status_code < 400:
                        hasil["komentar_ok"] = True
                        return hasil
                    hasil["komentar_galat"] = redact(r.text)[:200]
                time.sleep(20)
            hasil["catatan"] = "Reel tayang, tetapi komentar pertama gagal: " + hasil.get("komentar_galat", "")
    except Exception as e:  # noqa: BLE001
        hasil["catatan"] = "Reel tayang, tetapi langkah lanjutan gagal: " + redact(e)[:150]
    return hasil


def simpan(p, j, pesan):
    simpan_json(p, j)
    publish(pesan)


def kerjakan(p, j, pages):
    petugas, nama = j.get("petugas", "Budi"), (pages.get(j.get("fanpage")) or {}).get("nama", j.get("fanpage"))
    print(f"{petugas} mengerjakan {os.path.basename(p)}")
    j.update(status="memproses", mulai=iso_now())
    simpan(p, j, f"{petugas} mulai mengunggah")  # ditandai dulu agar tidak terunggah dua kali
    try:
        akun = pages.get(j.get("fanpage"))
        if not akun:
            raise RuntimeError(f"Fanpage '{j.get('fanpage')}' tidak ada di pages.json")
        video = siapkan_video(j, tempfile.mkdtemp())
        j.update(upload(akun["page_id"], token_halaman(akun), video, caption(j), komentar(j)), status="selesai")
        j["selesai"] = iso_now()
        telegram(f"✅ {petugas}: reel tayang di {nama}\nhttps://www.facebook.com/reel/{j['video_id']}" + (f"\n⚠️ {j['catatan']}" if j.get("catatan") else ""))
    except Exception as e:  # noqa: BLE001
        galat, n = redact(e)[:300], int(j.get("percobaan", 0))
        j["galat"] = galat
        if n < MAKS_ULANG and not j.get("video_id"):
            j.update(status="menunggu", percobaan=n + 1, jadwal=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds"))
        else:
            j.update(status="gagal", selesai=iso_now())
            telegram(f"❌ {petugas}: gagal mengunggah ke {nama}\n{galat}")
    simpan(p, j, f"{petugas}: {j['status']}")


def main():
    pages = muat_json("pages.json", {})
    sekarang = datetime.now(timezone.utc)
    semua = [(p, j) for p in sorted(glob.glob("queue/*.json")) if (j := muat_json(p))]
    ubah = False
    for p, j in semua:
        waktu = parse_iso(j["jadwal"]) if j.get("jadwal") else sekarang
        if j.get("status") == "menunggu_persetujuan" and waktu < sekarang:
            j["status"] = "kedaluwarsa"
            simpan_json(p, j)
            ubah = True
        elif j.get("status") == "memproses" and j.get("mulai") and parse_iso(j["mulai"]) < sekarang - timedelta(minutes=60):
            j.update(status="gagal", galat="Proses terhenti. Periksa manual di Facebook sebelum mengulang, agar tidak ganda.")
            simpan_json(p, j)
            telegram(f"❌ Tugas {j.get('id')} terhenti. Periksa manual di Facebook.")
            ubah = True
        elif j.get("status") in FINAL and parse_iso(j.get("selesai") or j.get("dibuat") or iso_now()) < sekarang - timedelta(days=SIMPAN_HARI):
            os.remove(p)
            ubah = True
    if ubah:
        publish("Pembersihan antrean")
    semua = [(p, j) for p in sorted(glob.glob("queue/*.json")) if (j := muat_json(p))]
    antrian = [(parse_iso(j["jadwal"]), p, j) for p, j in semua if j.get("status") == "menunggu" and j.get("jadwal") and parse_iso(j["jadwal"]) <= sekarang]
    antrian.sort(key=lambda x: x[0])
    dikerjakan = 0
    for _, p, j in antrian:
        if dikerjakan >= MAKS_PER_RUN:
            break
        sehari = [x for _, x in semua if x.get("fanpage") == j.get("fanpage") and x.get("status") == "selesai"
                  and x.get("selesai") and parse_iso(x["selesai"]) > sekarang - timedelta(hours=24)]
        if len(sehari) >= MAKS_PER_HARI:
            print("Batas harian tercapai untuk", j.get("fanpage"))
            continue
        kerjakan(p, j, pages)
        dikerjakan += 1
    if not antrian:
        print("Tidak ada tugas yang jatuh tempo.")


if __name__ == "__main__":
    main()
