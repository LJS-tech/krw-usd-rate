"""
원화-달러 환율 조회 서버 (단일 파일 버전)
- HTML/CSS 를 코드 안에 내장 -> templates/static 폴더 불필요
- 그래프: 터치/마우스로 짚으면 날짜+환율 말풍선 + 세로 기준선
- 데이터: Frankfurter(ECB) 1차, yfinance 2차(백업), 30분 캐시
"""
import datetime as dt
import json
import os
import threading
import urllib.request

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

_CACHE = {"ts": None, "data": None}
_LOCK = threading.Lock()
_TTL = dt.timedelta(minutes=30)
_DAYS = 92


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
    krwusd = [round(1.0 / v, 8) for v in usdkrw]
    last, prev = usdkrw[-1], (usdkrw[-2] if len(usdkrw) > 1 else usdkrw[-1])
    change = round(last - prev, 4)
    pct = round((change / prev) * 100, 3) if prev else 0.0
    return {
        "source": src,
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "today_date": dates[-1],
        "today_usdkrw": last,
        "today_krwusd": round(1.0 / last, 8),
        "change": change, "pct": pct,
        "period_high": max(usdkrw), "period_low": min(usdkrw),
        "period_avg": round(sum(usdkrw) / len(usdkrw), 2),
        "dates": dates, "usdkrw": usdkrw, "krwusd": krwusd,
    }


def get_rates():
    with _LOCK:
        now = dt.datetime.now()
        if _CACHE["data"] is None or now - _CACHE["ts"] > _TTL:
            _CACHE["data"] = _build()
            _CACHE["ts"] = now
        return _CACHE["data"]


PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#1e3a8a">
<title>원 / 달러 환율</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#f1f5f9;--card:#fff;--ink:#0f172a;--sub:#64748b;--blue:#2563eb;--up:#dc2626;--down:#2563eb;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  background:var(--bg);color:var(--ink);padding-bottom:40px;-webkit-text-size-adjust:100%;}
header{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff;padding:18px 16px;
  display:flex;justify-content:space-between;align-items:baseline;}
header h1{font-size:18px;font-weight:700;}
.updated{font-size:11px;opacity:.85;}
main{max-width:680px;margin:0 auto;padding:14px;display:flex;flex-direction:column;gap:14px;}
.card{background:var(--card);border-radius:16px;padding:18px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
.hero{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;}
.label{font-size:13px;color:var(--sub);margin-bottom:6px;}
.big{font-size:34px;font-weight:800;letter-spacing:-.5px;}
.chg{font-size:14px;font-weight:600;margin-top:6px;}
.chg.up{color:var(--up);} .chg.down{color:var(--down);}
.hero-sub{text-align:right;}
.krw{font-size:13px;color:var(--ink);font-weight:600;}
.date{font-size:11px;color:var(--sub);margin-top:4px;}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}
.stat{text-align:center;padding:14px 8px;}
.s-label{font-size:11px;color:var(--sub);margin-bottom:6px;}
.s-val{font-size:17px;font-weight:700;}
h2{font-size:15px;margin-bottom:12px;}
.hint{font-size:11px;color:var(--sub);font-weight:400;margin-left:6px;}
.chart-wrap{position:relative;height:240px;touch-action:pan-y;}
.table-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
.toggle{background:#eff6ff;color:var(--blue);border:none;border-radius:8px;
  padding:6px 12px;font-size:12px;font-weight:600;cursor:pointer;}
.table-scroll{max-height:520px;overflow-y:auto;}
table{width:100%;border-collapse:collapse;font-size:13px;}
th{position:sticky;top:0;background:#f8fafc;color:var(--sub);font-weight:600;
  padding:9px 6px;text-align:right;border-bottom:1px solid #e2e8f0;}
th:first-child,td:first-child{text-align:left;}
td{padding:9px 6px;border-bottom:1px solid #f1f5f9;font-variant-numeric:tabular-nums;}
tr:hover td{background:#f8fafc;}
footer{text-align:center;font-size:11px;color:var(--sub);margin-top:8px;padding:0 14px;}
@media(max-width:420px){.big{font-size:28px;}.s-val{font-size:15px;}}
</style>
</head>
<body>
<header><h1>By 진솔</h1><span id="updated" class="updated">불러오는 중…</span></header>
<main>
  <section class="hero card">
    <div class="hero-main">
      <div class="label">오늘 환율 (1 USD 기준)</div>
      <div id="big" class="big">—</div>
      <div id="chg" class="chg">—</div>
    </div>
    <div class="hero-sub">
      <div class="krw">1원 = <span id="krwusd">—</span> USD</div>
      <div class="date" id="tdate"></div>
    </div>
  </section>
  <section class="stats">
    <div class="card stat"><div class="s-label">3개월 최고</div><div id="hi" class="s-val">—</div></div>
    <div class="card stat"><div class="s-label">3개월 최저</div><div id="lo" class="s-val">—</div></div>
    <div class="card stat"><div class="s-label">3개월 평균</div><div id="avg" class="s-val">—</div></div>
  </section>
  <section class="card chart-card">
    <h2>최근 3개월 추이 (USD/KRW)<span class="hint">그래프 상세 표시</span></h2>
    <div class="chart-wrap"><canvas id="chart"></canvas></div>
  </section>
  <section class="card table-card">
    <div class="table-head"><h2>일자별 환율</h2><button id="toggle" class="toggle">전체 보기</button></div>
    <div class="table-scroll">
      <table id="tbl"><thead><tr><th>날짜</th><th>USD/KRW</th><th>1원(USD)</th></tr></thead><tbody></tbody></table>
    </div>
  </section>
</main>
<footer><span id="src"></span> · 데이터는 영업일 기준</footer>
<script>
let chart, full=false, DATA=null;
function fmt(n){return Number(n).toLocaleString("ko-KR",{minimumFractionDigits:2,maximumFractionDigits:2});}
function renderTable(){
  const tb=document.querySelector("#tbl tbody");tb.innerHTML="";
  const n=DATA.dates.length;const idx=[...Array(n).keys()].reverse();
  const show=full?idx:idx.slice(0,15);
  for(const i of show){const tr=document.createElement("tr");
    tr.innerHTML=`<td>${DATA.dates[i]}</td><td>${fmt(DATA.usdkrw[i])}</td><td>${DATA.krwusd[i].toFixed(8)}</td>`;
    tb.appendChild(tr);}
  document.getElementById("toggle").textContent=full?"접기":"전체 보기";
}

// 짚은 지점에 세로 기준선을 그리는 플러그인
const crosshair={
  id:"crosshair",
  afterDraw(c){
    const act=c.tooltip&&c.tooltip._active;
    if(act&&act.length){
      const x=act[0].element.x;const ya=c.chartArea;
      const ctx=c.ctx;ctx.save();
      ctx.beginPath();ctx.moveTo(x,ya.top);ctx.lineTo(x,ya.bottom);
      ctx.lineWidth=1;ctx.strokeStyle="rgba(37,99,235,0.45)";
      ctx.setLineDash([4,4]);ctx.stroke();ctx.restore();
    }
  }
};

async function load(){
  const r=await fetch("/api/rates");DATA=await r.json();
  document.getElementById("big").textContent=fmt(DATA.today_usdkrw)+" 원";
  document.getElementById("krwusd").textContent=DATA.today_krwusd.toFixed(8);
  document.getElementById("tdate").textContent=DATA.today_date+" 기준";
  document.getElementById("updated").textContent="갱신 "+DATA.updated;
  document.getElementById("hi").textContent=fmt(DATA.period_high);
  document.getElementById("lo").textContent=fmt(DATA.period_low);
  document.getElementById("avg").textContent=fmt(DATA.period_avg);
  document.getElementById("src").textContent="출처: "+DATA.source;
  const up=DATA.change>=0;const chg=document.getElementById("chg");
  chg.textContent=(up?"▲ +":"▼ ")+fmt(Math.abs(DATA.change))+` (${up?"+":""}${DATA.pct}%)`;
  chg.className="chg "+(up?"up":"down");
  const ctx=document.getElementById("chart");if(chart)chart.destroy();
  chart=new Chart(ctx,{type:"line",
    data:{labels:DATA.dates,datasets:[{data:DATA.usdkrw,borderColor:"#2563eb",borderWidth:2,
      backgroundColor:"rgba(37,99,235,0.10)",fill:true,
      pointRadius:0,pointHoverRadius:5,pointHoverBackgroundColor:"#2563eb",
      pointHoverBorderColor:"#fff",pointHoverBorderWidth:2,tension:0.25}]},
    plugins:[crosshair],
    options:{responsive:true,maintainAspectRatio:false,
      interaction:{mode:"index",intersect:false,axis:"x"},
      hover:{mode:"index",intersect:false},
      plugins:{legend:{display:false},
        tooltip:{enabled:true,
          backgroundColor:"rgba(15,23,42,0.92)",
          titleColor:"#cbd5e1",bodyColor:"#fff",
          titleFont:{size:12},bodyFont:{size:14,weight:"bold"},
          padding:10,cornerRadius:8,displayColors:false,
          callbacks:{
            title:items=>items[0].label,
            label:c=>{
              const i=c.dataIndex;
              return ["1 USD = "+fmt(DATA.usdkrw[i])+" 원",
                      "1 원 = "+DATA.krwusd[i].toFixed(8)+" USD"];
            }
          }}},
      scales:{x:{ticks:{maxTicksLimit:6,color:"#64748b"},grid:{display:false}},
        y:{ticks:{color:"#64748b"},grid:{color:"#eef2f7"}}}}});
  renderTable();
}
document.getElementById("toggle").addEventListener("click",()=>{full=!full;renderTable();});
load();setInterval(load,5*60*1000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/api/rates")
def api_rates():
    return jsonify(get_rates())


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
