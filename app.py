"""
원화-달러 환율 조회 서버
- 오늘 환율 + 최근 3개월 시계열을 그래프/표로 제공
- 데이터: Frankfurter(ECB) 1차, yfinance 2차(백업)
- 결과는 30분 메모리 캐시
"""
import datetime as dt
import json
import os
import threading
import urllib.request

from flask import Flask, jsonify, render_template

app = Flask(__name__)

_CACHE = {"ts": None, "data": None}
_LOCK = threading.Lock()
_TTL = dt.timedelta(minutes=30)
_DAYS = 92  # 약 3개월


def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _from_frankfurter():
    base = "https://api.frankfurter.dev/v1"
    latest = _http_json(f"{base}/latest?base=USD&symbols=KRW")
    end = dt.date.fromisoformat(latest["date"])
    start = end - dt.timedelta(days=_DAYS)
    ts = _http_json(f"{base}/{start}..{end}?base=USD&symbols=KRW")
    rows = sorted(ts["rates"].items())
    dates = [d for d, _ in rows]
    usdkrw = [round(float(v["KRW"]), 4) for _, v in rows]
    return dates, usdkrw, "Frankfurter (ECB)"


def _from_yfinance():
    import yfinance as yf
    end = dt.date.today()
    start = end - dt.timedelta(days=_DAYS + 5)
    df = yf.download("KRW=X", start=start, end=end + dt.timedelta(days=1),
                     progress=False)
    if hasattr(df.columns, "droplevel"):
        try:
            df.columns = df.columns.droplevel(1)
        except Exception:
            pass
    df = df.dropna(subset=["Close"])
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    usdkrw = [round(float(v), 4) for v in df["Close"].tolist()]
    return dates, usdkrw, "Yahoo Finance"


def _build():
    try:
        dates, usdkrw, src = _from_frankfurter()
    except Exception:
        dates, usdkrw, src = _from_yfinance()

    krwusd = [round(1.0 / v, 8) for v in usdkrw]  # 1원당 달러
    last, prev = usdkrw[-1], (usdkrw[-2] if len(usdkrw) > 1 else usdkrw[-1])
    change = round(last - prev, 4)
    pct = round((change / prev) * 100, 3) if prev else 0.0
    return {
        "source": src,
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "today_date": dates[-1],
        "today_usdkrw": last,
        "today_krwusd": round(1.0 / last, 8),
        "change": change,
        "pct": pct,
        "period_high": max(usdkrw),
        "period_low": min(usdkrw),
        "period_avg": round(sum(usdkrw) / len(usdkrw), 2),
        "dates": dates,
        "usdkrw": usdkrw,
        "krwusd": krwusd,
    }


def get_rates():
    with _LOCK:
        now = dt.datetime.now()
        if _CACHE["data"] is None or now - _CACHE["ts"] > _TTL:
            _CACHE["data"] = _build()
            _CACHE["ts"] = now
        return _CACHE["data"]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/rates")
def api_rates():
    return jsonify(get_rates())


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    # Render 같은 클라우드는 PORT 환경변수를 줌. 로컬은 5000.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
