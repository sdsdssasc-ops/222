import os, time, threading
import requests
from flask import Flask, jsonify, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
HEAD = {"User-Agent": "Mozilla/5.0 (LimitedsPredictor)"}
POOL_SIZE = int(os.getenv("POOL_SIZE", "120"))      # عدد المتدات اللي نحللها (الأغلى رابّ)
FETCH_DELAY = float(os.getenv("FETCH_DELAY", "1.6"))  # ثواني بين كل طلب لروبلوكس
REFRESH_AFTER = 6 * 3600

items, items_time = {}, 0
history, thumbs = {}, {}
lock = threading.Lock()

DEMAND = {-1: "غير محدد", 0: "سيء", 1: "منخفض", 2: "عادي", 3: "عالي", 4: "ممتاز"}
TREND = {-1: "غير محدد", 0: "غير محدد", 1: "نازل", 2: "غير مستقر", 3: "ثابت", 4: "طالع", 5: "متذبذب"}


def load_items():
    """كل المتدات من Rolimons (الاسم، RAP، القيمة، الطلب...)"""
    global items, items_time
    if items and time.time() - items_time < 600:
        return items
    r = requests.get("https://api.rolimons.com/items/v1/itemdetails", headers=HEAD, timeout=20)
    r.raise_for_status()
    data = {}
    for iid, v in r.json()["items"].items():
        data[int(iid)] = {
            "id": int(iid), "name": v[0], "acronym": v[1] or "",
            "rap": max(v[2], 0), "value": v[3] if v[3] > 0 else None,
            "demand": DEMAND.get(v[5], "غير محدد"), "trend": TREND.get(v[6], "غير محدد"),
            "projected": bool(v[7] == 1), "hyped": bool(v[8] == 1), "rare": bool(v[9] == 1),
        }
    items, items_time = data, time.time()
    return items


def fetch_history(iid):
    r = requests.get(f"https://economy.roblox.com/v1/assets/{iid}/resale-data", headers=HEAD, timeout=20)
    if r.status_code == 429:
        raise RuntimeError("rate")
    r.raise_for_status()
    j = r.json()
    prices = [p["value"] for p in j.get("priceDataPoints", [])]
    vols = [p["value"] for p in j.get("volumeDataPoints", [])]
    with lock:
        history[iid] = {"prices": prices, "vols": vols, "t": time.time(),
                        "avg": j.get("recentAveragePrice"), "sales": j.get("assetStock")}


def predict(prices, current, days=7):
    """انحدار خطي على آخر 30 نقطة → توقع بعد 7 أيام"""
    p = prices[-30:]
    n = len(p)
    if n < 8 or current <= 0:
        return None
    mx, my = (n - 1) / 2, sum(p) / n
    sxx = sum((i - mx) ** 2 for i in range(n))
    sxy = sum((i - mx) * (p[i] - my) for i in range(n))
    slope = sxy / sxx
    ss_tot = sum((y - my) ** 2 for y in p) or 1
    ss_res = sum((p[i] - (my + slope * (i - mx))) ** 2 for i in range(n))
    r2 = max(0.0, 1 - ss_res / ss_tot)
    pred = min(max(current + slope * days, current * 0.6), current * 1.4)
    return {"predicted": round(pred), "pct": round((pred - current) / current * 100, 2),
            "confidence": round(r2 * 100)}


def worker():
    while True:
        try:
            data = load_items()
            ids = [i["id"] for i in sorted(data.values(), key=lambda x: -x["rap"])[:POOL_SIZE]]
            for iid in ids:
                h = history.get(iid)
                if h and time.time() - h["t"] < REFRESH_AFTER:
                    continue
                try:
                    fetch_history(iid)
                except RuntimeError:
                    time.sleep(40)
                except Exception:
                    pass
                time.sleep(FETCH_DELAY)
        except Exception:
            time.sleep(30)
        time.sleep(60)


def get_thumbs(ids):
    need = [i for i in ids if i not in thumbs]
    for k in range(0, len(need), 50):
        chunk = need[k:k + 50]
        try:
            r = requests.get("https://thumbnails.roblox.com/v1/assets", headers=HEAD, timeout=20,
                             params={"assetIds": ",".join(map(str, chunk)), "size": "150x150", "format": "Png"})
            for d in r.json().get("data", []):
                if d.get("imageUrl"):
                    thumbs[d["targetId"]] = d["imageUrl"]
        except Exception:
            pass
    return {i: thumbs.get(i, "") for i in ids}


def card(it, pr, img):
    return {**it, "image": img, "link": f"https://www.roblox.com/catalog/{it['id']}",
            "predicted": pr["predicted"], "pct": pr["pct"], "confidence": pr["confidence"]}


@app.route("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.route("/api/movers")
def movers():
    n = min(max(int(request.args.get("n", 10)), 1), 50)
    data = load_items()
    rows = []
    for iid, h in list(history.items()):
        it = data.get(iid)
        if not it:
            continue
        pr = predict(h["prices"], it["rap"])
        if pr:
            rows.append((it, pr))
    rows.sort(key=lambda x: -x[1]["pct"])
    gain = [r for r in rows if r[1]["pct"] > 0][:n]
    lose = [r for r in reversed(rows) if r[1]["pct"] < 0][:n]
    imgs = get_thumbs([r[0]["id"] for r in gain + lose])
    return jsonify({
        "gainers": [card(i, p, imgs[i["id"]]) for i, p in gain],
        "losers": [card(i, p, imgs[i["id"]]) for i, p in lose],
        "analyzed": len(rows), "pool": POOL_SIZE,
    })


@app.route("/api/item/<int:iid>")
def item(iid):
    it = load_items().get(iid)
    if not it:
        return jsonify({"error": "المتد غير موجود"}), 404
    if iid not in history:
        try:
            fetch_history(iid)
        except Exception:
            return jsonify({"error": "روبلوكس رفض الطلب، جرب بعد شوي"}), 429
    h = history[iid]
    pr = predict(h["prices"], it["rap"])
    img = get_thumbs([iid])[iid]
    out = {**it, "image": img, "link": f"https://www.roblox.com/catalog/{iid}",
           "history": h["prices"][-90:], "avg_volume": round(sum(h["vols"][-30:]) / max(len(h["vols"][-30:]), 1), 1)}
    out.update(pr or {"predicted": None, "pct": None, "confidence": None})
    return jsonify(out)


@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify([])
    res = [i for i in load_items().values() if q in i["name"].lower() or q == i["acronym"].lower()]
    res.sort(key=lambda x: -x["rap"])
    res = res[:12]
    imgs = get_thumbs([i["id"] for i in res])
    return jsonify([{"id": i["id"], "name": i["name"], "rap": i["rap"], "image": imgs[i["id"]]} for i in res])


threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
