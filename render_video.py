"""Divisi Produksi: membuat video vertikal 1080x1920 dari gambar dan teks memakai FFmpeg."""
import os
import shutil
import subprocess
import tempfile
import textwrap

import requests

from lib import drive_id

FONT = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"]


def _font():
    for f in FONT:
        if os.path.exists(f):
            return f
    raise RuntimeError("Font DejaVu tidak ditemukan (pasang paket fonts-dejavu-core)")


def _ambil(sumber, folder, i):
    tujuan = os.path.join(folder, f"g{i}.img")
    if sumber.startswith("http") and "google.com" in sumber:
        import gdown
        fid = drive_id(sumber)
        if not fid or not gdown.download(id=fid, output=tujuan, quiet=True):
            raise RuntimeError("Gagal mengunduh gambar dari Google Drive: " + sumber[:60])
    elif sumber.startswith("http"):
        r = requests.get(sumber, timeout=60)
        r.raise_for_status()
        with open(tujuan, "wb") as f:
            f.write(r.content)
    elif os.path.exists(sumber):
        shutil.copy(sumber, tujuan)
    else:
        raise RuntimeError("Sumber gambar tidak ditemukan: " + sumber[:60])
    return tujuan


def buat(spec, keluar):
    """spec: {"gambar": [..], "teks": [..], "detik": 3}. Hasil: file MP4 di path keluar."""
    gambar, teks, detik = spec["gambar"], spec.get("teks", []), float(spec.get("detik", 3))
    if not gambar or len(gambar) * detik > 90:
        raise RuntimeError("Jumlah gambar kosong atau total durasi lebih dari 90 detik")
    font, kerja, klip = _font(), tempfile.mkdtemp(), []
    frames = int(detik * 30)
    for i, g in enumerate(gambar):
        img, t = _ambil(g, kerja, i), (teks[i] if i < len(teks) else "")
        vf = ("scale=1296:2304:force_original_aspect_ratio=increase,crop=1296:2304,"
              f"zoompan=z='min(zoom+0.0006,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30")
        if t:
            tf = os.path.join(kerja, f"t{i}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write("\n".join(textwrap.wrap(t, 22)))
            vf += (f",drawtext=fontfile={font}:textfile={tf}:expansion=none:fontcolor=white:fontsize=60:"
                   "line_spacing=12:box=1:boxcolor=black@0.55:boxborderw=26:x=(w-text_w)/2:y=h*0.70")
        out = os.path.join(kerja, f"k{i}.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", img, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                        "-vf", vf, "-t", str(detik), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                        "-c:a", "aac", "-shortest", out], check=True, capture_output=True, text=True)
        klip.append(out)
    daftar = os.path.join(kerja, "daftar.txt")
    with open(daftar, "w") as f:
        f.write("".join(f"file '{k}'\n" for k in klip))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", daftar, "-c", "copy", keluar],
                   check=True, capture_output=True, text=True)
    return keluar
