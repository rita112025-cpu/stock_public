#!/usr/bin/env python3
"""
批次抓取自選股日線資料（增量更新版）
自動嘗試 TWSE（上市）→ TPEX（上櫃）兩個來源
支援增量更新：只補抓最後一個月到今天，57 支約 1 分鐘
用法：
    python batch_fetch.py                        # 增量更新全部
    python batch_fetch.py --no-resume            # 全量重抓
    python batch_fetch.py --only 2330,3324       # 只抓指定代號
    python batch_fetch.py --start 2023-01-01     # 指定起始日
"""

import csv, json, os, ssl, sys, time, argparse, io, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from datetime import date
from urllib.request import Request
from urllib.error import HTTPError

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = ssl.create_default_context()

_opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL))

# ──────────────────────────────────────────────
# 預設自選股清單（初次執行時寫出 watchlist.csv）
# ──────────────────────────────────────────────
_DEFAULT_WATCHLIST = [
    ("2330", "台積電"),
    ("2382", "廣達"),
    ("2317", "鴻海"),
    ("3017", "奇鋐"),
    ("2454", "聯發科"),
    ("2059", "川湖"),
    ("6669", "緯穎"),
    ("2383", "台光電"),
    ("2301", "光寶科"),
    ("3665", "貿聯-KY"),
    ("3037", "欣興"),
    ("3324", "雙鴻"),
    ("2308", "台達電"),
    ("6584", "南俊國際"),
    ("6505", "台塑化"),
    ("2072", "世紀風電"),
    ("2377", "微星"),
    ("2313", "華通"),
    ("2324", "仁寶"),
    ("2353", "宏碁"),
    ("6510", "精測"),
    ("6919", "康霈"),
    ("3533", "嘉澤"),
    ("3529", "力旺"),
    ("6213", "聯茂"),
    ("6515", "穎崴"),
    ("6223", "旺矽"),
    ("7769", "鴻勁"),
    ("6409", "旭隼"),
    ("6781", "AES-KY"),
    ("5274", "信驊"),
    ("3443", "創意"),
    ("3008", "大立光"),
    ("3653", "健策"),
    ("3661", "世芯-KY"),
    ("00919", "群益台灣精選高息"),
    ("00878", "國泰永續高股息"),
    ("2603", "長榮"),
    ("6446", "藥華藥"),
    ("2882", "國泰金"),
    ("2891", "中信金"),
    ("2881", "富邦金"),
    ("2412", "中華電"),
    ("1216", "統一"),
    ("4938", "和碩"),
    ("0050",  "元大台灣50"),
    ("0056",  "元大高股息"),
    ("006208","富邦台50"),
    ("6217", "中探針"),
    ("2303", "聯電"),
    ("2327", "國巨"),
    ("9910", "豐泰"),
    ("6274", "台燿"),
    ("2376", "技嘉"),
    ("6187", "萬潤"),
    ("6531", "愛普"),
    ("6693", "廣閎科"),
]

_WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.csv")

# ──────────────────────────────────────────────
# 自選股清單 I/O
# ──────────────────────────────────────────────
def load_watchlist() -> list[tuple[str, str]]:
    if not os.path.exists(_WATCHLIST_FILE):
        with open(_WATCHLIST_FILE, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows([["代號", "名稱"]] + list(_DEFAULT_WATCHLIST))
        print(f"已產生預設清單：{_WATCHLIST_FILE}（可用 Excel 編輯）", file=sys.stderr)
    with open(_WATCHLIST_FILE, "r", newline="", encoding="utf-8-sig") as f:
        wl = [(r.get("代號", "").strip(), r.get("名稱", "").strip())
              for r in csv.DictReader(f) if r.get("代號", "").strip()]
    if not wl:
        sys.exit(f"錯誤：{_WATCHLIST_FILE} 讀不到任何有效資料列。\n"
                 f"請確認檔案為 UTF-8 編碼，且標題列為「代號,名稱」。\n"
                 f"（用 Excel 編輯後請另存為「CSV UTF-8」，不要存成一般 CSV/Big5）")
    return wl

# ──────────────────────────────────────────────
# CSV 讀寫（原子寫入避免中途失敗留下半截檔）
# ──────────────────────────────────────────────
def read_existing(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            rows = [{"date": r["date"], "open": r.get("open", ""),
                     "high": r.get("high", ""), "low": r.get("low", ""),
                     "close": r["close"], "volume": r.get("volume", "")}
                    for r in csv.DictReader(f) if r.get("date") and r.get("close")]
        return sorted(rows, key=lambda r: r["date"])
    except Exception:
        return []

def resume_start(existing: list[dict], fallback: date) -> date:
    """增量起點：已有資料的最後一個月的月初（當月資料可能有盤後更正）"""
    if not existing:
        return fallback
    try:
        d = date.fromisoformat(existing[-1]["date"])
        return date(d.year, d.month, 1)
    except ValueError:
        return fallback

def merge_rows(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    by_date = {r["date"]: r for r in existing}
    by_date.update({r["date"]: r for r in new_rows})
    return sorted(by_date.values(), key=lambda r: r["date"])

def write_csv(path: str, rows: list[dict]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["date","open","high","low","close","volume"])
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)

# ──────────────────────────────────────────────
# 健檢
# ──────────────────────────────────────────────
def health_check(rows: list[dict]) -> list[str]:
    warns = []
    if len(rows) < 60:
        warns.append(f"筆數僅 {len(rows)}，MA60 無法計算")
    dates = [r["date"] for r in rows]
    if dates != sorted(dates):
        warns.append("日期未升冪排序")
    dup = len(dates) - len(set(dates))
    if dup:
        warns.append(f"含重複日期 {dup} 筆")
    return warns

# ──────────────────────────────────────────────
# 共用工具
# ──────────────────────────────────────────────
def _get(url: str, retries: int = 2) -> dict | None:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    })
    for attempt in range(retries + 1):
        try:
            with _opener.open(req, timeout=20) as r:
                return json.loads(r.read())
        except HTTPError as e:
            if e.code in (301, 302, 307, 308):
                # 標準 opener 已自動跟 Location；走到這裡代表沒有 Location。
                # 同一 URL 有時 200、有時 307，行為與流量節流一致，故視為可重試。
                if attempt < retries:
                    time.sleep(5 * (attempt + 1))
                    continue
                print(f"    [警告] HTTP {e.code}（無 Location，疑似流量節流）", file=sys.stderr)
                return None
            if attempt < retries:
                time.sleep(3)
            else:
                print(f"    [警告] {type(e).__name__}: {e}", file=sys.stderr)
                return None
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
            else:
                print(f"    [警告] {type(e).__name__}: {e}", file=sys.stderr)
                return None
    return None

def _clean(v: str) -> str:
    return str(v).strip().replace(",", "").lstrip("+").replace("--", "").replace("X", "")

def _roc_to_iso(s: str) -> str | None:
    p = str(s).strip().split("/")
    if len(p) != 3:
        return None
    try:
        return f"{int(p[0])+1911}-{int(p[1]):02d}-{int(p[2]):02d}"
    except ValueError:
        return None

def _parse_rows(rows_data: list, col: dict) -> list[dict]:
    rows = []
    for row in rows_data:
        try:
            iso = _roc_to_iso(row[col["date"]])
            if not iso:
                continue
            c = _clean(row[col["close"]])
            if not c:
                continue
            rows.append({
                "date":   iso,
                "open":   _clean(row[col["open"]])   if "open"   in col else "",
                "high":   _clean(row[col["high"]])   if "high"   in col else "",
                "low":    _clean(row[col["low"]])    if "low"    in col else "",
                "close":  c,
                "volume": _clean(row[col["volume"]]) if "volume" in col else "",
            })
        except (IndexError, KeyError):
            continue
    return rows

# ──────────────────────────────────────────────
# TWSE（上市）
# ──────────────────────────────────────────────
def _twse_month(code: str, year: int, month: int) -> list[dict]:
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
        f"?date={year}{month:02d}01&stockNo={code}&response=json"
    )
    data = _get(url)
    if not data or data.get("stat") != "OK":
        return []
    fields = data.get("fields", [])
    col = {}
    for i, f in enumerate(fields):
        if "日期"     in f: col["date"]   = i
        if "開盤"     in f: col["open"]   = i
        if "最高"     in f: col["high"]   = i
        if "最低"     in f: col["low"]    = i
        if "收盤"     in f: col["close"]  = i
        if "成交股數" in f or "成交量" in f: col["volume"] = i
    if "date" not in col or "close" not in col:
        return []
    return _parse_rows(data.get("data", []), col)

# ──────────────────────────────────────────────
# TPEX（上櫃）— 改用 OpenAPI 每日收盤
# ──────────────────────────────────────────────
# 舊的 st43_result.php 已停用（redirect 到 /errors）。
# OpenAPI tpex_mainboard_daily_close_quotes 只有當天資料，不接受日期參數。
# 策略：只有查詢「本月」時才打 API；歷史月份直接回 []。
# 全部 10000+ 支股票一次打包，用 module-level cache 避免重複請求。
_TPEX_DAILY_CACHE: list | None = None

def _tpex_month(code: str, year: int, month: int) -> list[dict]:
    global _TPEX_DAILY_CACHE
    today = date.today()
    if year != today.year or month != today.month:
        return []
    if _TPEX_DAILY_CACHE is None:
        data = _get(
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes")
        _TPEX_DAILY_CACHE = data if isinstance(data, list) else []
    for row in _TPEX_DAILY_CACHE:
        if row.get("SecuritiesCompanyCode") == code:
            roc = row.get("Date", "")
            if len(roc) != 7:
                break
            try:
                iso = f"{int(roc[:3]) + 1911}-{roc[3:5]}-{roc[5:7]}"
            except ValueError:
                break
            c = _clean(row.get("Close", ""))
            if not c:
                break
            return [{
                "date":   iso,
                "open":   _clean(row.get("Open", "")),
                "high":   _clean(row.get("High", "")),
                "low":    _clean(row.get("Low", "")),
                "close":  c,
                "volume": _clean(row.get("TradingShares", "")),
            }]
    return []

# ──────────────────────────────────────────────
# 抓單支股票整段區間
# ──────────────────────────────────────────────
# 1：TPEX 現在只回今天，歷史月份一律 []；
# 設為 1 讓增量更新（只跑 1-2 個月）也能即時試到 TPEX。
_TWSE_GIVE_UP = 1

def fetch_stock(code: str, start: date, end: date,
                delay: float, sink: list | None = None) -> tuple[list[dict], str]:
    """sink：若傳入 list，每抓完一個月就把該月資料 extend 進去。
    主迴圈可在 KeyboardInterrupt 時用它保住中斷前已抓到的月份。"""
    all_rows: list[dict] = [] if sink is None else sink
    source = ""
    twse_miss = 0
    y, m = start.year, start.month

    while (y, m) <= (end.year, end.month):
        rows = []

        # TWSE：只有在 TPEX 已成功過（有正面證據是上櫃）才停止嘗試。
        # 不能只憑「連續 N 個月無資料」就放棄 —— 晚上市的股票前幾十個月
        # 本來就沒有資料，一旦永久停用 TWSE 就再也抓不到。
        if source != "TPEX 上櫃":
            rows = _twse_month(code, y, m)
            if rows:
                if not source: source = "TWSE 上市"
                twse_miss = 0
            else:
                twse_miss += 1

        # TPEX fallback：TWSE 連續失敗達門檻，且尚未確認是上市股，才試 TPEX
        if not rows and source != "TWSE 上市" and twse_miss >= _TWSE_GIVE_UP:
            rows = _tpex_month(code, y, m)
            if rows and not source:
                source = "TPEX 上櫃"

        all_rows.extend(rows)     # sink 與 all_rows 同一個物件，主迴圈可即時看到
        m = m + 1 if m < 12 else 1
        if m == 1: y += 1
        time.sleep(delay)

    s, e = start.isoformat(), end.isoformat()
    seen: set[str] = set()
    result = []
    for r in sorted(all_rows, key=lambda x: x["date"]):
        if s <= r["date"] <= e and r["date"] not in seen:
            seen.add(r["date"])
            result.append(r)
    return result, source

# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="批次抓自選股日線 CSV（增量更新）")
    parser.add_argument("--start",     default="2024-01-01")
    parser.add_argument("--end",       default=date.today().isoformat())
    parser.add_argument("--outdir",    default="data")
    parser.add_argument("--delay",     type=float, default=1.2)
    parser.add_argument("--only",      default="",
                        help="只抓指定代號，逗號分隔，例如 2330,3324")
    parser.add_argument("--no-resume", dest="resume", action="store_false", default=True,
                        help="全量重抓所有股票（預設為增量更新）")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    os.makedirs(args.outdir, exist_ok=True)

    watchlist = load_watchlist()
    if args.only:
        only_set = {c.strip() for c in args.only.split(",") if c.strip()}
        watchlist = [(c, n) for c, n in watchlist if c in only_set]

    total = len(watchlist)
    ok, failed, skipped = [], [], []

    print(f"\n自選股共 {total} 支　區間 {start} ～ {end}\n")
    print(f"{'#':>3}  {'代號':<8} {'名稱':<14} {'來源':<10} {'筆數':>6}  {'新增':>5}")
    print("─" * 56)

    for idx, (code, name) in enumerate(watchlist, 1):
        fname = os.path.join(args.outdir, f"{code}_{name}.csv")
        print(f"{idx:>3}  {code:<8} {name:<14} ", end="", flush=True)

        existing = read_existing(fname)
        fetch_from = resume_start(existing, start) if args.resume else start

        if args.resume and existing and fetch_from > end:
            print(f"[已是最新，{len(existing)} 筆]")
            skipped.append((code, name))
            continue

        partial: list[dict] = []
        try:
            new_rows, src = fetch_stock(code, fetch_from, end, args.delay, sink=partial)
        except KeyboardInterrupt:
            # 中斷保護：把中斷前已抓到的月份與既有資料合併後寫回，不整支重來
            salvage = merge_rows(existing, partial)
            if salvage:
                write_csv(fname, salvage)
                print(f"\n\n[中斷] {code} {name} 已保住 {len(salvage)} 筆"
                      f"（新增 {len(salvage) - len(existing)}），重跑會從這裡續抓。")
            else:
                print("\n\n[中斷] 尚無資料可保留。")
            print(f"CSV 存於 {os.path.abspath(args.outdir)}\n")
            sys.exit(130)
        merged = merge_rows(existing, new_rows)

        if not new_rows:
            reason = "TWSE+TPEX 均無資料" if not src else f"{src}：查無此區間資料"
            if existing:
                print(f"[{reason}，保留既有 {len(existing)} 筆]")
            else:
                print(f"[{reason}]")
            failed.append((code, name))
            continue

        write_csv(fname, merged)

        added = len(merged) - len(existing)
        print(f"{src:<10} {len(merged):>6} 筆  +{added:>4}")
        ok.append((code, name))

        warns = health_check(merged)
        for w in warns:
            print(f"    [健檢] {w}", file=sys.stderr)

    print("─" * 56)
    print(f"\n完成：{len(ok)} 支更新，{len(skipped)} 支已是最新，{len(failed)} 支失敗")
    if failed:
        print("失敗清單：" + "、".join(f"{c} {n}" for c, n in failed))
    print(f"CSV 存於 {os.path.abspath(args.outdir)}\n")

if __name__ == "__main__":
    main()
