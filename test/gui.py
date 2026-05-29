"""国内基金分析与买卖决策 —— 图形界面（tkinter）。

四个功能页：
  1. 信号分析：管理自选基金，批量计算技术指标信号 + 仓位操作建议；
  2. 持仓估值：按基金重仓股的实时涨跌，估算该基金当日涨跌；
  3. 交易记录：记录每日实际买卖操作，自动汇总持仓；
  4. 资金设置：设置总仓位金额，查看整体投入/现金占比。

所有联网操作都在后台线程执行，通过 queue + after 回主线程刷新界面，
避免窗口卡死。
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import messagebox, ttk

if __package__:
    from . import dead_funds, data_fetcher, market, portfolio, trade_log, watchlist
    from .data_fetcher import FundDataEmpty
    from .indicators import compute_indicators
    from .strategy import evaluate_signals
else:  # 允许直接 python test/gui.py 运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from test import dead_funds, data_fetcher, market, portfolio, trade_log, watchlist
    from test.data_fetcher import FundDataEmpty
    from test.indicators import compute_indicators
    from test.strategy import evaluate_signals

# 并发线程数：东财接口并发过高会限流，6~8 较稳妥
_MAX_WORKERS = 8


_ACTION_COLORS = {
    "强烈买入": "#c0392b",
    "买入": "#e67e22",
    "观望": "#7f8c8d",
    "卖出": "#2980b9",
    "强烈卖出": "#16a085",
}

_UP_COLOR = "#c0392b"
_DOWN_COLOR = "#16a085"


def _analyze_one_fund(code: str, total_capital: float, with_estimate: bool) -> dict:
    """分析单只基金（供线程池调用）。失败的空数据基金会被登记为已清盘。"""
    try:
        nav_df = data_fetcher.fetch_fund_nav(code)
        ind = compute_indicators(nav_df)
        name = data_fetcher.fetch_fund_name(code)
        report = evaluate_signals(ind, code, name)
        adv = portfolio.advise(report, total_capital)
        est = None
        if with_estimate:
            e = data_fetcher.fetch_fund_estimate(code)
            if e:
                est = {"estimate_pct": e["gszzl"], "time": e.get("gztime", "")}
        last = trade_log.last_trade(code)
        return {"code": code, "report": report, "adv": adv,
                "est": est, "last": last, "error": None}
    except FundDataEmpty:
        dead_funds.mark_dead(code, "无净值数据")
        return {"code": code, "error": "已清盘/无数据", "dead": True}
    except Exception as exc:  # noqa: BLE001
        return {"code": code, "error": str(exc)}


class FundApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("国内基金技术分析与买卖决策助手")
        self.geometry("1080x680")
        self.minsize(960, 600)

        self._task_queue: "queue.Queue" = queue.Queue()
        self._busy = False
        self._scoring = False
        self._all_funds = None  # 全市场基金列表缓存 (DataFrame)
        self._detail_windows: dict = {}

        self._build_style()
        self._build_tabs()
        self._poll_queue()

        # 初始化各页数据
        self._refresh_watchlist_box()
        self._refresh_trades_table()
        self._refresh_capital_view()

    # ------------------------------------------------------------------ #
    # 界面构建
    # ------------------------------------------------------------------ #
    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=26, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 10))
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 12, "bold"))

    def _build_tabs(self) -> None:
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=6)

        self._build_home_tab()
        self._build_analysis_tab()
        self._build_allfunds_tab()
        self._build_holdings_tab()
        self._build_trades_tab()
        self._build_capital_tab()

        self.status = tk.StringVar(value="就绪")
        bar = ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken")
        bar.pack(fill="x", side="bottom")

    # ---- Tab 0: 首页（大盘指数） -------------------------------------- #
    def _build_home_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  首页  ")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Label(top, text="大盘指数 · 当日行情", style="Title.TLabel").pack(side="left")
        self.idx_refresh_btn = ttk.Button(top, text="刷新行情", command=self._on_refresh_indices)
        self.idx_refresh_btn.pack(side="right")
        self.idx_time_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.idx_time_var, foreground="#7f8c8d").pack(side="right", padx=8)

        cols = ("name", "code", "price", "change", "pct")
        headers = {"name": "指数", "code": "代码", "price": "最新点位",
                   "change": "涨跌", "pct": "涨跌幅%"}
        self.idx_tree = ttk.Treeview(tab, columns=cols, show="headings", height=10)
        for c in cols:
            self.idx_tree.heading(c, text=headers[c])
            self.idx_tree.column(c, width=140, anchor="center")
        self.idx_tree.column("name", anchor="w", width=180)
        self.idx_tree.pack(fill="x", padx=10, pady=6)
        self.idx_tree.tag_configure("up", foreground=_UP_COLOR)
        self.idx_tree.tag_configure("down", foreground=_DOWN_COLOR)
        self.idx_tree.bind("<Double-1>", self._on_index_detail)

        ttk.Label(tab, text="双击任一指数查看详情（开高低/昨收/近月走势）。",
                  foreground="#7f8c8d").pack(anchor="w", padx=12, pady=2)

        # 进入即自动加载一次
        self.after(300, self._on_refresh_indices)

    def _on_refresh_indices(self) -> None:
        self.idx_refresh_btn.config(state="disabled")
        self._run_async(market.fetch_index_spot, self._on_indices_done)

    def _on_indices_done(self, rows) -> None:
        self.idx_refresh_btn.config(state="normal")
        for item in self.idx_tree.get_children():
            self.idx_tree.delete(item)
        for r in rows:
            pct = r["change_pct"]
            tag = "up" if (pct or 0) >= 0 else "down"
            price = f"{r['price']:,.2f}" if r["price"] is not None else "-"
            change = f"{r['change']:+.2f}" if r["change"] is not None else "-"
            pct_str = f"{pct:+.2f}" if pct is not None else "-"
            self.idx_tree.insert("", tk.END, values=(
                r["name"], r["code"], price, change, pct_str), tags=(tag,))
        import datetime as _d
        self.idx_time_var.set("更新于 " + _d.datetime.now().strftime("%H:%M:%S"))

    def _on_index_detail(self, _event) -> None:
        item = self.idx_tree.focus()
        if not item:
            return
        vals = self.idx_tree.item(item, "values")
        if vals:
            IndexDetailWindow(self, vals[1], vals[0])

    # ---- Tab 1: 信号分析 ---------------------------------------------- #
    def _build_analysis_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  信号分析  ")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="自选基金代码:").pack(side="left")
        self.add_code_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.add_code_var, width=12).pack(side="left", padx=4)
        ttk.Button(top, text="添加", command=self._on_add_fund).pack(side="left", padx=2)
        ttk.Button(top, text="删除选中", command=self._on_remove_fund).pack(side="left", padx=2)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)

        self.intraday_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            top, text="含实时估值", variable=self.intraday_var
        ).pack(side="left", padx=4)
        self.analyze_btn = ttk.Button(top, text="开始分析", command=self._on_analyze)
        self.analyze_btn.pack(side="left", padx=6)

        # 主体：左侧自选列表 + 右侧结果表
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="自选清单", style="Title.TLabel").pack(anchor="w")
        self.watch_box = tk.Listbox(left, width=14, height=22, exportselection=False)
        self.watch_box.pack(fill="y", expand=True, pady=4)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        cols = ("code", "name", "nav", "est", "score", "action", "suggest", "amount", "last")
        headers = {
            "code": "代码", "name": "名称", "nav": "净值", "est": "实时估算%",
            "score": "评分", "action": "信号", "suggest": "仓位操作",
            "amount": "建议金额", "last": "上次操作",
        }
        widths = {
            "code": 60, "name": 150, "nav": 70, "est": 80, "score": 60,
            "action": 80, "suggest": 70, "amount": 90, "last": 130,
        }
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=18)
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.column("name", anchor="w")
        self.tree.column("last", anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        vs = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        vs.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=vs.set)

        for action, color in _ACTION_COLORS.items():
            self.tree.tag_configure(action, foreground=color)

        self.tree.bind("<Double-1>", self._on_row_detail)

    # ---- Tab: 全部基金 ------------------------------------------------ #
    def _build_allfunds_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  全部基金  ")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        self.all_load_btn = ttk.Button(top, text="加载基金列表", command=self._on_load_all_funds)
        self.all_load_btn.pack(side="left", padx=2)

        ttk.Label(top, text="类型:").pack(side="left", padx=(10, 2))
        self.all_cat_var = tk.StringVar(value="全部")
        self.all_cat_box = ttk.Combobox(top, textvariable=self.all_cat_var, width=8,
                                         state="readonly", values=["全部"])
        self.all_cat_box.pack(side="left", padx=2)
        self.all_cat_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_allfunds_table())

        ttk.Label(top, text="行业:").pack(side="left", padx=(8, 2))
        self.all_ind_var = tk.StringVar(value="全部")
        self.all_ind_box = ttk.Combobox(
            top, textvariable=self.all_ind_var, width=14, state="readonly",
            values=["全部"] + data_fetcher.list_industries())
        self.all_ind_box.pack(side="left", padx=2)
        self.all_ind_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_allfunds_table())

        ttk.Label(top, text="搜索(代码/名称):").pack(side="left", padx=(10, 2))
        self.all_search_var = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.all_search_var, width=16)
        ent.pack(side="left", padx=2)
        ent.bind("<Return>", lambda _e: self._refresh_allfunds_table())
        ttk.Button(top, text="筛选", command=self._refresh_allfunds_table).pack(side="left", padx=2)

        ttk.Label(top, text="显示上限").pack(side="left", padx=(10, 2))
        self.all_limit_var = tk.IntVar(value=300)
        ttk.Spinbox(top, from_=50, to=3000, increment=50, width=6,
                    textvariable=self.all_limit_var).pack(side="left")

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)
        self.all_score_btn = ttk.Button(top, text="对列表评分", command=self._on_score_all)
        self.all_score_btn.pack(side="left", padx=2)
        ttk.Button(top, text="按评分排序", command=lambda: self._sort_allfunds_by_score()).pack(
            side="left", padx=2)
        ttk.Button(top, text="加入自选", command=self._on_add_selected_to_watch).pack(
            side="left", padx=2)

        self.all_count_var = tk.StringVar(value="未加载。点击「加载基金列表」获取全市场基金。")
        ttk.Label(tab, textvariable=self.all_count_var).pack(anchor="w", padx=10)

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("code", "name", "score", "action")
        headers = {"code": "代码", "name": "基金名称", "score": "评分", "action": "信号"}
        widths = {"code": 80, "name": 320, "score": 80, "action": 90}
        self.all_tree = ttk.Treeview(body, columns=cols, show="headings", height=20)
        for c in cols:
            self.all_tree.heading(c, text=headers[c])
            self.all_tree.column(c, width=widths[c], anchor="center")
        self.all_tree.column("name", anchor="w")
        self.all_tree.pack(side="left", fill="both", expand=True)
        vs = ttk.Scrollbar(body, orient="vertical", command=self.all_tree.yview)
        vs.pack(side="left", fill="y")
        self.all_tree.configure(yscrollcommand=vs.set)
        for action, color in _ACTION_COLORS.items():
            self.all_tree.tag_configure(action, foreground=color)
        self.all_tree.bind("<Double-1>", self._on_allfund_detail)

        tip = ("提示：全市场基金过万，评分仅针对当前列表显示的基金（受「显示上限」控制），"
               "逐只联网较慢。建议先用搜索缩小范围，或调小显示上限。")
        ttk.Label(tab, text=tip, foreground="#7f8c8d", wraplength=1000,
                  justify="left").pack(anchor="w", padx=10, pady=4)

    def _on_load_all_funds(self) -> None:
        self.all_load_btn.config(state="disabled")
        self.all_count_var.set("正在加载全市场基金列表…")
        self._run_async(data_fetcher.list_all_funds, self._on_all_funds_loaded)

    def _on_all_funds_loaded(self, df) -> None:
        self.all_load_btn.config(state="normal")
        self._all_funds = df
        # 填充板块下拉
        try:
            cats = ["全部"] + data_fetcher.list_fund_categories()
            self.all_cat_box.config(values=cats)
        except Exception:
            pass
        self._refresh_allfunds_table()

    def _refresh_allfunds_table(self) -> None:
        if self._all_funds is None:
            return
        for item in self.all_tree.get_children():
            self.all_tree.delete(item)

        df = self._all_funds
        # 过滤已清盘基金
        dead = dead_funds.dead_set()
        if dead:
            df = df[~df["code"].astype(str).isin(dead)]

        # 类型筛选
        cat = self.all_cat_var.get()
        if cat and cat != "全部" and "type" in df.columns:
            df = df[df["type"].astype(str).str.startswith(cat)]

        # 行业/主题筛选
        ind = self.all_ind_var.get()
        if ind and ind != "全部":
            df = data_fetcher.filter_funds_by_industry(df, ind)

        # 关键字搜索
        kw = self.all_search_var.get().strip()
        if kw:
            mask = df["code"].astype(str).str.contains(kw) | df["name"].astype(str).str.contains(kw)
            df = df[mask]

        total_match = len(df)
        limit = int(self.all_limit_var.get())
        df = df.head(limit)

        for _, row in df.iterrows():
            self.all_tree.insert("", tk.END,
                                 values=(str(row["code"]), str(row["name"]), "", ""))

        self.all_count_var.set(
            f"匹配 {total_match} 只，显示前 {len(df)} 只"
            f"（已加载 {len(self._all_funds)} 只，已过滤清盘 {dead_funds.count()} 只）。"
            f" 双击任意行查看详情。")

    def _on_add_selected_to_watch(self) -> None:
        sel = self.all_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择基金。")
            return
        for item in sel:
            code = self.all_tree.item(item, "values")[0]
            watchlist.add_fund(code)
        self._refresh_watchlist_box()
        self._set_status(f"已将 {len(sel)} 只基金加入自选。")

    def _on_score_all(self) -> None:
        if self._scoring:
            messagebox.showinfo("提示", "评分进行中，请稍候。")
            return
        items = list(self.all_tree.get_children())
        if not items:
            messagebox.showinfo("提示", "列表为空，请先加载并筛选基金。")
            return
        codes = [(it, self.all_tree.item(it, "values")[0]) for it in items]
        self._scoring = True
        self.all_score_btn.config(state="disabled")
        threading.Thread(target=self._score_all_worker, args=(codes,), daemon=True).start()

    def _score_all_worker(self, codes) -> None:
        data_fetcher.fetch_fund_name("000001")  # 预热名称缓存，避免并发冷启动
        total = len(codes)
        counter = {"done": 0}

        def score_one(item, code):
            try:
                nav_df = data_fetcher.fetch_fund_nav(code)
                ind = compute_indicators(nav_df)
                report = evaluate_signals(ind, code, data_fetcher.fetch_fund_name(code))
                return item, report.composite_score, report.action
            except FundDataEmpty:
                dead_funds.mark_dead(code, "无净值数据")
                return item, None, "已清盘"
            except Exception:  # noqa: BLE001
                return item, None, "失败"

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
            futs = [ex.submit(score_one, item, code) for item, code in codes]
            for fut in as_completed(futs):
                item, score, action = fut.result()
                counter["done"] += 1
                self._post(self._update_score_row, (item, score, action))
                self._post(self._set_status, f"评分中 {counter['done']}/{total} …")
        self._post(self._after_score_all, None)

    def _update_score_row(self, payload) -> None:
        item, score, action = payload
        if not self.all_tree.exists(item):
            return
        if action == "已清盘":
            # 已登记为死基，直接从列表移除
            self.all_tree.delete(item)
            return
        vals = list(self.all_tree.item(item, "values"))
        vals[2] = f"{score:+.2f}" if score is not None else "-"
        vals[3] = action
        tag = action if action in _ACTION_COLORS else ""
        self.all_tree.item(item, values=vals, tags=(tag,) if tag else ())

    def _after_score_all(self, _payload) -> None:
        self._scoring = False
        self.all_score_btn.config(state="normal")
        self._sort_allfunds_by_score()
        self._set_status("评分完成，已按评分从高到低排序。")

    def _sort_allfunds_by_score(self) -> None:
        items = list(self.all_tree.get_children())

        def key(it):
            raw = self.all_tree.item(it, "values")[2]
            try:
                return float(raw)
            except (ValueError, TypeError):
                return float("-inf")

        for idx, it in enumerate(sorted(items, key=key, reverse=True)):
            self.all_tree.move(it, "", idx)

    def _on_allfund_detail(self, _event) -> None:
        item = self.all_tree.focus()
        if not item:
            return
        vals = self.all_tree.item(item, "values")
        if vals:
            self.open_detail(vals[0])

    # ---- Tab 2: 持仓估值 ---------------------------------------------- #
    def _build_holdings_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  持仓估值  ")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="基金代码:").pack(side="left")
        self.hold_code_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.hold_code_var, width=12).pack(side="left", padx=4)
        ttk.Label(top, text="取前").pack(side="left")
        self.hold_topn_var = tk.IntVar(value=10)
        ttk.Spinbox(top, from_=3, to=20, width=4, textvariable=self.hold_topn_var).pack(side="left", padx=2)
        ttk.Label(top, text="大重仓股").pack(side="left")
        self.hold_btn = ttk.Button(top, text="估算当日涨跌", command=self._on_estimate_holdings)
        self.hold_btn.pack(side="left", padx=8)

        self.hold_summary = tk.StringVar(value="输入基金代码后点击估算。")
        ttk.Label(tab, textvariable=self.hold_summary, style="Title.TLabel").pack(
            anchor="w", padx=10, pady=4
        )

        cols = ("code", "name", "weight", "change", "contrib")
        headers = {"code": "股票代码", "name": "股票名称", "weight": "占净值比例%",
                   "change": "当日涨跌%", "contrib": "贡献(权重×涨跌)"}
        self.hold_tree = ttk.Treeview(tab, columns=cols, show="headings", height=18)
        for c in cols:
            self.hold_tree.heading(c, text=headers[c])
            self.hold_tree.column(c, width=140, anchor="center")
        self.hold_tree.column("name", anchor="w")
        self.hold_tree.pack(fill="both", expand=True, padx=10, pady=6)
        self.hold_tree.tag_configure("up", foreground="#c0392b")
        self.hold_tree.tag_configure("down", foreground="#16a085")

    # ---- Tab 3: 交易记录 ---------------------------------------------- #
    def _build_trades_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  交易记录  ")

        form = ttk.LabelFrame(tab, text="记录一笔操作")
        form.pack(fill="x", padx=8, pady=6)

        self.t_code = tk.StringVar()
        self.t_action = tk.StringVar(value=trade_log.BUY)
        self.t_amount = tk.StringVar()
        self.t_nav = tk.StringVar()
        self.t_note = tk.StringVar()

        ttk.Label(form, text="基金代码").grid(row=0, column=0, padx=4, pady=6, sticky="e")
        ttk.Entry(form, textvariable=self.t_code, width=10).grid(row=0, column=1, padx=4)
        ttk.Label(form, text="操作").grid(row=0, column=2, padx=4, sticky="e")
        ttk.Combobox(
            form, textvariable=self.t_action, values=[trade_log.BUY, trade_log.SELL],
            width=6, state="readonly",
        ).grid(row=0, column=3, padx=4)
        ttk.Label(form, text="金额(元)").grid(row=0, column=4, padx=4, sticky="e")
        ttk.Entry(form, textvariable=self.t_amount, width=10).grid(row=0, column=5, padx=4)
        ttk.Label(form, text="成交净值").grid(row=0, column=6, padx=4, sticky="e")
        ttk.Entry(form, textvariable=self.t_nav, width=8).grid(row=0, column=7, padx=4)
        ttk.Button(form, text="填最新净值", command=self._on_fill_nav).grid(row=0, column=8, padx=4)

        ttk.Label(form, text="备注").grid(row=1, column=0, padx=4, pady=6, sticky="e")
        ttk.Entry(form, textvariable=self.t_note, width=40).grid(
            row=1, column=1, columnspan=5, padx=4, sticky="w"
        )
        ttk.Button(form, text="保存记录", command=self._on_add_trade).grid(
            row=1, column=7, columnspan=2, padx=4
        )

        cols = ("date", "code", "action", "amount", "nav", "shares", "note")
        headers = {"date": "日期", "code": "代码", "action": "操作", "amount": "金额",
                   "nav": "净值", "shares": "份额", "note": "备注"}
        self.trade_tree = ttk.Treeview(tab, columns=cols, show="headings", height=16)
        for c in cols:
            self.trade_tree.heading(c, text=headers[c])
            self.trade_tree.column(c, width=110, anchor="center")
        self.trade_tree.column("note", width=220, anchor="w")
        self.trade_tree.pack(fill="both", expand=True, padx=8, pady=4)
        self.trade_tree.tag_configure(trade_log.BUY, foreground="#c0392b")
        self.trade_tree.tag_configure(trade_log.SELL, foreground="#16a085")

        ttk.Button(tab, text="删除选中记录", command=self._on_delete_trade).pack(
            anchor="e", padx=8, pady=4
        )

    # ---- Tab 4: 资金设置 ---------------------------------------------- #
    def _build_capital_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  资金设置  ")

        row = ttk.Frame(tab)
        row.pack(fill="x", padx=10, pady=10)
        ttk.Label(row, text="总仓位金额(元):", style="Title.TLabel").pack(side="left")
        self.capital_var = tk.StringVar(value=str(portfolio.get_total_capital() or ""))
        ttk.Entry(row, textvariable=self.capital_var, width=16).pack(side="left", padx=6)
        ttk.Button(row, text="保存", command=self._on_save_capital).pack(side="left")

        self.capital_info = tk.StringVar()
        info = ttk.Label(tab, textvariable=self.capital_info, justify="left",
                         font=("Microsoft YaHei UI", 11))
        info.pack(anchor="w", padx=12, pady=8)

        ttk.Button(tab, text="刷新整体仓位概览", command=self._on_refresh_overview).pack(
            anchor="w", padx=12, pady=4
        )
        self.overview_info = tk.StringVar(value="点击上方按钮，根据交易记录与最新净值刷新整体仓位。")
        ttk.Label(tab, textvariable=self.overview_info, justify="left",
                  font=("Microsoft YaHei UI", 11)).pack(anchor="w", padx=12, pady=4)

    # ------------------------------------------------------------------ #
    # 通用：后台任务调度
    # ------------------------------------------------------------------ #
    def _run_async(self, func, on_done, *args) -> None:
        """在后台线程跑 func，结果/异常通过队列回主线程交给 on_done。"""
        if self._busy:
            messagebox.showinfo("提示", "已有任务在执行，请稍候。")
            return
        self._busy = True
        self._set_status("处理中…")

        def worker():
            try:
                result = func(*args)
                self._task_queue.put(("ok", on_done, result))
            except Exception as exc:  # noqa: BLE001
                self._task_queue.put(("err", on_done, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _post(self, callback, payload=None) -> None:
        """从后台线程向主线程投递一次 UI 更新（不影响单飞任务的忙碌标志）。"""
        self._task_queue.put(("ui", callback, payload))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, callback, payload = self._task_queue.get_nowait()
                if kind == "ui":
                    # 进度类回调：不重置 _busy，不改状态栏
                    callback(payload)
                    continue
                self._busy = False
                self._set_status("就绪")
                if kind == "ok":
                    callback(payload)
                else:
                    messagebox.showerror("出错了", str(payload))
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _set_status(self, text: str) -> None:
        self.status.set(text)

    # ------------------------------------------------------------------ #
    # Tab1 事件
    # ------------------------------------------------------------------ #
    def _refresh_watchlist_box(self) -> None:
        self.watch_box.delete(0, tk.END)
        for code in watchlist.get_watchlist():
            self.watch_box.insert(tk.END, code)

    def _on_add_fund(self) -> None:
        code = self.add_code_var.get().strip()
        if not code:
            return
        watchlist.add_fund(code)
        self.add_code_var.set("")
        self._refresh_watchlist_box()

    def _on_remove_fund(self) -> None:
        sel = self.watch_box.curselection()
        for idx in sel:
            watchlist.remove_fund(self.watch_box.get(idx))
        self._refresh_watchlist_box()

    def _on_analyze(self) -> None:
        codes = watchlist.get_watchlist()
        if not codes:
            messagebox.showinfo("提示", "自选清单为空，请先添加基金代码。")
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        with_intraday = self.intraday_var.get()
        self.analyze_btn.config(state="disabled")
        self._run_async(self._analyze_funds, self._on_analyze_done, codes, with_intraday)

    @staticmethod
    def _analyze_funds(codes, with_estimate):
        data_fetcher.fetch_fund_name("000001")  # 预热名称缓存，避免并发冷启动
        total_capital = portfolio.get_total_capital()
        result_map = {}
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
            futs = {
                ex.submit(_analyze_one_fund, code, total_capital, with_estimate): code
                for code in codes
            }
            for fut in as_completed(futs):
                r = fut.result()
                result_map[r["code"]] = r
        # 按原始顺序返回
        return [result_map[c] for c in codes if c in result_map]

    def _on_analyze_done(self, results) -> None:
        self.analyze_btn.config(state="normal")
        for r in results:
            if r.get("error"):
                self.tree.insert("", tk.END, values=(
                    r["code"], "分析失败", "-", "-", "-", "-", "-", "-", r["error"][:30]))
                continue
            report = r["report"]
            adv = r["adv"]
            est = r["est"]
            last = r["last"]

            est_str = "-"
            if est and est.get("estimate_pct") is not None:
                est_str = f"{est['estimate_pct']:+.2f}"

            amount_str = "-"
            if adv.suggest_amount > 0:
                amount_str = f"{adv.suggest_action} {adv.suggest_amount:,.0f}"
            elif adv.suggest_action == "维持":
                amount_str = "维持"

            last_str = "-"
            if last:
                last_str = f"{last['date']} {last['action']}{last['amount']:.0f}"

            self.tree.insert(
                "", tk.END,
                values=(
                    report.fund_code, report.fund_name, f"{report.nav:.4f}",
                    est_str, f"{report.composite_score:+.2f}", report.action,
                    adv.suggest_action, amount_str, last_str,
                ),
                tags=(report.action,),
            )
        self._set_status(f"分析完成，共 {len(results)} 只。")

    def _on_row_detail(self, _event) -> None:
        item = self.tree.focus()
        if not item:
            return
        vals = self.tree.item(item, "values")
        if not vals or vals[1] == "分析失败":
            return
        self.open_detail(vals[0])

    def open_detail(self, code: str) -> None:
        """打开（或复用）某只基金的详情窗口。"""
        code = str(code).strip().zfill(6)
        existing = self._detail_windows.get(code)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        win = FundDetailWindow(self, code)
        self._detail_windows[code] = win

    def on_trades_changed(self) -> None:
        """交易数据变更后，刷新交易页与资金页（供详情窗口回调）。"""
        self._refresh_trades_table()
        self._refresh_capital_view()

    # ------------------------------------------------------------------ #
    # Tab2 事件
    # ------------------------------------------------------------------ #
    def _on_estimate_holdings(self) -> None:
        code = self.hold_code_var.get().strip()
        if not code:
            messagebox.showinfo("提示", "请输入基金代码。")
            return
        topn = int(self.hold_topn_var.get())
        for item in self.hold_tree.get_children():
            self.hold_tree.delete(item)
        self.hold_summary.set("估算中…")
        self.hold_btn.config(state="disabled")
        self._run_async(self._estimate_holdings, self._on_holdings_done, code, topn)

    @staticmethod
    def _estimate_holdings(code, topn):
        code = code.zfill(6)
        name = data_fetcher.fetch_fund_name(code)
        est = data_fetcher.estimate_fund_intraday_change(code, top_n=topn)
        return {"code": code, "name": name, "est": est}

    def _on_holdings_done(self, payload) -> None:
        self.hold_btn.config(state="normal")
        est = payload["est"]
        details = est.get("details", [])
        if not details:
            self.hold_summary.set(f"{payload['code']} {payload['name']}：未获取到持仓数据。")
            return
        for d in details:
            change = d["change"]
            if change is None:
                change_str, contrib_str, tag = "无数据", "-", ""
            else:
                change_str = f"{change:+.2f}"
                contrib_str = f"{d['weight'] * change / 100:+.4f}"
                tag = "up" if change >= 0 else "down"
            self.hold_tree.insert("", tk.END, values=(
                d["code"], d["name"], f"{d['weight']:.2f}", change_str, contrib_str), tags=(tag,))

        est_pct = est.get("estimate_pct")
        covered = est.get("covered_weight", 0.0)
        if est_pct is None:
            self.hold_summary.set(
                f"{payload['code']} {payload['name']}：重仓股均无法获取实时行情。")
        else:
            self.hold_summary.set(
                f"{payload['code']} {payload['name']} ▶ 估算当日涨跌 "
                f"{est_pct:+.2f}%（覆盖前 {len(details)} 大重仓股，合计占净值 {covered:.1f}%）")

    # ------------------------------------------------------------------ #
    # Tab3 事件
    # ------------------------------------------------------------------ #
    def _refresh_trades_table(self) -> None:
        for item in self.trade_tree.get_children():
            self.trade_tree.delete(item)
        for t in reversed(trade_log.list_trades()):
            self.trade_tree.insert("", tk.END, iid=t["id"], values=(
                t["date"], t["fund_code"], t["action"], f"{t['amount']:.2f}",
                f"{t['nav']}", f"{t['shares']:.4f}", t.get("note", "")),
                tags=(t["action"],))

    def _on_fill_nav(self) -> None:
        code = self.t_code.get().strip()
        if not code:
            messagebox.showinfo("提示", "请先输入基金代码。")
            return
        self._run_async(self._latest_nav, self._set_nav_field, code)

    @staticmethod
    def _latest_nav(code):
        df = data_fetcher.fetch_fund_nav(code.zfill(6))
        return float(df.iloc[-1]["nav"])

    def _set_nav_field(self, nav) -> None:
        self.t_nav.set(f"{nav:.4f}")

    def _on_add_trade(self) -> None:
        try:
            code = self.t_code.get().strip()
            amount = float(self.t_amount.get())
            nav = float(self.t_nav.get())
        except ValueError:
            messagebox.showerror("输入有误", "金额和净值必须是数字。")
            return
        if not code:
            messagebox.showerror("输入有误", "请填写基金代码。")
            return
        trade_log.add_trade(code, self.t_action.get(), amount, nav, self.t_note.get())
        self.t_amount.set("")
        self.t_note.set("")
        self._refresh_trades_table()
        self._set_status("已保存交易记录。")

    def _on_delete_trade(self) -> None:
        item = self.trade_tree.focus()
        if not item:
            return
        if messagebox.askyesno("确认", "确定删除选中的交易记录吗？"):
            trade_log.delete_trade(item)
            self._refresh_trades_table()

    # ------------------------------------------------------------------ #
    # Tab4 事件
    # ------------------------------------------------------------------ #
    def _refresh_capital_view(self) -> None:
        cap = portfolio.get_total_capital()
        if cap > 0:
            self.capital_info.set(f"当前总仓位金额：{cap:,.2f} 元")
        else:
            self.capital_info.set("尚未设置总仓位金额，仓位建议将只给方向、不给金额。")

    def _on_save_capital(self) -> None:
        try:
            amount = float(self.capital_var.get())
        except ValueError:
            messagebox.showerror("输入有误", "请输入数字金额。")
            return
        portfolio.set_total_capital(amount)
        self._refresh_capital_view()
        self._set_status("已保存总仓位金额。")

    def _on_refresh_overview(self) -> None:
        codes = list(trade_log.holding_summary().keys())
        if not codes:
            self.overview_info.set("暂无持仓（交易记录为空）。")
            return
        self._run_async(self._compute_overview, self._show_overview, codes)

    @staticmethod
    def _compute_overview(codes):
        navs = {}
        for c in codes:
            try:
                df = data_fetcher.fetch_fund_nav(c)
                navs[c] = float(df.iloc[-1]["nav"])
            except Exception:
                navs[c] = 0.0
        return portfolio.portfolio_overview(navs)

    def _show_overview(self, ov) -> None:
        self.overview_info.set(
            f"总资金：{ov['total_capital']:,.2f} 元\n"
            f"已投入(持仓市值)：{ov['invested_value']:,.2f} 元  "
            f"（仓位 {ov['invested_ratio']:.1%}）\n"
            f"可用现金：{ov['cash']:,.2f} 元"
        )


class FundDetailWindow(tk.Toplevel):
    """单只基金详情窗口：信号分析 + 仓位建议 + 交易历史 + 买/卖操作。"""

    def __init__(self, app: "FundApp", code: str) -> None:
        super().__init__(app)
        self.app = app
        self.code = code
        self._latest_nav = None
        self._fund_name = code

        self.title(f"基金详情 - {code}")
        self.geometry("680x640")
        self.minsize(600, 520)

        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        head = ttk.Frame(self)
        head.pack(fill="x", padx=10, pady=8)
        self.title_var = tk.StringVar(value=f"{self.code} 加载中…")
        ttk.Label(head, textvariable=self.title_var,
                  font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        self.action_var = tk.StringVar(value="")
        self.action_lbl = ttk.Label(head, textvariable=self.action_var,
                                     font=("Microsoft YaHei UI", 13, "bold"))
        self.action_lbl.pack(side="right")

        # 操作按钮区
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=4)
        ttk.Button(btns, text="买入", command=lambda: self._open_trade_dialog(trade_log.BUY)).pack(
            side="left", padx=4)
        ttk.Button(btns, text="卖出", command=lambda: self._open_trade_dialog(trade_log.SELL)).pack(
            side="left", padx=4)
        ttk.Button(btns, text="重新分析", command=self.reload).pack(side="left", padx=4)
        ttk.Button(btns, text="加入自选", command=self._add_to_watch).pack(side="left", padx=4)
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right", padx=4)

        # 分析文本
        self.text = tk.Text(self, wrap="word", height=18, font=("Consolas", 10))
        self.text.pack(fill="both", expand=True, padx=10, pady=6)
        self.text.insert("1.0", "正在拉取数据与计算指标…")
        self.text.config(state="disabled")

        # 该基金交易历史
        ttk.Label(self, text="该基金交易记录", style="Title.TLabel").pack(anchor="w", padx=10)
        cols = ("date", "action", "amount", "nav", "shares", "note")
        headers = {"date": "日期", "action": "操作", "amount": "金额", "nav": "净值",
                   "shares": "份额", "note": "备注"}
        self.trade_tree = ttk.Treeview(self, columns=cols, show="headings", height=6)
        for c in cols:
            self.trade_tree.heading(c, text=headers[c])
            self.trade_tree.column(c, width=100, anchor="center")
        self.trade_tree.column("note", anchor="w", width=160)
        self.trade_tree.pack(fill="x", padx=10, pady=(2, 10))
        self.trade_tree.tag_configure(trade_log.BUY, foreground="#c0392b")
        self.trade_tree.tag_configure(trade_log.SELL, foreground="#16a085")

    def reload(self) -> None:
        self.app._run_async(self._load, self._populate, self.code)

    @staticmethod
    def _load(code):
        nav_df = data_fetcher.fetch_fund_nav(code)
        ind = compute_indicators(nav_df)
        name = data_fetcher.fetch_fund_name(code)
        report = evaluate_signals(ind, code, name)
        adv = portfolio.advise(report)
        return {
            "name": name,
            "latest_nav": float(nav_df.iloc[-1]["nav"]),
            "report": report,
            "adv": adv,
        }

    def _populate(self, data) -> None:
        if not self.winfo_exists():
            return
        report = data["report"]
        adv = data["adv"]
        self._latest_nav = data["latest_nav"]
        self._fund_name = data["name"]

        self.title_var.set(f"{self.code}  {self._fund_name}")
        self.action_var.set(f"【{report.action}】 {report.composite_score:+.2f}")
        self.action_lbl.config(foreground=_ACTION_COLORS.get(report.action, "#000000"))

        text = report.to_text()
        text += "\n仓位建议:\n"
        text += f"  当前持仓市值: {adv.current_value:,.2f} 元 ({adv.current_ratio:.1%})\n"
        text += f"  操作: 【{adv.suggest_action}】 {adv.reason}\n"
        self.text.config(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", text)
        self.text.config(state="disabled")

        self._refresh_trade_tree()

    def _refresh_trade_tree(self) -> None:
        for item in self.trade_tree.get_children():
            self.trade_tree.delete(item)
        for t in reversed(trade_log.list_trades(self.code)):
            self.trade_tree.insert("", tk.END, values=(
                t["date"], t["action"], f"{t['amount']:.2f}", f"{t['nav']}",
                f"{t['shares']:.4f}", t.get("note", "")), tags=(t["action"],))

    def _add_to_watch(self) -> None:
        watchlist.add_fund(self.code)
        self.app._refresh_watchlist_box()
        self.app._set_status(f"已将 {self.code} 加入自选。")

    def _open_trade_dialog(self, action: str) -> None:
        dlg = tk.Toplevel(self)
        dlg.title(f"{action} - {self.code}")
        dlg.geometry("320x230")
        dlg.transient(self)
        dlg.grab_set()

        amount_var = tk.StringVar()
        nav_var = tk.StringVar(value=f"{self._latest_nav:.4f}" if self._latest_nav else "")
        note_var = tk.StringVar()

        frm = ttk.Frame(dlg)
        frm.pack(fill="both", expand=True, padx=12, pady=10)
        ttk.Label(frm, text=f"基金: {self.code} {self._fund_name}").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(frm, text=f"操作: {action}").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(frm, text="金额(元)").grid(row=2, column=0, sticky="e", pady=4)
        amount_ent = ttk.Entry(frm, textvariable=amount_var, width=16)
        amount_ent.grid(row=2, column=1, pady=4)
        ttk.Label(frm, text="成交净值").grid(row=3, column=0, sticky="e", pady=4)
        ttk.Entry(frm, textvariable=nav_var, width=16).grid(row=3, column=1, pady=4)
        ttk.Label(frm, text="备注").grid(row=4, column=0, sticky="e", pady=4)
        ttk.Entry(frm, textvariable=note_var, width=16).grid(row=4, column=1, pady=4)
        amount_ent.focus_set()

        def confirm():
            try:
                amount = float(amount_var.get())
                nav = float(nav_var.get())
            except ValueError:
                messagebox.showerror("输入有误", "金额与净值必须是数字。", parent=dlg)
                return
            if amount <= 0 or nav <= 0:
                messagebox.showerror("输入有误", "金额与净值必须大于 0。", parent=dlg)
                return
            trade_log.add_trade(self.code, action, amount, nav, note_var.get())
            dlg.destroy()
            self._refresh_trade_tree()
            self.reload()
            self.app.on_trades_changed()
            self.app._set_status(f"已记录：{self.code} {action} {amount:.0f} 元。")

        bar = ttk.Frame(dlg)
        bar.pack(fill="x", padx=12, pady=6)
        ttk.Button(bar, text="确认", command=confirm).pack(side="right", padx=4)
        ttk.Button(bar, text="取消", command=dlg.destroy).pack(side="right", padx=4)


class IndexDetailWindow(tk.Toplevel):
    """指数详情窗口：扩展实时行情 + 近月日线走势。"""

    def __init__(self, app: "FundApp", code: str, name: str) -> None:
        super().__init__(app)
        self.app = app
        self.code = code
        self.title(f"指数详情 - {name}({code})")
        self.geometry("640x560")

        head = ttk.Frame(self)
        head.pack(fill="x", padx=10, pady=8)
        self.title_var = tk.StringVar(value=f"{name}  加载中…")
        ttk.Label(head, textvariable=self.title_var,
                  font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        ttk.Button(head, text="刷新", command=self.reload).pack(side="right")

        self.info = tk.Text(self, height=7, wrap="word", font=("Consolas", 10))
        self.info.pack(fill="x", padx=10, pady=4)
        self.info.config(state="disabled")

        ttk.Label(self, text="近月日线", style="Title.TLabel").pack(anchor="w", padx=10)
        cols = ("date", "close", "pct", "high", "low")
        headers = {"date": "日期", "close": "收盘", "pct": "涨跌%", "high": "最高", "low": "最低"}
        self.hist_tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        for c in cols:
            self.hist_tree.heading(c, text=headers[c])
            self.hist_tree.column(c, width=110, anchor="center")
        self.hist_tree.pack(fill="both", expand=True, padx=10, pady=6)
        self.hist_tree.tag_configure("up", foreground=_UP_COLOR)
        self.hist_tree.tag_configure("down", foreground=_DOWN_COLOR)

        self.reload()

    def reload(self) -> None:
        self.app._run_async(self._load, self._populate, self.code)

    @staticmethod
    def _load(code):
        detail = market.fetch_index_detail(code)
        try:
            hist = market.fetch_index_history(code, days=30)
        except Exception:
            hist = None
        return {"detail": detail, "hist": hist}

    def _populate(self, data) -> None:
        if not self.winfo_exists():
            return
        d = data["detail"]
        self.title_var.set(
            f"{d['name']}  {d['price']:,.2f}  ({d['change_pct']:+.2f}%)")
        text = (
            f"最新: {d['price']:,.2f}    涨跌: {d['change']:+.2f}  ({d['change_pct']:+.2f}%)\n"
            f"今开: {d['open']:,.2f}    昨收: {d['prev_close']:,.2f}\n"
            f"最高: {d['high']:,.2f}    最低: {d['low']:,.2f}\n"
            f"成交额: {(d['amount'] or 0) / 1e8:,.2f} 亿元\n"
        )
        self.info.config(state="normal")
        self.info.delete("1.0", tk.END)
        self.info.insert("1.0", text)
        self.info.config(state="disabled")

        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)
        hist = data["hist"]
        if hist is not None and not hist.empty:
            for _, r in hist.iloc[::-1].iterrows():
                pct = r.get("pct")
                tag = "" if pct is None or pd_isna(pct) else ("up" if pct >= 0 else "down")
                pct_str = "-" if pct is None or pd_isna(pct) else f"{pct:+.2f}"
                self.hist_tree.insert("", tk.END, values=(
                    str(r["date"])[:10], f"{r['close']:,.2f}", pct_str,
                    f"{r['high']:,.2f}", f"{r['low']:,.2f}"), tags=(tag,))


def pd_isna(v) -> bool:
    try:
        import math
        return v is None or (isinstance(v, float) and math.isnan(v))
    except Exception:
        return False


def main() -> None:
    app = FundApp()
    app.mainloop()


if __name__ == "__main__":
    main()
