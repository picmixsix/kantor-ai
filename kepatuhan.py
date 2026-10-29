"""Divisi Kepatuhan: pemeriksaan otomatis sebelum konten masuk antrean persetujuan."""
import difflib
import re

LABEL = "Link afiliasi"
LARANGAN = [
    r"pasti\s+untung", r"dijamin\s+(untung|sembuh|berhasil|aman|laris)", r"100\s*%\s*(aman|ampuh|sembuh|berhasil)",
    r"sembuh\s+total", r"tanpa\s+efek\s+samping", r"anti\s+gagal", r"cepat\s+kaya",
    r"obat\s+(kanker|diabetes|jantung)", r"turun\s+berat\s+badan\s+\d+\s*kg",
]


def periksa(j, riwayat=()):
    """Mengembalikan daftar masalah. Daftar kosong berarti lolos."""
    masalah = []
    desk = j.get("deskripsi", "")
    teks = (desk + " " + j.get("komentar", "")).lower()
    for pola in LARANGAN:
        if re.search(pola, teks):
            masalah.append("klaim berlebihan: " + pola)
    if not desk.strip():
        masalah.append("deskripsi kosong")
    if len(desk) > 2000:
        masalah.append("deskripsi terlalu panjang")
    if len(j.get("tagar", [])) > 15:
        masalah.append("tagar lebih dari 15")
    for lama in riwayat:
        if lama and difflib.SequenceMatcher(None, lama, desk).ratio() > 0.9:
            masalah.append("terlalu mirip dengan konten sebelumnya")
            break
    return masalah
