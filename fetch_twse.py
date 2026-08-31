#!/usr/bin/env python3
"""
台股日線資料抓取工具 — 證交所官方 API（上市股票）
用法：
    python fetch_twse.py 2330
    python fetch_twse.py 2330 --start 2023-01-01 --end 2024-12-31
    python fetch_twse.py 2330 --out my_data.csv
輸出為 UTF-8 BOM 的 CSV，可直接丟進台股個股分析工作台。
"""

import csv
import json
import ssl
import sys
import time
import argparse
from datetime import date
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()   # 使用系統憑證庫


# ---------- 抓單月資料 ----------
def fetch_month(stock_no: str, year: int, month: int) -> list[dict]:
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
        f"?date={year}{month:02d}01&stockNo={stock_no}&response=json"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            payload = json.loads(resp.read())
    except (URLError, HTTPError) as e:
        print(f"  [警告] {year}/{month:02d} 連線失敗：{e}", file=sys.stderr)
        return []

    if payload.get("stat") != "OK":
        # stat 可能是 "很抱歉，沒有符合條件的資料！" 等
        return []

    fields = payload.get("fields", [])
    data   = payload.get("data",   [])

    # 找欄位索引（證交所欄位：日期/成交股數/成交金額/開盤價/最高價/最低價/收盤價/漲跌/筆數）
    col = {}
    for i, f in enumerate(fields):
        if "日期"   in f:                          col["date"]   = i
        if "開盤"   in f:                          col["open"]   = i
        if "最高"   in f:                          col["high"]   = i
        if "最低"   in f:                          col["low"]    = i
        if "收盤"   in f:                          col["close"]  = i
        if "成交股數" in f or ("成交量" in f):     col["volume"] = i

    if "date" not in col or "close" not in col:
        return []

    def clean(v: str) -> str:
        return v.strip().replace(",", "").lstrip("+")

    rows = []
    for row in data:
        # 民國日期 114/08/01 → 2025-08-01
        parts = row[col["date"]].split("/")
        if len(parts) != 3:
            continue
        try:
            iso = f"{int(parts[0])+1911}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except ValueError:
            continue

        close_raw = clean(row[col["close"]])
        if close_raw in ("", "--", "-", "X"):
            continue   # 停牌或無資料

        rows.append({
            "date":   iso,
            "open":   clean(row[col["open"]])   if "open"   in col else "",
            "high":   clean(row[col["high"]])   if "high"   in col else "",
            "low":    clean(row[col["low"]])    if "low"    in col else "",
            "close":  close_raw,
            "volume": clean(row[col["volume"]]) if "volume" in col else "",
        })
    return rows


# ---------- 抓整段區間 ----------
def fetch_range(stock_no: str, start: date, end: date, delay: float) -> list[dict]:
    all_rows: list[dict] = []
    y, m = start.year, start.month

    while (y, m) <= (end.year, end.month):
        print(f"  {y}/{m:02d} … ", end="", flush=True)
        rows = fetch_month(stock_no, y, m)
        print(f"{len(rows)} 筆")
        all_rows.extend(rows)

        # 往下一個月
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1

        time.sleep(delay)   # 避免打太快被擋

    # 過濾到指定區間、去重、排序
    s, e = start.isoformat(), end.isoformat()
    seen: set[str] = set()
    result = []
    for r in sorted(all_rows, key=lambda x: x["date"]):
        if s <= r["date"] <= e and r["date"] not in seen:
            seen.add(r["date"])
            result.append(r)
    return result


# ---------- 主程式 ----------
def main():
    parser = argparse.ArgumentParser(
        description="從證交所抓上市個股日線 (OHLCV)，存成 CSV"
    )
    parser.add_argument("stock",
        help="股票代號，例如 2330")
    parser.add_argument("--start", default="2024-01-01",
        help="開始日期 YYYY-MM-DD（預設 2024-01-01）")
    parser.add_argument("--end", default=date.today().isoformat(),
        help="結束日期 YYYY-MM-DD（預設今天）")
    parser.add_argument("--out",
        help="輸出檔名（預設 {股票代號}_daily.csv）")
    parser.add_argument("--delay", type=float, default=1.5,
        help="每月請求間隔秒數（預設 1.5，請勿設太低）")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    out   = args.out or f"{args.stock}_daily.csv"

    if start > end:
        sys.exit("錯誤：開始日期不能晚於結束日期。")

    print(f"\n股票代號：{args.stock}")
    print(f"日期範圍：{start}  ～  {end}")
    print(f"資料來源：TWSE STOCK_DAY API（上市股票）")
    print(f"輸出檔案：{out}\n")

    rows = fetch_range(args.stock, start, end, args.delay)

    if not rows:
        sys.exit("\n[錯誤] 沒有抓到任何資料。請確認股票代號正確，且該股票為上市（非上櫃）股票。")

    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["date", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n完成：共 {len(rows)} 筆，已存至 {out}")
    print("（UTF-8 BOM 編碼，可直接丟進台股個股分析工作台）")

    # 簡易預覽最後 3 筆
    print("\n最後 3 筆預覽：")
    print("date        open     high     low      close    volume")
    for r in rows[-3:]:
        print(f"{r['date']}  {r['open']:<8} {r['high']:<8} {r['low']:<8} {r['close']:<8} {r['volume']}")


if __name__ == "__main__":
    main()
