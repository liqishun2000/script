# -*- coding: utf-8 -*-
"""
积存金实时价格监控（网格交易提醒，含手续费核算）

数据源：京东金融积存金实时价（主），新浪 Au(T+D) 行情（备用）
通知：企业微信群机器人 webhook（推荐）/ Server酱（微信公众号推送，可选）

交易逻辑（考虑手续费）：
  - 买入：价格每比参考价（上次买入价，空仓时为锚点价）下跌 GRID_STEP_PCT，
    提示买入一份，并记录为一笔持仓（记入 state.json）。
  - 卖出：对每笔持仓单独核算，只有当前价扣除卖出手续费后 >= 买入成本(含买入手续费)
    再加 MIN_PROFIT_RATE 净利润时，才提示卖出该笔。绝不推送亏手续费的卖出。
  - 空仓时锚点价跟随价格上移（只涨不跌），保证高位回落也能触发买入。
  - 推送后默认你已按提示操作；如实际没操作，改 state.json 里的 lots 即可。

用法：
    python gold_monitor.py              # 前台运行监控，Ctrl+C 退出
    python gold_monitor.py --test       # 发一条测试通知后退出
    python gold_monitor.py status       # 查看当前持仓与触发价
    python gold_monitor.py bought 899.5 # 记录实际买入 1 份 @899.5（可加份数：bought 899.5 2）
    python gold_monitor.py sold 899.5   # 移除该笔持仓（已卖出或当初没买）
    python gold_monitor.py sold all     # 移除全部持仓
    python gold_monitor.py clear        # 清空持仓并重置锚点

持仓同步命令在监控运行时可直接用（另开一个终端执行即可），
监控进程会自动检测 state.json 的修改并热重载，操作确认会推送到群里。
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ============================ 配置区 ============================

# 手续费率（按你银行/平台的实际费率改，工行积存金卖出约 0.5%）
BUY_FEE_RATE = 0.000    # 买入手续费率；若你的平台买入免手续费，改为 0.0
SELL_FEE_RATE = 0.005   # 卖出/赎回手续费率

# 每格要求的最少净利润率（扣完双边手续费之后）
MIN_PROFIT_RATE = 0.01  # 1%

# 买入网格步长（百分比）。价格每下跌一格提示加买一份。
# 注意：必须明显大于 0，通常应 >= 双边手续费 + 净利润要求，否则格子太密不划算
GRID_STEP_PCT = 0.012    # 1.2%

# 每份克数（仅用于消息里估算盈亏金额，不影响信号）
LOT_GRAMS = 2

# 最大持仓份数：跌破上限后不再提示加仓，防止单边下跌无限补仓
MAX_LOTS = 10

# 轮询间隔（秒）
POLL_INTERVAL = 30

# 企业微信群机器人 webhook（推荐）。
# 获取方式：企业微信建一个群 -> 群设置 -> 群机器人 -> 添加 -> 复制 webhook 地址
WECOM_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=dfd6e537-8680-4f15-9262-dcf9485fba30"

# Server酱 SendKey（可选，推送到微信）。https://sct.ftqq.com 扫码获取
SERVERCHAN_SENDKEY = ""

# ===============================================================

STATE_FILE = Path(__file__).with_name("state.json")
JD_URL = "https://ms.jr.jd.com/gw/generic/hj/h5/m/latestPrice"
SINA_URL = "https://hq.sinajs.cn/list=gds_AUTD"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})


LOG_FILE = Path(__file__).with_name("gold_monitor.log")


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5 * 1024 * 1024:
            LOG_FILE.unlink()  # 超过 5MB 直接重开，避免无限膨胀
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def fetch_price_jd():
    """京东金融积存金实时价，返回 (价格, 昨收) 元/克"""
    resp = session.get(JD_URL, headers={"Referer": "https://m.jr.jd.com/"}, timeout=10)
    datas = resp.json()["resultData"]["datas"]
    return float(datas["price"]), float(datas["yesterdayPrice"])


def fetch_price_sina():
    """新浪 Au(T+D) 行情备用源，返回 (最新价, 昨收) 元/克"""
    resp = session.get(SINA_URL, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
    m = re.search(r'"([^"]+)"', resp.text)
    fields = m.group(1).split(",")
    return float(fields[0]), float(fields[7])


def fetch_price():
    try:
        return fetch_price_jd()
    except Exception as e:
        log(f"京东接口失败({e})，切换新浪备用源")
        return fetch_price_sina()


def notify_wecom(title, content):
    body = {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{content}"}}
    resp = session.post(WECOM_WEBHOOK, json=body, timeout=10)
    result = resp.json()
    if result.get("errcode") != 0:
        raise RuntimeError(f"企业微信返回错误: {result}")


def notify_serverchan(title, content):
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    resp = session.post(url, data={"title": title, "desp": content}, timeout=10)
    result = resp.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Server酱返回错误: {result}")


def notify(title, content):
    sent = False
    for name, key, func in [
        ("企业微信", WECOM_WEBHOOK, notify_wecom),
        ("Server酱", SERVERCHAN_SENDKEY, notify_serverchan),
    ]:
        if not key:
            continue
        try:
            func(title, content)
            sent = True
            log(f"{name}通知已发送: {title}")
        except Exception as e:
            log(f"{name}通知发送失败: {e}")
    if not sent:
        log(f"(未配置通知渠道) {title} | {content}")


# ---------------------- 手续费核算 ----------------------

def buy_cost(buy_price):
    """每克实际成本 = 买入价 * (1 + 买入费率)"""
    return buy_price * (1 + BUY_FEE_RATE)


def breakeven_price(lot_price):
    """回本价：卖出扣费后刚好等于买入成本的价格"""
    return buy_cost(lot_price) / (1 - SELL_FEE_RATE)


def sell_target(lot_price):
    """目标卖出价：回本之外再赚 MIN_PROFIT_RATE 净利润"""
    return buy_cost(lot_price) * (1 + MIN_PROFIT_RATE) / (1 - SELL_FEE_RATE)


def net_profit_per_gram(lot_price, sell_price):
    """每克净利润 = 卖出净得 - 买入成本"""
    return sell_price * (1 - SELL_FEE_RATE) - buy_cost(lot_price)


# ---------------------- 网格决策 ----------------------

def process_tick(price, state):
    """根据当前价更新持仓状态，返回要推送的 (标题, 内容) 列表"""
    msgs = []
    lots = state.setdefault("lots", [])

    # 空仓时锚点跟随价格上移，高位回落一格即可触发首次买入
    if not lots:
        if state.get("anchor") is None or price > state["anchor"]:
            state["anchor"] = price

    # ---- 卖出信号：逐笔核算，扣费后有净利润才提示 ----
    sellable = [lot for lot in lots if price >= sell_target(lot["price"])]
    if sellable:
        lines = []
        total_profit = 0.0
        for lot in sellable:
            p = net_profit_per_gram(lot["price"], price)
            total_profit += p * LOT_GRAMS
            lines.append(
                f"> 买入价 {lot['price']:.2f} → 现价卖出净赚 {p:.2f} 元/克"
                f"（{LOT_GRAMS} 克约 {p * LOT_GRAMS:.1f} 元）"
            )
        state["lots"] = [lot for lot in lots if lot not in sellable]
        lots = state["lots"]
        if not lots:
            state["anchor"] = price  # 清仓后以当前价为新锚点
        msgs.append((
            f"卖出提醒：{len(sellable)} 份可获利了结（现价 {price:.2f}）",
            "\n".join(lines)
            + f"\n> 合计净利润约 {total_profit:.1f} 元（已扣双边手续费）"
            + f"\n> 剩余持仓 {len(lots)} 份",
        ))

    # ---- 买入信号：较参考价跌满一格 ----
    ref = lots[-1]["price"] if lots else state["anchor"]
    if price <= ref * (1 - GRID_STEP_PCT):
        steps = int((ref - price) / (ref * GRID_STEP_PCT))
        room = MAX_LOTS - len(lots)
        n = min(steps, room)
        if n > 0:
            for _ in range(n):
                lots.append({"price": price, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
            state.pop("full_warned", None)
            msgs.append((
                f"买入提醒：下跌 {(ref - price) / ref * 100:.2f}%，建议买入 {n} 份（现价 {price:.2f}）",
                f"> 参考价 {ref:.2f} → 现价 {price:.2f}\n"
                f"> 本笔回本价：{breakeven_price(price):.2f} 元/克（含双边手续费）\n"
                f"> 目标卖出价：{sell_target(price):.2f} 元/克（净赚 ≥{MIN_PROFIT_RATE:.1%}）\n"
                f"> 当前持仓 {len(lots)}/{MAX_LOTS} 份",
            ))
        elif not state.get("full_warned"):
            state["full_warned"] = True
            msgs.append((
                f"持仓已满 {MAX_LOTS} 份，暂停加仓（现价 {price:.2f}）",
                f"> 价格仍在下跌但已达最大持仓，不再提示买入\n"
                f"> 如要继续补仓请调大脚本里的 MAX_LOTS",
            ))

    return msgs


def position_summary(state, price):
    lots = state.get("lots", [])
    if not lots:
        return f"> 当前空仓，锚点价 {state.get('anchor', price):.2f}"
    nearest = min(sell_target(lot["price"]) for lot in lots)
    ref = lots[-1]["price"]
    return (
        f"> 当前持仓 {len(lots)} 份，成本 {min(l['price'] for l in lots):.2f}"
        f" ~ {max(l['price'] for l in lots):.2f} 元/克\n"
        f"> 最近卖出触发价：{nearest:.2f}，下一买入触发价：{ref * (1 - GRID_STEP_PCT):.2f}"
    )


def load_state():
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if "lots" in state:  # 仅接受新版格式，旧版 baseline 状态直接重建
            return state
    return {"anchor": None, "lots": []}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def state_mtime():
    return STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0


# ---------------------- 持仓同步命令 ----------------------
# 监控进程每轮会检测 state.json 的外部修改并热重载，
# 因此这些命令可以在监控运行时直接使用，无需重启。

def cmd_status():
    state = load_state()
    try:
        price, yesterday = fetch_price()
        head = f"> 当前价：{price:.2f} 元/克（日内 {price - yesterday:+.2f}）\n"
    except Exception as e:
        price, head = None, f"> 取价失败：{e}\n"
    text = head + position_summary(state, price or 0)
    print(text.replace("> ", ""))


def cmd_bought(price, n):
    state = load_state()
    for _ in range(n):
        state["lots"].append(
            {"price": price, "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "manual": True}
        )
    save_state(state)
    notify(
        f"已记录买入：{n} 份 @ {price:.2f}",
        f"> 回本价 {breakeven_price(price):.2f}，目标卖出价 {sell_target(price):.2f}\n"
        f"> 当前持仓 {len(state['lots'])}/{MAX_LOTS} 份",
    )


def cmd_sold(target):
    state = load_state()
    lots = state["lots"]
    if not lots:
        print("当前没有持仓记录")
        return
    if target == "all":
        removed, state["lots"] = lots, []
    else:
        price = float(target)
        # 删除买入价最接近的一笔（容差 1%，防止误删）
        lot = min(lots, key=lambda l: abs(l["price"] - price))
        if abs(lot["price"] - price) > price * 0.01:
            print(f"未找到买入价接近 {price:.2f} 的持仓，现有：" +
                  ", ".join(f"{l['price']:.2f}" for l in lots))
            return
        removed = [lot]
        lots.remove(lot)
    save_state(state)
    notify(
        f"已移除持仓 {len(removed)} 份",
        "> 买入价：" + ", ".join(f"{l['price']:.2f}" for l in removed)
        + f"\n> 剩余持仓 {len(state['lots'])} 份",
    )


def cmd_clear():
    state = {"anchor": None, "lots": []}
    save_state(state)
    notify("持仓已清空", "> 锚点将在下一轮以现价重建")


def main():
    parser = argparse.ArgumentParser(
        description="积存金网格监控（含手续费核算）",
        epilog="示例：bought 899.5 2 记录买入2份；sold 899.5 移除该笔；sold all 全部移除",
    )
    parser.add_argument("--test", action="store_true", help="发送一条测试通知后退出")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status", help="查看当前持仓与触发价")
    p = sub.add_parser("bought", help="记录实际买入：bought 价格 [份数]")
    p.add_argument("price", type=float)
    p.add_argument("n", type=int, nargs="?", default=1)
    p = sub.add_parser("sold", help="移除持仓（已卖出/当初没买）：sold 买入价 或 sold all")
    p.add_argument("price")
    sub.add_parser("clear", help="清空全部持仓并重置锚点")
    args = parser.parse_args()

    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "bought":
        return cmd_bought(args.price, args.n)
    if args.cmd == "sold":
        return cmd_sold(args.price)
    if args.cmd == "clear":
        return cmd_clear()

    if args.test:
        price, _ = fetch_price()
        notify("积存金监控测试", f"当前价格 {price:.2f} 元/克，通知链路正常。")
        return

    min_move = sell_target(1.0) - 1.0  # 一份从买到卖至少需要的涨幅（比例）
    log(
        f"启动监控：买入步长 {GRID_STEP_PCT:.1%}，手续费 买{BUY_FEE_RATE:.1%}/卖{SELL_FEE_RATE:.1%}，"
        f"单份获利需上涨 ≥{min_move:.2%}"
    )

    state = load_state()
    try:
        price, yesterday = fetch_price()
    except Exception as e:
        price = yesterday = None
        log(f"启动取价失败: {e}")

    if price is not None:
        if not state["lots"] and (state["anchor"] is None or price > state["anchor"]):
            state["anchor"] = price
        save_state(state)
        notify(
            "积存金监控已启动",
            f"> 当前价：{price:.2f} 元/克（日内 {price - yesterday:+.2f}）\n"
            f"{position_summary(state, price)}\n"
            f"> 买入步长 {GRID_STEP_PCT:.1%}｜手续费 买{BUY_FEE_RATE:.1%} 卖{SELL_FEE_RATE:.1%}｜"
            f"单份获利需涨 ≥{min_move:.2%}",
        )
    else:
        notify("积存金监控已启动", "> 启动取价失败，稍后自动重试")

    known_mtime = state_mtime()

    while True:
        time.sleep(POLL_INTERVAL)

        # state.json 被 bought/sold 等命令改过 -> 热重载持仓
        if state_mtime() != known_mtime:
            state = load_state()
            known_mtime = state_mtime()
            log(f"检测到持仓被外部修改，已重载：{len(state['lots'])} 份")

        try:
            price, yesterday = fetch_price()
        except Exception as e:
            log(f"取价失败: {e}")
            continue

        msgs = process_tick(price, state)
        lots = state["lots"]
        nearest_sell = min((sell_target(l["price"]) for l in lots), default=None)
        ref = lots[-1]["price"] if lots else state["anchor"]
        log(
            f"现价 {price:.2f} | 持仓 {len(lots)} 份 | "
            f"下格买入 {ref * (1 - GRID_STEP_PCT):.2f} | "
            f"最近卖出 {f'{nearest_sell:.2f}' if nearest_sell else '—'}"
        )
        if msgs:
            save_state(state)
            known_mtime = state_mtime()
            for title, content in msgs:
                notify(title, content)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("已停止")
