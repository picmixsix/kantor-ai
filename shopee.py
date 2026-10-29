"""Shopee Affiliate Open API: membuat short link ber-subId (jalur resmi, tanpa scraping)."""
import hashlib
import json
import time

import requests

from lib import secret

ENDPOINT_BAWAAN = "https://open-api.affiliate.shopee.co.id/graphql"  # cek di dasbor afiliasi jika berbeda


def _kirim(query):
    app, sec = secret("SHOPEE_APP_ID"), secret("SHOPEE_APP_SECRET")
    if not app or not sec:
        raise RuntimeError("SHOPEE_APP_ID dan SHOPEE_APP_SECRET belum diisi")
    payload = json.dumps({"query": query}, separators=(",", ":"))
    ts = str(int(time.time()))
    sig = hashlib.sha256((app + ts + payload + sec).encode()).hexdigest()
    r = requests.post(secret("SHOPEE_ENDPOINT", ENDPOINT_BAWAAN), data=payload.encode(), timeout=30, headers={
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app}, Timestamp={ts}, Signature={sig}"})
    j = r.json()
    if r.status_code >= 400 or j.get("errors"):
        raise RuntimeError("Shopee: " + json.dumps(j.get("errors", j))[:200])
    return j.get("data", {})


def short_link(url, sub_ids):
    subs = json.dumps(list(sub_ids)[:5])
    for bentuk in (f"input: {{originUrl: {json.dumps(url)}, subIds: {subs}}}",
                   f"originUrl: {json.dumps(url)}, subIds: {subs}"):
        try:
            data = _kirim("mutation { generateShortLink(" + bentuk + ") { shortLink } }")
            return data["generateShortLink"]["shortLink"]
        except (RuntimeError, KeyError, TypeError) as e:
            galat = e
    raise RuntimeError(str(galat))
