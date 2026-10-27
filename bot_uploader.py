import os
import requests
import json
import re
import time

# --- PENGATURAN ---
ALL_SECRETS = json.loads(os.environ.get("ALL_SECRETS", "{}"))
GITHUB_TOKEN = ALL_SECRETS.get("GH_TOKEN")
REPO = "picmixsix/kantor-ai" # Repo Anda

def ambil_pages():
    with open("pages.json", "r") as f:
        return json.load(f)

def ambil_antrean():
    url = f"https://api.github.com/repos/{REPO}/issues?state=open"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers)
    return res.json() if res.status_code == 200 else []

def parsing_tugas(body):
    match = re.search(r'```json\n(.*?)\n```', body, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    return None

def ubah_link_gdrive(link):
    # Mengubah link GDrive biasa menjadi link direct download
    file_id = re.search(r'/d/([a-zA-Z0-9_-]+)', link)
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id.group(1)}"
    return link

def upload_reels_fb(page_id, access_token, video_url, deskripsi):
    print("Memulai inisialisasi upload Reels...")
    url_init = f"https://graph.facebook.com/v18.0/{page_id}/video_reels"
    payload_init = {
        "upload_phase": "start",
        "access_token": access_token
    }
    res_init = requests.post(url_init, data=payload_init).json()
    
    if "video_id" not in res_init:
        print("Gagal inisialisasi:", res_init)
        return False
        
    video_id = res_init["video_id"]
    upload_url = res_init["upload_url"]
    
    print("Mengunggah video dari GDrive ke Facebook...")
    payload_upload = {
        "access_token": access_token,
        "video_file_chunk": video_url # FB bisa menarik langsung dari URL
    }
    headers = {"Authorization": f"OAuth {access_token}"}
    requests.post(upload_url, headers=headers, data=payload_upload)
    
    # Tunggu sebentar agar Facebook memproses video
    time.sleep(10)
    
    print("Mempublikasikan Reels...")
    payload_publish = {
        "upload_phase": "finish",
        "video_id": video_id,
        "video_state": "PUBLISHED",
        "description": deskripsi,
        "access_token": access_token
    }
    res_pub = requests.post(url_init, data=payload_publish).json()
    
    if "success" in res_pub and res_pub["success"]:
        return True
    else:
        print("Gagal publikasi:", res_pub)
        return False

def tutup_issue(issue_num, pesan):
    url_comment = f"https://api.github.com/repos/{REPO}/issues/{issue_num}/comments"
    url_close = f"https://api.github.com/repos/{REPO}/issues/{issue_num}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    requests.post(url_comment, headers=headers, json={"body": pesan})
    requests.patch(url_close, headers=headers, json={"state": "closed"})

if __name__ == "__main__":
    print("Bot Dijalankan...")
    pages = ambil_pages()
    issues = ambil_antrean()
    
    for issue in issues:
        tugas = parsing_tugas(issue.get("body", ""))
        if not tugas:
            continue
            
        fp_kode = tugas.get("fanpage")
        if fp_kode not in pages:
            print(f"Fanpage {fp_kode} tidak ditemukan di pages.json")
            continue
            
        akun = pages[fp_kode]
        token_fb = ALL_SECRETS.get(akun["secret_key"])
        
        if not token_fb:
            print(f"Token untuk {akun['nama']} tidak ditemukan di Secrets!")
            continue
            
        teks_post = f"{tugas['deskripsi']}\n\nLink Produk: {tugas['redirect_link']}"
        link_video = ubah_link_gdrive(tugas["gdrive_link"])
        
        sukses = upload_reels_fb(akun["page_id"], token_fb, link_video, teks_post)
        
        if sukses:
            tutup_issue(issue["number"], "✅ Berhasil upload Reels ke Facebook! Antrean ini ditutup.")
            print(f"Selesai memproses antrean #{issue['number']}")
