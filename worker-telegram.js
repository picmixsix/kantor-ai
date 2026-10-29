// Cloudflare Worker: menerima tombol Setuju/Tolak dari Telegram dan mengubah status tugas di repo.
// Variabel (Settings > Variables and Secrets di Cloudflare):
//   BOT_TOKEN, OWNER_ID (ID angka akun Telegram Anda), WEBHOOK_SECRET (kata acak bebas), GH_TOKEN, REPO (contoh picmixsix/kantor-ai)
const kirim = (env, method, body) => fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const gh = (env, path, opt = {}) => fetch(`https://api.github.com/repos/${env.REPO}/contents/${path}`, { ...opt, headers: {
  Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "kantor-ai-worker" } });
const dec = (b64) => new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\n/g, "")), (c) => c.charCodeAt(0)));
const enc = (s) => { let b = ""; new TextEncoder().encode(s).forEach((x) => (b += String.fromCharCode(x))); return btoa(b); };

export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("ok");
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
    const cb = (await req.json()).callback_query;
    if (!cb) return new Response("ok");
    const jawab = (teks) => kirim(env, "answerCallbackQuery", { callback_query_id: cb.id, text: teks, show_alert: false });
    if (String(cb.from.id) !== String(env.OWNER_ID)) { await jawab("Tidak diizinkan"); return new Response("ok"); }
    const [aksi, id] = (cb.data || "").split(":");
    if (!/^[0-9a-z_-]+$/.test(id || "") || !["ok", "no"].includes(aksi)) { await jawab("Data tidak valid"); return new Response("ok"); }
    const r = await gh(env, `queue/${id}.json`);
    if (!r.ok) { await jawab("Tugas tidak ditemukan"); return new Response("ok"); }
    const file = await r.json(), job = JSON.parse(dec(file.content));
    if (job.status !== "menunggu_persetujuan") { await jawab("Sudah diproses: " + job.status); return new Response("ok"); }
    job.status = aksi === "ok" ? "menunggu" : "ditolak";
    const put = await gh(env, `queue/${id}.json`, { method: "PUT", body: JSON.stringify({
      message: `Telegram: ${job.status} ${id}`, content: enc(JSON.stringify(job, null, 2)), sha: file.sha }) });
    await jawab(put.ok ? (aksi === "ok" ? "Disetujui ✓" : "Ditolak ✗") : "Gagal menyimpan, coba lagi");
    if (put.ok && cb.message) await kirim(env, "editMessageReplyMarkup", { chat_id: cb.message.chat.id, message_id: cb.message.message_id, reply_markup: { inline_keyboard: [] } });
    return new Response("ok");
  },
};
