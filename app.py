"""
원화-달러 환율 조회 서버 (단일 파일 버전)
- 환율 출처: 한국은행 ECOS 매매기준율 1차 / Frankfurter(ECB) 2차 / yfinance 3차
- 그래프: 터치/마우스로 짚으면 날짜+환율 말풍선 + 세로 기준선
- 관리자: 우측 상단 버튼 -> 암호(krwpass) -> 조회수 통계 + 초기화
"""
import datetime as dt
import json
import os
import threading
import urllib.request

from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

# ===== 여기에 한국은행 ECOS 인증키를 붙여넣으세요 =====
ECOS_KEY = os.environ.get("ECOS_KEY", "").strip() or "UFI3GQ999ROMHHCDEYZZ"
# ====================================================

ADMIN_PW = "krwpass"
VISITS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visits.json")

_CACHE = {"ts": None, "data": None}
_LOCK = threading.Lock()
_VLOCK = threading.Lock()
_TTL = dt.timedelta(minutes=30)
_DAYS = 92


def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _from_ecos():
    if not ECOS_KEY or ECOS_KEY == "PASTE_YOUR_ECOS_KEY_HERE":
        raise RuntimeError("no ecos key")
    end = dt.date.today()
    start = end - dt.timedelta(days=_DAYS)
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}/json/kr/"
           f"1/300/731Y001/D/{start:%Y%m%d}/{end:%Y%m%d}/0000001")
    j = _http_json(url)
    if "StatisticSearch" not in j:
        raise RuntimeError("ecos error: " + json.dumps(j)[:200])
    rows = j["StatisticSearch"]["row"]
    dates, usdkrw = [], []
    for r in rows:
        t = r.get("TIME", "")
        v = r.get("DATA_VALUE", "")
        if len(t) == 8 and v:
            dates.append(f"{t[:4]}-{t[4:6]}-{t[6:]}")
            usdkrw.append(round(float(v), 4))
    if not usdkrw:
        raise RuntimeError("ecos empty")
    return dates, usdkrw, "한국은행 ECOS (매매기준율)"


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
    for fn in (_from_ecos, _from_frankfurter, _from_yfinance):
        try:
            dates, usdkrw, src = fn()
            break
        except Exception:
            continue
    else:
        raise RuntimeError("all sources failed")
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


def _load_visits():
    try:
        with open(VISITS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"total": 0, "ips": [], "by_date": {}, "first": None}


def _save_visits(v):
    try:
        with open(VISITS_FILE, "w", encoding="utf-8") as f:
            json.dump(v, f)
    except Exception:
        pass


def record_visit():
    with _VLOCK:
        v = _load_visits()
        today = dt.date.today().isoformat()
        if v.get("first") is None:
            v["first"] = today
        v["total"] = int(v.get("total", 0)) + 1
        v.setdefault("by_date", {})
        v["by_date"][today] = v["by_date"].get(today, 0) + 1
        ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "")
              .split(",")[0].strip())
        ips = set(v.get("ips", []))
        if ip:
            ips.add(ip)
        v["ips"] = list(ips)
        _save_visits(v)


def reset_visits():
    with _VLOCK:
        today = dt.date.today().isoformat()
        _save_visits({"total": 0, "ips": [], "by_date": {}, "first": today})


def visit_stats():
    v = _load_visits()
    today = dt.date.today().isoformat()
    return {
        "total": int(v.get("total", 0)),
        "today": int(v.get("by_date", {}).get(today, 0)),
        "unique": len(v.get("ips", [])),
        "first": v.get("first") or today,
    }


PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#1e3a8a">
<title>원/달러 환율</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#f1f5f9;--card:#fff;--ink:#0f172a;--sub:#64748b;--blue:#2563eb;--up:#dc2626;--down:#2563eb;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  background:var(--bg);color:var(--ink);padding-bottom:40px;-webkit-text-size-adjust:100%;}
header{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff;padding:16px;
  display:flex;justify-content:space-between;align-items:center;gap:10px;}
.h-left h1{font-size:18px;font-weight:700;}
.h-left .updated{font-size:11px;opacity:.85;}
.admin-btn{background:rgba(255,255,255,0.18);color:#fff;border:1px solid rgba(255,255,255,0.35);
  border-radius:10px;padding:8px 12px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;}
.admin-btn:hover{background:rgba(255,255,255,0.3);}
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
.overlay{position:fixed;inset:0;background:rgba(15,23,42,0.55);display:none;
  align-items:center;justify-content:center;padding:18px;z-index:50;}
.overlay.show{display:flex;}
.modal{background:#fff;border-radius:18px;padding:22px;width:100%;max-width:360px;
  box-shadow:0 20px 50px rgba(0,0,0,.3);}
.modal h3{font-size:17px;margin-bottom:4px;}
.modal .sub{font-size:12px;color:var(--sub);margin-bottom:16px;}
.adm-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px;}
.adm-cell{background:#f8fafc;border-radius:12px;padding:14px;text-align:center;}
.adm-cell .n{font-size:24px;font-weight:800;color:var(--blue);}
.adm-cell .t{font-size:11px;color:var(--sub);margin-top:4px;}
.adm-foot{font-size:11px;color:var(--sub);text-align:center;margin-bottom:14px;}
.btn-row{display:flex;gap:10px;}
.close-btn{flex:1;background:var(--blue);color:#fff;border:none;border-radius:10px;
  padding:11px;font-size:14px;font-weight:600;cursor:pointer;}
.reset-btn{flex:1;background:#fef2f2;color:var(--up);border:1px solid #fecaca;
  border-radius:10px;padding:11px;font-size:14px;font-weight:600;cursor:pointer;}
.reset-btn:hover{background:#fee2e2;}
@media(max-width:420px){.big{font-size:28px;}.s-val{font-size:15px;}}
</style>
</head>
<body>
<header>
  <div class="h-left">
    <h1>By 진솔</h1>
    <div id="updated" class="updated">불러오는 중…</div>
  </div>
  <button id="adminBtn" class="admin-btn">🔒 관리자 설정</button>
</header>
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
    <h2>최근 3개월 추이 (USD/KRW)<span class="hint">그래프 상세 표시 지원</span></h2>
    <div class="chart-wrap"><canvas id="chart"></canvas></div>
  </section>
  <section class="card table-card">
    <div class="table-head"><h2>일자별 환율</h2><button id="toggle" class="toggle">전체 보기</button></div>
    <div class="table-scroll">
      <table id="tbl"><thead><tr><th>날짜</th><th>USD/KRW</th><th>1원(USD)</th></tr></thead><tbody></tbody></table>
    </div>
  </section>
</main>
<footer><span id="src"></span> · 데이터는 영업일 기준 · 이진솔</footer>

<div id="overlay" class="overlay">
  <div class="modal">
    <h3>관리자 · 접속 통계</h3>
    <div class="sub">이 사이트의 조회수 정보입니다.</div>
    <div class="adm-grid">
      <div class="adm-cell"><div id="a-total" class="n">—</div><div class="t">누적 접속수</div></div>
      <div class="adm-cell"><div id="a-today" class="n">—</div><div class="t">오늘 접속수</div></div>
      <div class="adm-cell"><div id="a-uniq" class="n">—</div><div class="t">순 방문자(IP)</div></div>
      <div class="adm-cell"><div id="a-first" class="n" style="font-size:14px;">—</div><div class="t">집계 시작일</div></div>
    </div>
    <div class="adm-foot" id="a-foot"></div>
    <div class="btn-row">
      <button id="resetBtn" class="reset-btn">초기화</button>
      <button id="closeBtn" class="close-btn">닫기</button>
    </div>
  </div>
</div>

<script>
let chart, full=false, DATA=null, ADMIN_PW="";
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
const crosshair={id:"crosshair",afterDraw(c){
  const act=c.tooltip&&c.tooltip._active;
  if(act&&act.length){const x=act[0].element.x;const ya=c.chartArea;const ctx=c.ctx;
    ctx.save();ctx.beginPath();ctx.moveTo(x,ya.top);ctx.lineTo(x,ya.bottom);
    ctx.lineWidth=1;ctx.strokeStyle="rgba(37,99,235,0.45)";ctx.setLineDash([4,4]);
    ctx.stroke();ctx.restore();}}};
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
        tooltip:{enabled:true,backgroundColor:"rgba(15,23,42,0.92)",
          titleColor:"#cbd5e1",bodyColor:"#fff",titleFont:{size:12},
          bodyFont:{size:14,weight:"bold"},padding:10,cornerRadius:8,displayColors:false,
          callbacks:{title:items=>items[0].label,
            label:c=>{const i=c.dataIndex;
              return ["1 USD = "+fmt(DATA.usdkrw[i])+" 원",
                      "1 원 = "+DATA.krwusd[i].toFixed(8)+" USD"];}}}},
      scales:{x:{ticks:{maxTicksLimit:6,color:"#64748b"},grid:{display:false}},
        y:{ticks:{color:"#64748b"},grid:{color:"#eef2f7"}}}}});
  renderTable();
}
document.getElementById("toggle").addEventListener("click",()=>{full=!full;renderTable();});
const overlay=document.getElementById("overlay");
function fillStats(s){
  document.getElementById("a-total").textContent=s.total.toLocaleString("ko-KR");
  document.getElementById("a-today").textContent=s.today.toLocaleString("ko-KR");
  document.getElementById("a-uniq").textContent=s.unique.toLocaleString("ko-KR");
  document.getElementById("a-first").textContent=s.first;
  document.getElementById("a-foot").textContent="집계 시작 "+s.first+" 이후 기록";
}
document.getElementById("adminBtn").addEventListener("click",async()=>{
  const pw=prompt("관리자 암호를 입력하세요");
  if(pw===null)return;
  const r=await fetch("/api/stats?pw="+encodeURIComponent(pw));
  if(r.status!==200){alert("암호가 틀렸습니다.");return;}
  ADMIN_PW=pw;
  fillStats(await r.json());
  overlay.classList.add("show");
});
document.getElementById("resetBtn").addEventListener("click",async()=>{
  if(!confirm("조회수를 정말 초기화할까요? 되돌릴 수 없습니다."))return;
  const r=await fetch("/api/reset?pw="+encodeURIComponent(ADMIN_PW));
  if(r.status!==200){alert("초기화에 실패했습니다.");return;}
  fillStats(await r.json());
  alert("초기화되었습니다.");
});
document.getElementById("closeBtn").addEventListener("click",()=>overlay.classList.remove("show"));
overlay.addEventListener("click",e=>{if(e.target===overlay)overlay.classList.remove("show");});
load();setInterval(load,5*60*1000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    record_visit()
    return render_template_string(PAGE)


@app.route("/api/rates")
def api_rates():
    return jsonify(get_rates())


@app.route("/api/stats")
def api_stats():
    if request.args.get("pw", "") != ADMIN_PW:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(visit_stats())


@app.route("/api/reset")
def api_reset():
    if request.args.get("pw", "") != ADMIN_PW:
        return jsonify({"error": "unauthorized"}), 401
    reset_visits()
    return jsonify(visit_stats())


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
