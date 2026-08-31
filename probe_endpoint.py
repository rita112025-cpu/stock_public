#!/usr/bin/env python3
"""
probe_endpoint.py — 單次探測 TWSE / TPEx 端點，把「原始回應」原封不動印出來。

為什麼需要這支：
  batch_fetch.py 的 _get() 先做 json.loads()，一旦回應不是 JSON 就只印
  「JSONDecodeError」然後回傳 None，看不到伺服器到底回了什麼。
  而且 _TWSE_GIVE_UP=3 讓 TPEX 要到第 4 個月才被嘗試，想診斷得先跑 32 個月。
  這支直接打一次，不解析、不判斷，只把事實印出來。

用法：
    python probe_endpoint.py 6223 2026 8
    python probe_endpoint.py 6223 2026 8 --save probe_out

輸出：HTTP 狀態碼、Content-Type、回應長度、前 400 個字元、
      若是 JSON 則列出頂層 key 與第一列資料。
"""

import sys, os, ssl, json, argparse
from urllib.request import urlopen, Request
from urllib.error import HTTPError

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = ssl.create_default_context()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def probe(label: str, url: str, referer: str = "", save_dir: str = "") -> None:
    print("=" * 72)
    print(f"[{label}]")
    print(f"URL: {url}")
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if referer:
        headers["Referer"] = referer

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=20, context=_SSL) as r:
            status = r.status
            ctype = r.headers.get("Content-Type", "(無)")
            final = r.geturl()
            raw = r.read()
    except HTTPError as e:
        status, ctype, final = e.code, e.headers.get("Content-Type", "(無)"), url
        raw = e.read()
    except Exception as e:
        print(f"連線失敗：{type(e).__name__}: {e}")
        print("=" * 72 + "\n")
        return

    print(f"HTTP 狀態    : {status}")
    print(f"Content-Type: {ctype}")
    print(f"回應長度    : {len(raw)} bytes")
    if final != url:
        print(f"被轉址到    : {final}")

    if not raw:
        print("回應是空的 —— 這就是 JSONDecodeError 的原因。")
        print("=" * 72 + "\n")
        return

    text = raw.decode("utf-8", errors="replace")
    print("-" * 72)
    print("前 400 字元：")
    print(text[:400])
    print("-" * 72)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"不是 JSON（{e}）")
        print("=" * 72 + "\n")
        return

    if isinstance(data, dict):
        print(f"JSON 頂層 key：{list(data.keys())}")
        for k, v in data.items():
            if isinstance(v, list) and v:
                print(f"  → '{k}' 是長度 {len(v)} 的陣列，第一列：")
                print(f"      {v[0]}")
            elif isinstance(v, list):
                print(f"  → '{k}' 是空陣列")
    elif isinstance(data, list):
        print(f"JSON 頂層是長度 {len(data)} 的陣列，第一列：")
        if data:
            print(f"  {data[0]}")

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        p = os.path.join(save_dir, f"{label.replace(' ', '_')}.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"URL: {url}\nHTTP: {status}\nContent-Type: {ctype}\n\n{text}")
        print(f"完整回應已存到 {p}")

    print("=" * 72 + "\n")


def main():
    ap = argparse.ArgumentParser(description="探測 TWSE / TPEx 端點的原始回應")
    ap.add_argument("code", help="股票代號，例如 6223")
    ap.add_argument("year", type=int, help="西元年，例如 2026")
    ap.add_argument("month", type=int, help="月份，例如 8")
    ap.add_argument("--save", default="", metavar="DIR",
                    help="把完整回應存進這個資料夾")
    a = ap.parse_args()

    code, y, m = a.code, a.year, a.month
    roc = y - 1911

    # batch_fetch.py 目前實際使用的兩支
    probe("TWSE STOCK_DAY（batch_fetch 使用中）",
          "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
          f"?date={y}{m:02d}01&stockNo={code}&response=json",
          save_dir=a.save)

    probe("TPEx st43_result（batch_fetch 使用中）",
          "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/"
          f"st43_result.php?l=zh-tw&d={roc}/{m:02d}&stkno={code}&s=0,asc",
          referer="https://www.tpex.org.tw/web/stock/aftertrading/"
                  "daily_trading_info/st43.php?l=zh-tw",
          save_dir=a.save)

    # 幾個候選路徑。【無法驗證】我沒有官方文件證明這些現在有效，
    # 純粹是讓你一次看完哪一支真的回得出資料。
    probe("候選 A：tpex www 新路徑",
          "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
          f"?code={code}&date={y}{m:02d}01&id=&response=json",
          referer="https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html",
          save_dir=a.save)

    probe("候選 B：tpex OpenAPI 當日收盤（無日期參數）",
          "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
          save_dir=a.save)

    roc = y - 1911
    probe(f"候選 C：OpenAPI + 西元日期 {y}{m:02d}01",
          f"https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
          f"?date={y}{m:02d}01",
          save_dir=a.save)

    probe(f"候選 D：OpenAPI + 民國日期 {roc}{m:02d}01",
          f"https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
          f"?date={roc}{m:02d}01",
          save_dir=a.save)

    probe(f"候選 E：候選 A 改民國日期",
          f"https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
          f"?code={code}&date={roc}{m:02d}01&response=json",
          save_dir=a.save)

    print("判讀方式：")
    print("  1. 哪一支的『HTTP 狀態 = 200』且『能解析成 JSON』且『陣列有資料』，那支就是可用的。")
    print("  2. 把那支的『頂層 key』與『第一列』貼出來，就能對上欄位順序。")
    print("  3. 若全部都是空回應或 HTML，代表要改用網頁版的請求方式（帶 Referer / Cookie），")
    print("     或這幾支端點已經停用。")


if __name__ == "__main__":
    main()
