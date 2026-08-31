#!/usr/bin/env python3
"""
run_gui.py — 台股資料抓取的圖形介面

相對於前一版的變更：
  1. 不再寫暫存 .bat。原本用 encoding="ascii" 寫檔，儲存位置只要含中文
     （例如「桌面\\股票資料」）就會變成 ????，抓取會寫到錯誤的路徑。
     現在直接用 subprocess.Popen 呼叫 batch_fetch.py，路徑以參數陣列傳遞，
     不經過 cmd 剖析，中文路徑、空格、& 都不會出問題。
  2. 抓取進度顯示在視窗裡，不再彈出 cmd 視窗。
  3. 加上「中斷」按鈕，可以隨時停止。
  4. 滑鼠滾輪改綁在整個清單區域 —— 原本只綁 canvas，游標移到 checkbox 上
     就滾不動。
  5. 加上「診斷 TPEX」按鈕，直接跑 probe_endpoint.py 看端點原始回應，
     不必為了看一行 stderr 而跑 32 個月。
  6. 加上「全量重抓」勾選框（對應 batch_fetch.py 的 --no-resume）。
"""

import sys, os, csv, re, subprocess, threading, queue, webbrowser
import tkinter as tk
from tkinter import messagebox, filedialog, scrolledtext

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_STOCKS = [
    ("2330","台積電"),  ("2382","廣達"),    ("2317","鴻海"),
    ("3017","奇鋐"),    ("2454","聯發科"),  ("2059","川湖"),
    ("6669","緯穎"),    ("2383","台光電"),  ("2301","光寶科"),
    ("3665","貿聯-KY"), ("3037","欣興"),    ("3324","雙鴻"),
    ("2308","台達電"),  ("6584","南俊國際"),("6505","台塑化"),
    ("2072","世紀風電"),("2377","微星"),    ("2313","華通"),
    ("2324","仁寶"),    ("2353","宏碁"),    ("6510","精測"),
    ("6919","康霈"),    ("3533","嘉澤"),    ("3529","力旺"),
    ("6213","聯茂"),    ("6515","穎崴"),    ("6223","旺矽"),
    ("7769","鴻勁"),    ("6409","旭隼"),    ("6781","AES-KY"),
    ("5274","信驊"),    ("3443","創意"),    ("3008","大立光"),
    ("3653","健策"),    ("3661","世芯-KY"), ("00919","群益台灣精選高息"),
    ("00878","國泰永續高股息"), ("2603","長榮"), ("6446","藥華藥"),
    ("2882","國泰金"),  ("2891","中信金"),  ("2881","富邦金"),
    ("2412","中華電"),  ("1216","統一"),    ("4938","和碩"),
    ("0050","元大台灣50"), ("0056","元大高股息"), ("006208","富邦台50"),
    ("6217","中探針"),  ("2303","聯電"),    ("2327","國巨"),
    ("9910","豐泰"),    ("6274","台燿"),    ("2376","技嘉"),
    ("6187","萬潤"),    ("6531","愛普"),    ("6693","廣閎科"),
]


def load_stocks():
    """讀 watchlist.csv；讀不到就用內建清單，並回報實際來源供畫面顯示。"""
    path = os.path.join(SCRIPT_DIR, "watchlist.csv")
    if not os.path.exists(path):
        return DEFAULT_STOCKS, "內建清單（找不到 watchlist.csv）"
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = [(r.get("代號", "").strip(), r.get("名稱", "").strip())
                    for r in csv.DictReader(f) if r.get("代號", "").strip()]
        if rows:
            return rows, "watchlist.csv"
        return DEFAULT_STOCKS, "內建清單（watchlist.csv 無有效資料列，可能存成了 Big5）"
    except Exception as e:
        return DEFAULT_STOCKS, f"內建清單（watchlist.csv 讀取失敗：{type(e).__name__}）"


def build_fetch_args(python_exe, script_dir, start_date, outdir,
                     selected, total, full):
    """組裝 batch_fetch.py 的參數陣列。抽成純函式以便測試。"""
    args = [python_exe, "-u", os.path.join(script_dir, "batch_fetch.py"),
            "--start", start_date, "--outdir", outdir]
    if len(selected) < total:
        args += ["--only", ",".join(selected)]
    if full:
        args.append("--no-resume")
    return args


class App:
    def __init__(self, root):
        self.root = root
        self.stocks, self.source_note = load_stocks()
        self.proc = None
        self.q = queue.Queue()

        root.title("台灣股票日線資料抓取")
        root.minsize(580, 660)

        self._build_stock_area()
        self._build_options()
        self._build_log()
        self._build_buttons()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._drain_queue)

    # ── 個股選擇 ──────────────────────────────────────────────
    def _build_stock_area(self):
        grp = tk.LabelFrame(self.root, text="選擇個股", padx=6, pady=6)
        grp.pack(fill="both", expand=True, padx=10, pady=(10, 6))

        top = tk.Frame(grp)
        top.pack(fill="x", pady=(0, 2))
        self.count_var = tk.StringVar()
        tk.Label(top, textvariable=self.count_var, anchor="w").pack(side="left")
        tk.Button(top, text="全不選", width=7,
                  command=lambda: self._set_all(False)).pack(side="right", padx=(3, 0))
        tk.Button(top, text="全選", width=7,
                  command=lambda: self._set_all(True)).pack(side="right")

        tk.Label(grp, text=f"清單來源：{self.source_note}",
                 anchor="w", fg="#666666").pack(fill="x", pady=(0, 3))

        wrap = tk.Frame(grp)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, height=250, bd=0, highlightthickness=0)
        sb = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        self.check_vars = []
        for code, name in self.stocks:
            v = tk.BooleanVar(value=True)
            self.check_vars.append(v)
            tk.Checkbutton(inner, text="%-8s %s" % (code, name), variable=v,
                           anchor="w", command=self._update_count).pack(fill="x")

        inner.bind("<Configure>", lambda e: (
            canvas.configure(scrollregion=canvas.bbox("all")),
            canvas.itemconfig(win, width=canvas.winfo_width())))

        # 變更 4：原本只綁 canvas，游標停在 checkbox 上時事件不會傳到 canvas，
        # 滾輪就沒反應。改成進入清單區時把 <MouseWheel> 綁到整個視窗。
        def on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        wrap.bind("<Enter>", lambda e: self.root.bind_all("<MouseWheel>", on_wheel))
        wrap.bind("<Leave>", lambda e: self.root.unbind_all("<MouseWheel>"))

        self._update_count()

    def _update_count(self):
        n = sum(1 for v in self.check_vars if v.get())
        self.count_var.set("已選 %d / %d 支" % (n, len(self.stocks)))

    def _set_all(self, state):
        for v in self.check_vars:
            v.set(state)
        self._update_count()

    # ── 選項 ─────────────────────────────────────────────────
    def _build_options(self):
        grp = tk.LabelFrame(self.root, text="選項", padx=6, pady=6)
        grp.pack(fill="x", padx=10, pady=(0, 6))

        r1 = tk.Frame(grp); r1.pack(fill="x", pady=2)
        tk.Label(r1, text="起始日期：", width=10, anchor="e").pack(side="left")
        self.date_var = tk.StringVar(value="2024-01-01")
        tk.Entry(r1, textvariable=self.date_var, width=14).pack(side="left")
        tk.Label(r1, text="（已有 CSV 的會增量更新，不會整段重抓）",
                 fg="#666666").pack(side="left", padx=(8, 0))

        r2 = tk.Frame(grp); r2.pack(fill="x", pady=2)
        tk.Label(r2, text="儲存位置：", width=10, anchor="e").pack(side="left")
        self.outdir_var = tk.StringVar(value=os.path.join(SCRIPT_DIR, "data"))
        tk.Entry(r2, textvariable=self.outdir_var).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(r2, text="瀏覽...", command=self._browse).pack(side="left")

        r3 = tk.Frame(grp); r3.pack(fill="x", pady=2)
        tk.Label(r3, text="", width=10).pack(side="left")
        self.full_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r3, text="全量重抓（忽略既有 CSV，57 支約 36 分鐘）",
                       variable=self.full_var).pack(side="left")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.outdir_var.get(),
                                    title="選擇 CSV 儲存資料夾")
        if d:
            self.outdir_var.set(os.path.normpath(d))

    # ── 進度輸出 ──────────────────────────────────────────────
    def _build_log(self):
        grp = tk.LabelFrame(self.root, text="進度", padx=6, pady=6)
        grp.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.log = scrolledtext.ScrolledText(grp, height=11, wrap="none",
                                             font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True)

    def _write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ── 底部按鈕 ──────────────────────────────────────────────
    def _build_buttons(self):
        f = tk.Frame(self.root)
        f.pack(fill="x", padx=10, pady=(0, 10))
        self.btn_probe = tk.Button(f, text="診斷 TPEX", width=10, command=self._probe)
        self.btn_probe.pack(side="left")
        self.btn_close = tk.Button(f, text="關閉", width=8, command=self._on_close)
        self.btn_close.pack(side="right", padx=(4, 0))
        self.btn_stop = tk.Button(f, text="中斷", width=8,
                                  command=self._stop, state="disabled")
        self.btn_stop.pack(side="right", padx=(4, 0))
        self.btn_start = tk.Button(f, text="開始抓取", width=10,
                                   bg="#2A3F66", fg="white", command=self._start)
        self.btn_start.pack(side="right")

    # ── 子行程 ───────────────────────────────────────────────
    def _run(self, args, done_msg):
        """背景執行緒跑子行程，逐行把輸出丟進 queue 給主執行緒顯示。"""
        code = -1
        try:
            # 變更 1：參數陣列直接傳給 Popen，不經 cmd 剖析，
            # 中文路徑 / 空格 / & / % 都不會被曲解。
            self.proc = subprocess.Popen(
                args, cwd=SCRIPT_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in self.proc.stdout:
                self.q.put(line)
            self.proc.wait()
            code = self.proc.returncode
        except Exception as e:
            self.q.put("\n[錯誤] %s: %s\n" % (type(e).__name__, e))
        finally:
            self.proc = None
        self.q.put(("__DONE__", code, done_msg))

    def _drain_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple):
                    _, code, msg = item
                    self._write("\n%s（結束碼 %s）\n" % (msg, code))
                    self.btn_start.configure(state="normal")
                    self.btn_probe.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                else:
                    self._write(item)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def _busy(self):
        self.btn_start.configure(state="disabled")
        self.btn_probe.configure(state="disabled")
        self.btn_stop.configure(state="normal")

    def _start(self):
        selected = [self.stocks[i][0]
                    for i, v in enumerate(self.check_vars) if v.get()]
        if not selected:
            messagebox.showwarning("提示", "請至少選擇一支個股。")
            return
        start_date = self.date_var.get().strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
            messagebox.showerror("錯誤",
                                 "日期格式錯誤，請輸入 YYYY-MM-DD（例如 2024-01-01）。")
            return
        outdir = self.outdir_var.get().strip()
        if not outdir:
            messagebox.showerror("錯誤", "請指定儲存位置。")
            return

        args = build_fetch_args(sys.executable, SCRIPT_DIR, start_date, outdir,
                                selected, len(self.stocks), self.full_var.get())

        self._write("\n%s\n起始日期：%s\n儲存位置：%s\n選取 %d / %d 支%s\n%s\n" % (
            "=" * 58, start_date, outdir, len(selected), len(self.stocks),
            "（全量重抓）" if self.full_var.get() else "（增量更新）", "=" * 58))
        self._busy()
        threading.Thread(target=self._run, args=(args, "抓取結束"),
                         daemon=True).start()

    def _probe(self):
        """跑 probe_endpoint.py 看端點原始回應，不必跑滿 32 個月。"""
        probe = os.path.join(SCRIPT_DIR, "probe_endpoint.py")
        if not os.path.exists(probe):
            messagebox.showerror("錯誤", "找不到 probe_endpoint.py。")
            return
        selected = [self.stocks[i][0]
                    for i, v in enumerate(self.check_vars) if v.get()]
        code = selected[0] if selected else "6223"
        from datetime import date
        d = date.today()
        y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
        self._write("\n%s\n診斷端點：代號 %s，%d-%02d\n%s\n"
                    % ("=" * 58, code, y, m, "=" * 58))
        self._busy()
        threading.Thread(
            target=self._run,
            args=([sys.executable, "-u", probe, code, str(y), str(m)], "診斷結束"),
            daemon=True).start()

    def _stop(self):
        if self.proc:
            self._write("\n[中斷] 正在停止子行程...\n")
            try:
                self.proc.terminate()
            except Exception as e:
                self._write("[中斷失敗] %s: %s\n" % (type(e).__name__, e))

    def _on_close(self):
        if self.proc:
            if not messagebox.askyesno("確認", "作業還在進行中，確定要關閉嗎？"):
                return
            try:
                self.proc.terminate()
            except Exception:
                pass
        analyzer = os.path.join(SCRIPT_DIR, "tw-stock-analyzer.html")
        if os.path.exists(analyzer) and messagebox.askyesno(
                "開啟分析工具", "要開啟分析工作台嗎？"):
            webbrowser.open(analyzer)
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
