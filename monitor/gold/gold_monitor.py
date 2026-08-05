# -*- coding: utf-8 -*-
"""积存金实时价格监控（网格交易提醒，含手续费核算）。"""

import argparse
import json
import logging
import math
import msvcrt
import os
import re
import shutil
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, time as clock_time, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
STATE_BACKUP_FILE = BASE_DIR / "state.json.bak"
STATE_LOCK_FILE = BASE_DIR / "state.json.lock"
LOG_FILE = BASE_DIR / "gold_monitor.log"

JD_URL = "https://ms.jr.jd.com/gw/generic/hj/h5/m/latestPrice"
SINA_URL = "https://hq.sinajs.cn/list=gds_AUTD"


# ============================ 配置区 ============================
# 直接修改本区即可。比例使用小数，例如 0.012 表示 1.2%。

# 手续费与交易策略
BUY_FEE_RATE = 0.0       # 买入手续费率
SELL_FEE_RATE = 0.005    # 卖出/赎回手续费率，0.5%
MIN_PROFIT_RATE = 0.01   # 扣除手续费后的最低净利润率，1%
GRID_STEP_PCT = 0.012    # 买入网格间距，1.2%
EMPTY_RISE_ALERT_PCT = 0.012  # 空仓时每累计上涨 1.2% 提醒一次
LOT_GRAMS = 2            # 每份克数，仅用于估算通知中的利润金额
MAX_LOTS = 10            # 最大持仓份数

# 运行与日志
POLL_INTERVAL = 30       # 正常行情轮询间隔，单位：秒
MAX_BACKOFF = 900        # 连续取价失败时的最大重试间隔，单位：秒
HEARTBEAT_TICKS = 10     # 每成功轮询多少次写一条正常心跳日志；10 * 30 秒 = 5 分钟
PRICE_REQUEST_START = clock_time(9, 0)   # 工作日开始请求行情的时间（含）
PRICE_REQUEST_END = clock_time(22, 0)    # 工作日停止请求行情的时间（不含）

# 通知渠道
WECOM_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=dfd6e537-8680-4f15-9262-dcf9485fba30"
SERVERCHAN_SENDKEY = ""  # 可选；不使用 Server酱时留空

# ===============================================================

if BUY_FEE_RATE + SELL_FEE_RATE + MIN_PROFIT_RATE >= 1:
    raise ValueError("手续费率与利润率配置不合理")
if not 0 <= BUY_FEE_RATE <= 0.5:
    raise ValueError("BUY_FEE_RATE 必须在 0 到 0.5 之间")
if not 0 <= SELL_FEE_RATE <= 0.5:
    raise ValueError("SELL_FEE_RATE 必须在 0 到 0.5 之间")
if not 0 <= MIN_PROFIT_RATE <= 10:
    raise ValueError("MIN_PROFIT_RATE 必须在 0 到 10 之间")
if not 0 < GRID_STEP_PCT < 1:
    raise ValueError("GRID_STEP_PCT 必须在 0 到 1 之间")
if not 0 < EMPTY_RISE_ALERT_PCT < 1:
    raise ValueError("EMPTY_RISE_ALERT_PCT 必须在 0 到 1 之间")
if LOT_GRAMS <= 0 or MAX_LOTS <= 0:
    raise ValueError("LOT_GRAMS 和 MAX_LOTS 必须大于 0")
if POLL_INTERVAL < 5 or MAX_BACKOFF < POLL_INTERVAL or HEARTBEAT_TICKS < 1:
    raise ValueError("轮询、退避或心跳参数不合理")
if PRICE_REQUEST_START >= PRICE_REQUEST_END:
    raise ValueError("PRICE_REQUEST_START 必须早于 PRICE_REQUEST_END")


def _build_logger():
    logger = logging.getLogger("gold_monitor")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if sys.stdout is not None:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger


logger = _build_logger()


def log(msg):
    logger.info(msg)


def _build_session():
    result = requests.Session()
    result.headers.update({"User-Agent": "Mozilla/5.0 (GoldMonitor/1.1)"})
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    result.mount("https://", HTTPAdapter(max_retries=retry))
    return result


session = _build_session()


class MarketClosedError(RuntimeError):
    """当前时段不允许请求黄金行情。"""


def is_price_request_allowed(now=None):
    now = now or datetime.now()
    return (
        now.weekday() < 5
        and PRICE_REQUEST_START <= now.time() < PRICE_REQUEST_END
    )


def next_price_request_time(now=None):
    now = now or datetime.now()
    candidate = now.replace(
        hour=PRICE_REQUEST_START.hour,
        minute=PRICE_REQUEST_START.minute,
        second=PRICE_REQUEST_START.second,
        microsecond=0,
    )
    if now.weekday() < 5 and now < candidate:
        return candidate

    candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def market_closed_message(now=None):
    now = now or datetime.now()
    if now.weekday() >= 5:
        reason = "周末休市"
    else:
        reason = (
            f"非取价时段（{PRICE_REQUEST_END:%H:%M} 至次日 "
            f"{PRICE_REQUEST_START:%H:%M}）"
        )
    return f"{reason}，下次取价时间 {next_price_request_time(now):%Y-%m-%d %H:%M}"


def _valid_price(value, source, field):
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} 的 {field} 不是有效数字: {value!r}") from exc
    if not math.isfinite(price) or not 100 <= price <= 5000:
        raise ValueError(f"{source} 的 {field} 超出合理范围: {price!r}")
    return price


def fetch_price_jd():
    """京东金融积存金实时价，返回 (价格, 昨收) 元/克。"""
    resp = session.get(JD_URL, headers={"Referer": "https://m.jr.jd.com/"}, timeout=(5, 10))
    resp.raise_for_status()
    payload = resp.json()
    datas = payload.get("resultData", {}).get("datas")
    if not isinstance(datas, dict):
        raise ValueError("京东响应缺少 resultData.datas")
    return (
        _valid_price(datas.get("price"), "京东", "price"),
        _valid_price(datas.get("yesterdayPrice"), "京东", "yesterdayPrice"),
    )


def fetch_price_sina():
    """新浪 Au(T+D) 行情备用源，返回 (最新价, 昨收) 元/克。"""
    resp = session.get(SINA_URL, headers={"Referer": "https://finance.sina.com.cn"}, timeout=(5, 10))
    resp.raise_for_status()
    resp.encoding = "gbk"
    match = re.search(r'"([^"]+)"', resp.text)
    if not match:
        raise ValueError("新浪响应格式异常：未找到行情字段")
    fields = match.group(1).split(",")
    if len(fields) <= 7:
        raise ValueError(f"新浪响应字段不足: {len(fields)}")
    return (
        _valid_price(fields[0], "新浪", "latest"),
        _valid_price(fields[7], "新浪", "yesterday"),
    )


def fetch_price(now=None):
    now = now or datetime.now()
    if not is_price_request_allowed(now):
        raise MarketClosedError(market_closed_message(now))
    try:
        price, yesterday = fetch_price_jd()
        return price, yesterday, "京东"
    except Exception as exc:
        log(f"京东接口失败({exc})，切换新浪备用源")
        price, yesterday = fetch_price_sina()
        return price, yesterday, "新浪"


def notify_wecom(title, content):
    body = {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{content}"}}
    resp = session.post(WECOM_WEBHOOK, json=body, timeout=(5, 10))
    resp.raise_for_status()
    result = resp.json()
    if result.get("errcode") != 0:
        raise RuntimeError(f"企业微信返回错误: {result}")


def notify_serverchan(title, content):
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    resp = session.post(url, data={"title": title, "desp": content}, timeout=(5, 10))
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Server酱返回错误: {result}")


def notify(title, content):
    configured = False
    sent = False
    for name, key, func in (
        ("企业微信", WECOM_WEBHOOK, notify_wecom),
        ("Server酱", SERVERCHAN_SENDKEY, notify_serverchan),
    ):
        if not key:
            continue
        configured = True
        try:
            func(title, content)
            sent = True
            log(f"{name}通知已发送: {title}")
        except Exception as exc:
            logger.exception("%s通知发送失败: %s", name, exc)
    if not configured:
        log(f"(未配置通知渠道) {title} | {content}")
    return sent


def buy_cost(buy_price):
    return buy_price * (1 + BUY_FEE_RATE)


def breakeven_price(lot_price):
    return buy_cost(lot_price) / (1 - SELL_FEE_RATE)


def sell_target(lot_price):
    return buy_cost(lot_price) * (1 + MIN_PROFIT_RATE) / (1 - SELL_FEE_RATE)


def net_profit_per_gram(lot_price, sell_price):
    return sell_price * (1 - SELL_FEE_RATE) - buy_cost(lot_price)


def process_tick(price, state):
    """根据当前价更新状态，返回需要发送的 (标题, 内容) 列表。"""
    price = _valid_price(price, "行情", "price")
    msgs = []
    lots = state.setdefault("lots", [])

    if not lots:
        anchor = state.get("anchor")
        rise_base = state.get("empty_rise_base")
        if rise_base is None:
            rise_base = anchor if anchor is not None else price
            state["empty_rise_base"] = rise_base
        at_latest_high = anchor is None or price >= anchor
        if anchor is None or price > anchor:
            state["anchor"] = price
        if at_latest_high and price >= rise_base * (1 + EMPTY_RISE_ALERT_PCT):
            rise_pct = (price - rise_base) / rise_base
            state["empty_rise_base"] = price
            msgs.append((
                f"空仓上涨提醒：累计上涨 {rise_pct:.2%}（现价 {price:.2f}）",
                f"> 提醒基准价 {rise_base:.2f} → 现价 {price:.2f}\n"
                f"> 当前空仓，下一上涨提醒价：{price * (1 + EMPTY_RISE_ALERT_PCT):.2f}\n"
                f"> 回落买入触发价：{state['anchor'] * (1 - GRID_STEP_PCT):.2f}",
            ))
    else:
        state.pop("empty_rise_base", None)

    sellable = [lot for lot in lots if price >= sell_target(lot["price"])]
    if sellable:
        lines = []
        total_profit = 0.0
        for lot in sellable:
            profit = net_profit_per_gram(lot["price"], price)
            total_profit += profit * LOT_GRAMS
            lines.append(
                f"> 买入价 {lot['price']:.2f} → 现价卖出净赚 {profit:.2f} 元/克"
                f"（{LOT_GRAMS:g} 克约 {profit * LOT_GRAMS:.1f} 元）"
            )
        state["lots"] = [lot for lot in lots if lot not in sellable]
        lots = state["lots"]
        if not lots:
            state["anchor"] = price
            state["empty_rise_base"] = price
        msgs.append((
            f"卖出提醒：{len(sellable)} 份可获利了结（现价 {price:.2f}）",
            "\n".join(lines)
            + f"\n> 合计净利润约 {total_profit:.1f} 元（已扣双边手续费）"
            + f"\n> 剩余持仓 {len(lots)} 份",
        ))

        # 同一轮不同时发出方向相反的信号；下一轮会基于剩余持仓重新判断。
        return msgs

    ref = lots[-1]["price"] if lots else state["anchor"]
    if price <= ref * (1 - GRID_STEP_PCT):
        steps = int((ref - price) / (ref * GRID_STEP_PCT))
        room = MAX_LOTS - len(lots)
        count = min(steps, room)
        if count > 0:
            for _ in range(count):
                lots.append({"price": price, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
            state.pop("empty_rise_base", None)
            state.pop("full_warned", None)
            msgs.append((
                f"买入提醒：下跌 {(ref - price) / ref * 100:.2f}%，建议买入 {count} 份（现价 {price:.2f}）",
                f"> 参考价 {ref:.2f} → 现价 {price:.2f}\n"
                f"> 本笔回本价：{breakeven_price(price):.2f} 元/克（含双边手续费）\n"
                f"> 目标卖出价：{sell_target(price):.2f} 元/克（净赚 ≥{MIN_PROFIT_RATE:.1%}）\n"
                f"> 当前持仓 {len(lots)}/{MAX_LOTS} 份",
            ))
        elif not state.get("full_warned"):
            state["full_warned"] = True
            msgs.append((
                f"持仓已满 {MAX_LOTS} 份，暂停加仓（现价 {price:.2f}）",
                "> 价格仍在下跌但已达最大持仓，不再提示买入\n"
                "> 如要继续补仓请调大脚本配置区的 MAX_LOTS",
            ))
    return msgs


def position_summary(state, price):
    lots = state.get("lots", [])
    if not lots:
        anchor = state.get("anchor")
        if anchor is None:
            return "> 当前空仓，锚点将在下次成功取价后建立"
        rise_base = state.get("empty_rise_base") or anchor
        return (
            f"> 当前空仓，锚点价 {anchor:.2f}\n"
            f"> 下一上涨提醒价：{rise_base * (1 + EMPTY_RISE_ALERT_PCT):.2f}，"
            f"回落买入触发价：{anchor * (1 - GRID_STEP_PCT):.2f}"
        )
    nearest = min(sell_target(lot["price"]) for lot in lots)
    ref = lots[-1]["price"]
    return (
        f"> 当前持仓 {len(lots)} 份，成本 {min(l['price'] for l in lots):.2f}"
        f" ~ {max(l['price'] for l in lots):.2f} 元/克\n"
        f"> 最近卖出触发价：{nearest:.2f}，下一买入触发价：{ref * (1 - GRID_STEP_PCT):.2f}"
    )


def _validate_state(state):
    if not isinstance(state, dict):
        raise ValueError("状态根节点必须是对象")
    anchor = state.get("anchor")
    if anchor is not None:
        state["anchor"] = _valid_price(anchor, "状态", "anchor")
    empty_rise_base = state.get("empty_rise_base")
    if empty_rise_base is not None:
        state["empty_rise_base"] = _valid_price(
            empty_rise_base, "状态", "empty_rise_base"
        )
    lots = state.get("lots")
    if not isinstance(lots, list):
        raise ValueError("状态 lots 必须是数组")
    for index, lot in enumerate(lots):
        if not isinstance(lot, dict):
            raise ValueError(f"状态 lots[{index}] 必须是对象")
        lot["price"] = _valid_price(lot.get("price"), "状态", f"lots[{index}].price")
    if len(lots) > MAX_LOTS:
        log(f"警告：状态持仓 {len(lots)} 份，超过配置上限 {MAX_LOTS} 份")
    return state


def _read_state_file(path):
    return _validate_state(json.loads(path.read_text(encoding="utf-8")))


def _load_state_unlocked():
    if not STATE_FILE.exists():
        return {"anchor": None, "lots": []}
    try:
        return _read_state_file(STATE_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("主状态文件读取失败: %s", exc)
        if STATE_BACKUP_FILE.exists():
            try:
                state = _read_state_file(STATE_BACKUP_FILE)
                logger.warning("已从状态备份 %s 恢复", STATE_BACKUP_FILE.name)
                return state
            except (OSError, ValueError, json.JSONDecodeError) as backup_exc:
                logger.error("状态备份读取失败: %s", backup_exc)
        raise RuntimeError("state.json 及其备份均不可用，拒绝以空持仓继续运行") from exc


def _save_state_unlocked(state):
    state = _validate_state(state)
    temp_file = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.tmp")
    try:
        if STATE_FILE.exists():
            try:
                _read_state_file(STATE_FILE)
                shutil.copy2(STATE_FILE, STATE_BACKUP_FILE)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        with temp_file.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_file, STATE_FILE)
    finally:
        try:
            temp_file.unlink(missing_ok=True)
        except OSError:
            pass


@contextmanager
def state_lock(timeout=10):
    """使用单独锁文件串行化后台进程和命令行的状态读改写。"""
    deadline = time.monotonic() + timeout
    with STATE_LOCK_FILE.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("等待 state.json 文件锁超时")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def load_state():
    with state_lock():
        return _load_state_unlocked()


def save_state(state):
    with state_lock():
        _save_state_unlocked(state)


def cmd_status():
    state = load_state()
    try:
        price, yesterday, source = fetch_price()
        head = f"> 当前价：{price:.2f} 元/克（日内 {price - yesterday:+.2f}，来源：{source}）\n"
    except MarketClosedError as exc:
        price, head = None, f"> 行情请求已暂停：{exc}\n"
    except Exception as exc:
        price, head = None, f"> 取价失败：{exc}\n"
    print((head + position_summary(state, price or 0)).replace("> ", ""))


def cmd_bought(price, count):
    price = _valid_price(price, "命令", "price")
    if count <= 0:
        raise ValueError("买入份数必须大于 0")
    with state_lock():
        state = _load_state_unlocked()
        if len(state["lots"]) + count > MAX_LOTS:
            raise ValueError(f"记录后将超过最大持仓 {MAX_LOTS} 份")
        for _ in range(count):
            state["lots"].append({
                "price": price,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "manual": True,
            })
        state.pop("empty_rise_base", None)
        _save_state_unlocked(state)
    notify(
        f"已记录买入：{count} 份 @ {price:.2f}",
        f"> 回本价 {breakeven_price(price):.2f}，目标卖出价 {sell_target(price):.2f}\n"
        f"> 当前持仓 {len(state['lots'])}/{MAX_LOTS} 份",
    )


def cmd_sold(target):
    with state_lock():
        state = _load_state_unlocked()
        lots = state["lots"]
        if not lots:
            print("当前没有持仓记录")
            return
        if target == "all":
            removed, state["lots"] = list(lots), []
        else:
            price = _valid_price(target, "命令", "price")
            lot = min(lots, key=lambda item: abs(item["price"] - price))
            if abs(lot["price"] - price) > price * 0.01:
                print(
                    f"未找到买入价接近 {price:.2f} 的持仓，现有："
                    + ", ".join(f"{item['price']:.2f}" for item in lots)
                )
                return
            removed = [lot]
            lots.remove(lot)
        if not state["lots"]:
            state["anchor"] = None
            state.pop("empty_rise_base", None)
        _save_state_unlocked(state)
    notify(
        f"已移除持仓 {len(removed)} 份",
        "> 买入价：" + ", ".join(f"{item['price']:.2f}" for item in removed)
        + f"\n> 剩余持仓 {len(state['lots'])} 份",
    )


def cmd_clear():
    with state_lock():
        _save_state_unlocked({"anchor": None, "lots": []})
    notify("持仓已清空", "> 锚点将在下一轮以现价重建")


def _positive_count(value):
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("份数必须是整数") from exc
    if count <= 0:
        raise argparse.ArgumentTypeError("份数必须大于 0")
    return count


def main():
    parser = argparse.ArgumentParser(description="积存金网格监控（含手续费核算）")
    parser.add_argument("--test", action="store_true", help="发送一条测试通知后退出")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status", help="查看当前持仓与触发价")
    bought_parser = sub.add_parser("bought", help="记录实际买入：bought 价格 [份数]")
    bought_parser.add_argument("price", type=float)
    bought_parser.add_argument("n", type=_positive_count, nargs="?", default=1)
    sold_parser = sub.add_parser("sold", help="移除持仓：sold 买入价 或 sold all")
    sold_parser.add_argument("price")
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
        if not (WECOM_WEBHOOK or SERVERCHAN_SENDKEY):
            raise RuntimeError("未配置通知渠道，无法执行通知测试")
        try:
            price, _, source = fetch_price()
            content = f"当前价格 {price:.2f} 元/克，来源：{source}，通知链路正常。"
        except MarketClosedError as exc:
            content = f"{exc}；未请求行情接口，通知链路正常。"
        notify("积存金监控测试", content)
        return

    min_move = sell_target(1.0) - 1.0
    log(
        f"启动监控：买入步长 {GRID_STEP_PCT:.1%}，空仓上涨提醒 {EMPTY_RISE_ALERT_PCT:.1%}，"
        f"手续费 买{BUY_FEE_RATE:.1%}/卖{SELL_FEE_RATE:.1%}，单份获利需上涨 ≥{min_move:.2%}，"
        f"取价时段 工作日 {PRICE_REQUEST_START:%H:%M}-{PRICE_REQUEST_END:%H:%M}"
    )
    if not (WECOM_WEBHOOK or SERVERCHAN_SENDKEY):
        log("警告：未在脚本配置区设置 WECOM_WEBHOOK 或 SERVERCHAN_SENDKEY")

    closed_reason = None
    try:
        price, yesterday, source = fetch_price()
    except MarketClosedError as exc:
        price = yesterday = source = None
        closed_reason = str(exc)
        log(f"行情请求已暂停：{closed_reason}")
    except Exception as exc:
        price = yesterday = source = None
        log(f"启动取价失败: {exc}")

    with state_lock():
        state = _load_state_unlocked()
        if price is not None and not state["lots"]:
            before = json.dumps(state, ensure_ascii=False, sort_keys=True)
            anchor = state.get("anchor")
            if state.get("empty_rise_base") is None:
                state["empty_rise_base"] = anchor if anchor is not None else price
            if anchor is None or price > anchor:
                state["anchor"] = price
            after = json.dumps(state, ensure_ascii=False, sort_keys=True)
            if after != before:
                _save_state_unlocked(state)

    if price is not None:
        notify(
            "积存金监控已启动",
            f"> 当前价：{price:.2f} 元/克（日内 {price - yesterday:+.2f}，来源：{source}）\n"
            f"{position_summary(state, price)}\n"
            f"> 买入步长 {GRID_STEP_PCT:.1%}｜空仓上涨提醒 {EMPTY_RISE_ALERT_PCT:.1%}｜"
            f"手续费 买{BUY_FEE_RATE:.1%} 卖{SELL_FEE_RATE:.1%}｜"
            f"单份获利需涨 ≥{min_move:.2%}",
        )
    elif closed_reason:
        notify(
            "积存金监控已启动",
            f"> 行情请求已暂停：{closed_reason}\n{position_summary(state, 0)}",
        )
    else:
        notify("积存金监控已启动", "> 启动取价失败，稍后自动重试")

    failure_count = 0
    tick_count = 0
    delay = POLL_INTERVAL
    closed_until = next_price_request_time() if closed_reason else None
    while True:
        time.sleep(delay)
        now = datetime.now()
        if not is_price_request_allowed(now):
            next_open = next_price_request_time(now)
            if next_open != closed_until:
                log(f"行情请求已暂停：{market_closed_message(now)}")
            closed_until = next_open
            failure_count = 0
            delay = POLL_INTERVAL
            continue
        if closed_until is not None:
            log("已进入取价时段，恢复请求黄金行情")
            closed_until = None
        try:
            price, yesterday, source = fetch_price(now)
        except Exception as exc:
            failure_count += 1
            delay = min(POLL_INTERVAL * (2 ** min(failure_count, 5)), MAX_BACKOFF)
            log(f"取价失败（连续 {failure_count} 次，下次 {delay} 秒后重试）: {exc}")
            continue

        if failure_count:
            log(f"取价已恢复，之前连续失败 {failure_count} 次，当前来源：{source}")
        failure_count = 0
        delay = POLL_INTERVAL
        tick_count += 1

        with state_lock():
            state = _load_state_unlocked()
            before = json.dumps(state, ensure_ascii=False, sort_keys=True)
            messages = process_tick(price, state)
            after = json.dumps(state, ensure_ascii=False, sort_keys=True)
            if after != before:
                _save_state_unlocked(state)

        lots = state["lots"]
        nearest_sell = min((sell_target(item["price"]) for item in lots), default=None)
        ref = lots[-1]["price"] if lots else state["anchor"]
        if messages or tick_count % HEARTBEAT_TICKS == 0:
            log(
                f"现价 {price:.2f}({source}) | 持仓 {len(lots)} 份 | "
                f"下格买入 {ref * (1 - GRID_STEP_PCT):.2f} | "
                f"最近卖出 {f'{nearest_sell:.2f}' if nearest_sell else '—'}"
            )
        for title, content in messages:
            notify(title, content)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("已停止")
    except Exception as exc:
        logger.critical("程序异常退出: %s\n%s", exc, traceback.format_exc())
        raise
