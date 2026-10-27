"""Bot Auto Uploader FB Reels (versi perbaikan).
Dijalankan GitHub Actions: membaca antrean di folder queue/, mengunggah tugas yang sudah
waktunya ke fanpage yang dipilih, memberi komentar pertama, lalu menyimpan status ke repo."""
import glob, json, os, re, subprocess, tempfile, time
from datetime import datetime, timezone

import requests

VER = os.getenv("FB_VER", "v25.0")
G = f"https://graph.facebook.com/{VER}"
MAKS_PER_RUN = 3

try:
    ALL = json.loads(os.getenv("ALL_SECRETS") or "{}")
except ValueError:
    ALL = {}
RAHASIA = [v for v in ALL.values() if isinstance(v, str) and len(v) >= 8]


def redact(teks):
    teks = str(teks)
    for s in RAHASIA:
        teks = teks.replace(s, "***")
    return teks


def sh(*a, check=True):
    return subprocess.run(a, check=check, capture_output=True, text=True)


def publish(pesan):
    """Simpan perubahan queue/ ke repo (aman terhadap tabrakan dengan panel)."""
    sh("git", "add", "queue")
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


def drive_id(url):
    m = re.search(r"/d/([\w-]{10,})", url) or re.search(r"[?&]id=([\w-]{10,})", url)
    return m.group(1) if m else None


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
    tok = ALL.get(akun["secret_key"])
    if not tok:
        raise RuntimeError(f"Secret {akun['secret_key']} belum diisi di GitHub Secrets")
    try:  # jika token pengguna, ambil token halaman; jika sudah token halaman, pakai apa adanya
        r = requests.get(f"{G}/{akun['page_id']}", params={"fields": "access_token", "access_token": tok}, timeout=30).json()
        baru = r.get("access_token")
        if baru:
            RAHASIA.append(baru)
        return baru or tok
    except requests.RequestException:
        return tok


def caption(j):
    bagian = [j.get("deskripsi", "").strip()]
    if j.get("link_di") in ("deskripsi", "keduanya") and j.get("redirect_link"):
        bagian.append(j["redirect_link"].strip())
    tagar = " ".join("#" + t.lstrip("#") for t in j.get("tagar", []) if t.strip())
    if tagar:
        bagian.append(tagar)
    return "\n\n".join(b for b in bagian if b)


def komentar(j):
    bagian = [j.get("komentar", "").strip()]
    if j.get("link_di") in ("komentar", "keduanya") and j.get("redirect_link"):
        bagian.append(j["redirect_link"].strip())
    return "\n".join(b for b in bagian if b)


def upload(page_id, tok, path, teks, komen):
    # 1) buka sesi unggah
    j = cek(requests.post(f"{G}/{page_id}/video_reels", data={"upload_phase": "start", "access_token": tok}, timeout=60))
    vid, url = j["video_id"], j["upload_url"]
    # 2) kirim isi file video (bukan URL Drive: Facebook tidak bisa menarik dari Drive)
    with open(path, "rb") as f:
        cek(requests.post(url, headers={"Authorization": "OAuth " + tok, "offset": "0",
                                        "file_size": str(os.path.getsize(path))}, data=f, timeout=900))
    # 3) terbitkan
    fin = cek(requests.post(f"{G}/{page_id}/video_reels", data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": teks, "access_token": tok}, timeout=60))
    # 4) tunggu Facebook selesai memproses
    for _ in range(20):
        s = requests.get(f"{G}/{vid}", params={"fields": "status", "access_token": tok}, timeout=30).json().get("status", {})
        if s.get("video_status") == "ready" or s.get("publishing_phase", {}).get("status") == "complete":
            break
        if s.get("video_status") == "error":
            raise RuntimeError("Facebook gagal memproses video: " + redact(json.dumps(s)[:200]))
        time.sleep(15)
    # 5) komentar pertama (coba beberapa alamat tujuan, simpan alasan jika gagal)
    hasil = {"video_id": vid}
    if komen:
        kandidat = [vid] + [x for x in (fin.get("post_id"), f"{page_id}_{vid}") if x]
        hasil["komentar_ok"] = False
        for _ in range(6):
            for target in kandidat:
                r = requests.post(f"{G}/{target}/comments", data={"message": komen, "access_token": tok}, timeout=30)
                if r.status_code < 400:
                    hasil["komentar_ok"] = True
                    hasil.pop("komentar_galat", None)
                    return hasil
                hasil["komentar_galat"] = redact(r.text)[:200]
            time.sleep(20)
    return hasil


def simpan(p, j, pesan):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=2)
    publish(pesan)


def kerjakan(p, j, pages):
    petugas = j.get("petugas", "Budi")
    print(f"{petugas} mengerjakan {os.path.basename(p)}")
    j.update(status="memproses", mulai=iso_now())
    simpan(p, j, f"{petugas} mulai mengunggah")  # ditandai dulu agar tidak terunggah dua kali
    try:
        akun = pages.get(j.get("fanpage"))
        if not akun:
            raise RuntimeError(f"Fanpage '{j.get('fanpage')}' tidak ada di pages.json")
        fid = drive_id(j.get("gdrive_link", ""))
        if not fid:
            raise RuntimeError("Link Google Drive tidak dikenali")
        import gdown
        f = os.path.join(tempfile.mkdtemp(), "video.mp4")
        if not gdown.download(id=fid, output=f, quiet=True) or os.path.getsize(f) < 1000:
            raise RuntimeError("Gagal mengunduh dari Google Drive. Pastikan aksesnya: siapa saja yang memiliki link")
        tok = token_halaman(akun)
        j.update(upload(akun["page_id"], tok, f, caption(j), komentar(j)), status="selesai")
        if j.get("komentar_ok") is False:
            j["catatan"] = "Reel tayang, tetapi komentar pertama gagal: " + j.get("komentar_galat", "")
    except Exception as e:  # noqa: BLE001
        j["status"] = "gagal"
        j["galat"] = redact(e)[:300]
    j["selesai"] = iso_now()
    simpan(p, j, f"{petugas}: {j['status']}")


def main():
    with open("pages.json", encoding="utf-8") as f:
        pages = json.load(f)
    sekarang = datetime.now(timezone.utc)
    antrian = []
    for p in sorted(glob.glob("queue/*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                j = json.load(f)
            waktu = datetime.fromisoformat(j["jadwal"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if j.get("status") == "menunggu" and waktu <= sekarang:
            antrian.append((waktu, p, j))
    antrian.sort(key=lambda x: x[0])
    for _, p, j in antrian[:MAKS_PER_RUN]:
        kerjakan(p, j, pages)
    if not antrian:
        print("Tidak ada tugas yang jatuh tempo.")


if __name__ == "__main__":
    main()
