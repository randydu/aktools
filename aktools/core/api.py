# -*- coding:utf-8 -*-
# /usr/bin/env python
"""
Date: 2024/1/12 22:05
Desc: HTTP 模式主文件
"""
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

import akshare as ak
from fastapi import APIRouter
from fastapi import Depends, status
from fastapi import Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

from aktools.datasets import get_pyscript_html, get_template_path
from aktools.login.user_login import User, get_current_active_user

app_core = APIRouter()

RETRY_MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5


# ── 统一 A 股历史行情数据源配置 ──────────────────────────────────
# 环境变量 AKSHARE_DEFAULT_SOURCE 设置默认源，可选: eastmoney / sina / tencent
# ── 数据目录（Docker 友好） ──────────────────────────────────────
_DATA_DIR = os.getenv("AKTOOLS_DATA_DIR", os.path.join(os.getcwd(), "data"))
os.makedirs(_DATA_DIR, exist_ok=True)

DEFAULT_SOURCE = os.getenv("AKSHARE_DEFAULT_SOURCE", "eastmoney")  # mutable — changed by /api/v1/default_source

_SOURCE_MAP = {
    "eastmoney": {"func": ak.stock_zh_a_hist, "prefixed": False},
    "sina": {"func": ak.stock_zh_a_daily, "prefixed": True},
    "tencent": {"func": ak.stock_zh_a_hist_tx, "prefixed": True},
}

# 实时行情数据源（函数无参数，返回全市场数据）
_SPOT_SOURCE_MAP = {
    "eastmoney": ak.stock_zh_a_spot_em,
    "sina": ak.stock_zh_a_spot,
}

# 其他慢速无参接口（股票列表等），与实时行情共用缓存线程
# ETF 实时行情数据源
_FUND_SPOT_SOURCE_MAP = {
    "eastmoney": ak.fund_etf_spot_em,
}

# ETF 历史行情数据源
_FUND_ETF_HIST_SOURCE_MAP = {
    "eastmoney": {"func": ak.fund_etf_hist_em, "prefixed": False},
    "sina": {"func": ak.fund_etf_hist_sina, "prefixed": True},
}

# US 股票数据源
_US_SPOT_SOURCE_MAP = {
    "eastmoney": ak.stock_us_spot_em,
}

_US_HIST_SOURCE_MAP = {
    "eastmoney": {"func": ak.stock_us_hist, "prefixed": False},
    "sina": {"func": ak.stock_us_daily, "prefixed": False},
}

_STATIC_CACHE_MAP = {
    "stock_cn_list": ak.stock_info_a_code_name,
    "fund_list": ak.fund_name_em,
    "stock_us_list": ak.get_us_stock_name,
    "board_industry_list": ak.stock_board_industry_name_em,
    "board_concept_list": ak.stock_board_concept_name_em,
    "stock_profile": None,  # built from constituent data below
}


def _build_stock_profile():
    """Build a {code: {industry, concepts}} lookup from constituent data.
    Runs during daily cache refresh. Empty on any failure — retry next cycle."""
    try:
        profile = {}
        # Industry mapping
        industries = ak.stock_board_industry_name_em()
        for _, row in industries.iterrows():
            name = str(row.iloc[1] if len(row) > 1 else row.iloc[0])
            try:
                cons = ak.stock_board_industry_cons_em(symbol=name)
                code_col = "代码" if "代码" in cons.columns else cons.columns[0]
                for _, crow in cons.iterrows():
                    code = str(crow[code_col])
                    profile.setdefault(code, {})["industry"] = name
            except Exception:
                continue
        # Concept mapping
        concepts = ak.stock_board_concept_name_em()
        for _, row in concepts.iterrows():
            name = str(row.iloc[1] if len(row) > 1 else row.iloc[0])
            try:
                cons = ak.stock_board_concept_cons_em(symbol=name)
                code_col = "代码" if "代码" in cons.columns else cons.columns[0]
                for _, crow in cons.iterrows():
                    code = str(crow[code_col])
                    profile.setdefault(code, {}).setdefault("concepts", []).append(name)
            except Exception:
                continue
        # Convert to list of dicts for JSON serialization
        return [{"code": k, **v} for k, v in profile.items()]
    except Exception:
        return None

# ── 缓存（后台线程定期刷新） ──────────────────────────────────
_CACHE_TTL = 60          # 实时行情刷新间隔（秒）
_STATIC_CACHE_TTL = 86400  # 静态数据刷新间隔（秒，默认 1 天）
_spot_cache = {}  # {key: {"data": [...], "ts": float}}
_spot_cache_lock = threading.Lock()
_spot_cache_warm = threading.Event()  # 首次刷新完成后置位
_paused_keys = set()                  # 暂停的缓存 key，含 "*" 表示全局暂停
_paused_lock = threading.Lock()
_CACHE_TTL_OFF = 300                  # 非交易时段刷新间隔（秒）

# ── 缓存持久化到 SQLite ──────────────────────────────────────
import sqlite3 as _sqlite3
_CACHE_DB = os.path.join(_DATA_DIR, "cache.db")


def _persist_cache_to_db():
    """Write all in-memory cache entries to SQLite (WAL mode, crash-safe)."""
    with _spot_cache_lock:
        if not _spot_cache:
            return
        try:
            conn = _sqlite3.connect(_CACHE_DB)
            conn.execute("PRAGMA journal_mode=WAL")       # crash-safe atomic commits
            conn.execute("PRAGMA synchronous=NORMAL")     # balance safety & speed
            conn.execute(
                "CREATE TABLE IF NOT EXISTS persisted_cache "
                "(key TEXT PRIMARY KEY, data TEXT, ts REAL)"
            )
            conn.execute("BEGIN IMMEDIATE")
            for key, entry in _spot_cache.items():
                data_json = json.dumps(entry["data"], ensure_ascii=False)
                conn.execute(
                    "INSERT OR REPLACE INTO persisted_cache VALUES (?, ?, ?)",
                    (key, data_json, entry["ts"]),
                )
            conn.commit()
            conn.close()
        except Exception:
            pass  # persistence is best-effort


def _load_cache_from_db():
    """Restore cache from SQLite on startup."""
    try:
        conn = _sqlite3.connect(_CACHE_DB)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS persisted_cache "
            "(key TEXT PRIMARY KEY, data TEXT, ts REAL)"
        )
        rows = conn.execute("SELECT key, data, ts FROM persisted_cache").fetchall()
        conn.close()
        if rows:
            with _spot_cache_lock:
                for key, data_json, ts in rows:
                    _spot_cache[key] = {"data": json.loads(data_json), "ts": ts}
            logger.info(f"从 cache.db 恢复了 {len(rows)} 个缓存项")
            return True
    except Exception:
        pass
    return False

# A 股交易时段 (北京时间)
_MARKET_SESSIONS = [
    ((9, 30), (11, 30)),
    ((13, 0), (15, 0)),
]


def _is_market_open() -> bool:
    """Check if A-share market is currently open (Beijing time, Mon-Fri)."""
    now = datetime.now(timezone(timedelta(hours=8)))  # UTC+8
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    t = (now.hour, now.minute)
    for (h1, m1), (h2, m2) in _MARKET_SESSIONS:
        if (h1, m1) <= t < (h2, m2):
            return True
    return False


def _refresh_cache():
    """Daemon thread: periodically refresh cached data (market-aware, pausable)."""
    cycle = 0
    _static_interval = max(1, _STATIC_CACHE_TTL // _CACHE_TTL)
    while True:
        # 检查全局暂停
        with _paused_lock:
            if "*" in _paused_keys:
                time.sleep(1)
                continue
        cycle += 1
        market_open = _is_market_open()
        ttl = _CACHE_TTL if market_open else _CACHE_TTL_OFF
        cycle_start = time.time()
        succeeded = 0
        failed = 0
        # 刷新实时行情（每周期）— A 股
        for source, func in _SPOT_SOURCE_MAP.items():
            try:
                df = func()
                if df is not None:
                    data = json.loads(df.to_json(orient="records", date_format="iso"))
                    with _spot_cache_lock:
                        _spot_cache["stock_cn_spot_" + source] = {"data": data, "ts": time.time()}
                    logger.info(f"缓存已刷新: stock_spot_{source} ({len(data)} 条)")
                    succeeded += 1
            except Exception as e:
                logger.warning(f"刷新缓存失败 [stock_spot_{source}]: {e}")
                failed += 1
        # 刷新实时行情（每周期）— ETF
        for source, func in _FUND_SPOT_SOURCE_MAP.items():
            try:
                df = func()
                if df is not None:
                    data = json.loads(df.to_json(orient="records", date_format="iso"))
                    with _spot_cache_lock:
                        _spot_cache["fund_etf_spot"] = {"data": data, "ts": time.time()}
                    logger.info(f"缓存已刷新: fund_etf_spot ({len(data)} 条)")
                    succeeded += 1
            except Exception as e:
                logger.warning(f"刷新缓存失败 [fund_etf_spot]: {e}")
                failed += 1
        # 刷新实时行情（每周期）— US
        for source, func in _US_SPOT_SOURCE_MAP.items():
            try:
                df = func()
                if df is not None:
                    data = json.loads(df.to_json(orient="records", date_format="iso"))
                    with _spot_cache_lock:
                        _spot_cache["stock_us_spot"] = {"data": data, "ts": time.time()}
                    logger.info(f"缓存已刷新: stock_us_spot ({len(data)} 条)")
                    succeeded += 1
            except Exception as e:
                logger.warning(f"刷新缓存失败 [stock_us_spot]: {e}")
                failed += 1

        # 静态数据仅在启动或每 _static_interval 个周期刷新
        if cycle == 1 or cycle % _static_interval == 0:
            for key, func in _STATIC_CACHE_MAP.items():
                try:
                    if func is None and key == "stock_profile":
                        data = _build_stock_profile()
                    else:
                        df = func()
                        if df is not None:
                            data = json.loads(df.to_json(orient="records", date_format="iso"))
                        else:
                            data = None
                    if data is not None:
                        # 清理名称中的空白字符
                        for row in (data if isinstance(data, list) else []):
                            if isinstance(row, dict) and "name" in row and isinstance(row["name"], str):
                                row["name"] = "".join(row["name"].split())
                        with _spot_cache_lock:
                            _spot_cache[key] = {"data": data, "ts": time.time()}
                        logger.info(f"缓存已刷新: {key} ({len(data)} 条)")
                        succeeded += 1
                except Exception as e:
                    logger.warning(f"刷新缓存失败 [{key}]: {e}")
                    failed += 1
        if cycle == 1:
            _spot_cache_warm.set()
        elapsed = int((time.time() - cycle_start) * 1000)
        logger.info(
            f"刷新周期 #{cycle} 完成: {succeeded} 成功, {failed} 失败, "
            f"耗时 {elapsed}ms, 下次 {ttl}s 后"
            f"({'交易时段' if market_open else '非交易时段'})"
        )
        _persist_cache_to_db()
        time.sleep(ttl)


# 启动时从 SQLite 恢复缓存（若有），避免冷启动等待
_restored = _load_cache_from_db()
if _restored:
    _spot_cache_warm.set()  # 恢复后可立即服务
    logger.info("缓存已从磁盘恢复，预热完成")

_refresh_thread = threading.Thread(target=_refresh_cache, daemon=True)
_refresh_thread.start()


def _normalize_symbol(symbol: str, prefixed: bool) -> str:
    """Normalize a stock code to the format expected by the data source.

    East Money expects bare codes (``600000``); Sina / Tencent expect
    exchange-prefixed codes (``sh600000``, ``sz000001``).  If the user
    passes a prefixed code to East Money the prefix is stripped; if an
    unprefixed code is passed to Sina/Tencent the exchange is inferred
    from the first digit (5/6/9 → sh, 0/2/3 → sz).
    """
    symbol = symbol.strip().lower()
    prefixed_in = symbol.startswith(("sh", "sz"))
    code = symbol[2:] if prefixed_in else symbol
    if prefixed:
        if prefixed_in:
            return symbol
        return f"sh{code}" if re.match(r"[569]", code) else f"sz{code}"
    return code


def _call_akshare(item_id: str, eval_str: str):
    """Call an AKShare function with retry on transient network errors."""
    code = f"ak.{item_id}({eval_str})" if eval_str else f"ak.{item_id}()"
    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            return eval(code)
        except (RequestsConnectionError, RequestsTimeout) as e:
            if attempt == RETRY_MAX_ATTEMPTS:
                raise
            logger.warning(
                f"接口 {item_id} 第 {attempt}/{RETRY_MAX_ATTEMPTS} 次尝试失败: {e}，"
                f"{RETRY_DELAY_SECONDS} 秒后重试..."
            )
            time.sleep(RETRY_DELAY_SECONDS)


def _call_akshare_direct(func, **kwargs):
    """Call an AKShare function directly with retry."""
    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            return func(**kwargs)
        except (RequestsConnectionError, RequestsTimeout) as e:
            if attempt == RETRY_MAX_ATTEMPTS:
                raise
            logger.warning(
                f"第 {attempt}/{RETRY_MAX_ATTEMPTS} 次尝试失败: {e}，"
                f"{RETRY_DELAY_SECONDS} 秒后重试..."
            )
            time.sleep(RETRY_DELAY_SECONDS)


# 创建一个日志记录器
_LOG_LEVEL = os.getenv("AKTOOLS_LOG_LEVEL", "INFO").upper()
logger = logging.getLogger(name="AKToolsLog")
logger.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))

# 创建一个TimedRotatingFileHandler来进行日志轮转
handler = TimedRotatingFileHandler(
    filename=os.path.join(_DATA_DIR, 'aktools.log'),
    when='midnight', interval=1, backupCount=7, encoding='utf-8'
)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# 使用日志记录器记录信息
logger.info('这是一个信息级别的日志消息')


@app_core.get("/private/{item_id}", description="私人接口", summary="该接口主要提供私密访问来获取数据")
def root(
        request: Request,
        item_id: str,
        current_user: User = Depends(get_current_active_user),
):
    """
    接收请求参数及接口名称并返回 JSON 数据
    此处由于 AKShare 的请求中是同步模式，所以这边在定义 root 函数中没有使用 asyncio 来定义，这样可以开启多线程访问
    :param request: 请求信息
    :type request: Request
    :param item_id: 必选参数; 测试接口名 ak.stock_dxsyl_em() 来获取 打新收益率 数据
    :type item_id: str
    :param current_user: 依赖注入，为了进行用户的登录验证
    :type current_user: str
    :return: 指定 接口名称 和 参数 的数据
    :rtype: json
    """
    interface_list = dir(ak)
    decode_params = urllib.parse.unquote(str(request.query_params))
    # print(decode_params)
    if item_id not in interface_list:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "未找到该接口，请升级 AKShare 到最新版本并在文档中确认该接口的使用方式：https://akshare.akfamily.xyz"
            },
        )
    eval_str = decode_params.replace("&", '", ').replace("=", '="') + '"'
    if not bool(request.query_params):
        try:
            received_df = _call_akshare(item_id, "")
            if received_df is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"error": "该接口返回数据为空，请确认参数是否正确：https://akshare.akfamily.xyz"},
                )
            temp_df = received_df.to_json(orient="records", date_format="iso")
        except KeyError as e:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": f"请输入正确的参数错误 {e}，请升级 AKShare 到最新版本并在文档中确认该接口的使用方式：https://akshare.akfamily.xyz"
                },
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            logger.error(f"接口 {item_id} 重试 {RETRY_MAX_ATTEMPTS} 次后仍失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"上游数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次，请稍后重试"
                },
            )
        except Exception as e:
            logger.error(f"接口 {item_id} 调用失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"数据接口调用异常: {e}，可能是上游数据源暂时不可用，请稍后重试"
                },
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=json.loads(temp_df))
    else:
        try:
            received_df = _call_akshare(item_id, eval_str)
            if received_df is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"error": "该接口返回数据为空，请确认参数是否正确：https://akshare.akfamily.xyz"},
                )
            temp_df = received_df.to_json(orient="records", date_format="iso")
        except KeyError as e:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": f"请输入正确的参数错误 {e}，请升级 AKShare 到最新版本并在文档中确认该接口的使用方式：https://akshare.akfamily.xyz"
                },
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            logger.error(f"接口 {item_id} 重试 {RETRY_MAX_ATTEMPTS} 次后仍失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"上游数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次，请稍后重试"
                },
            )
        except Exception as e:
            logger.error(f"接口 {item_id} 调用失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"数据接口调用异常: {e}，可能是上游数据源暂时不可用，请稍后重试"
                },
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=json.loads(temp_df))


@app_core.get(
    path="/public/v1/stock_cn_hist",
    description="A 股历史行情接口 (v1)",
    summary="支持切换数据源（eastmoney/sina/tencent），方便海外用户访问",
)
def stock_cn_hist(
    request: Request,
    symbol: str = Query(..., description="股票代码，如 600000 或 sh600000"),
    source: str = Query(
        "", description=f"数据源，可选 eastmoney/sina/tencent，默认 {DEFAULT_SOURCE}"
    ),
    start_date: str = Query("19900101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("20500101", description="结束日期 YYYYMMDD"),
    adjust: str = Query("", description="复权类型: 空=不复权, qfq=前复权, hfq=后复权"),
):
    source = source or DEFAULT_SOURCE
    source_config = _SOURCE_MAP.get(source)
    if source_config is None:
        valid = ", ".join(_SOURCE_MAP)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": f"不支持的数据源: {source}，可选: {valid}"},
        )

    normalized = _normalize_symbol(symbol, source_config["prefixed"])
    logger.info(f"统一接口: symbol={symbol} → {normalized}, source={source}")

    try:
        received_df = _call_akshare_direct(
            source_config["func"],
            symbol=normalized,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        if received_df is None:
            logger.info("该接口返回数据为空，请确认参数是否正确")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "该接口返回数据为空，请确认参数是否正确"},
            )
        temp_df = received_df.to_json(orient="records", date_format="iso")
    except (RequestsConnectionError, RequestsTimeout) as e:
        logger.error(f"统一接口 {source} 重试 {RETRY_MAX_ATTEMPTS} 次后仍失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"{source} 数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次，请稍后重试或切换数据源"
            },
        )
    except Exception as e:
        logger.error(f"统一接口调用失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": f"数据接口调用异常: {e}"},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=json.loads(temp_df))


@app_core.get(
    path="/public/v1/stock_cn_spot",
    description="A 股实时行情接口 (v1)",
    summary="支持切换数据源（eastmoney/sina），可筛选个股",
)
def stock_cn_spot(
    request: Request,
    source: str = Query(
        "", description=f"数据源，可选 eastmoney/sina，默认 {DEFAULT_SOURCE}"
    ),
    symbol: str = Query("", description="股票代码筛选，如 600000 或 sh600000，留空返回全市场"),
):
    source = source or DEFAULT_SOURCE
    if source not in _SPOT_SOURCE_MAP:
        valid = ", ".join(_SPOT_SOURCE_MAP)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": f"不支持的数据源: {source}，可选: {valid}"},
        )

    # 缓存优先：先查请求源 → 再查其他源 → 最后才发起网络调用
    with _spot_cache_lock:
        cache_key = "stock_cn_spot_" + source
        entry = _spot_cache.get(cache_key)
        fallback_entry = None
        if entry is None:
            for s in _SPOT_SOURCE_MAP:
                alt_key = "stock_cn_spot_" + s
                if s != source and alt_key in _spot_cache:
                    fallback_entry = _spot_cache[alt_key]
                    break

    stale_headers = {}
    if entry is not None:
        data = entry["data"]
        stale_headers = _stale_headers(entry["ts"])
        logger.info(
            f"实时行情缓存命中: source={source}, "
            f"age={int(time.time() - entry['ts'])}s"
        )
    elif fallback_entry is not None:
        data = fallback_entry["data"]
        stale_headers = _stale_headers(fallback_entry["ts"])
        source = next(s for s, e in _spot_cache.items() if e is fallback_entry)
        logger.info(
            f"实时行情回退到备用缓存: {source}, "
            f"age={int(time.time() - fallback_entry['ts'])}s"
        )
    else:
        # 缓存正在预热中，快速返回 503 而非阻塞 30s
        if not _spot_cache_warm.is_set():
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "实时行情缓存预热中，请 30 秒后重试"
                },
                headers={"Retry-After": "30"},
            )

        logger.info(f"所有缓存未命中，直接调用 {source}")
        func = _SPOT_SOURCE_MAP[source]
        try:
            df = _call_akshare_direct(func)
            if df is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"error": "该接口返回数据为空"},
                )
            data = json.loads(df.to_json(orient="records", date_format="iso"))
        except (RequestsConnectionError, RequestsTimeout) as e:
            logger.error(f"实时行情 {source} 直接调用失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"{source} 数据源不可用且无可回退缓存，请稍后重试"
                },
            )
        except Exception as e:
            logger.error(f"实时行情直接调用异常: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"error": f"数据接口调用异常: {e}"},
            )

    # 按个股代码筛选
    if symbol:
        code = _normalize_symbol(symbol, prefixed=False)
        data = [row for row in data if code in str(row.get("代码", "")).lower()]
        if not data:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到股票代码: {symbol}"},
            )

    return JSONResponse(
        status_code=status.HTTP_200_OK, content=data, headers=stale_headers
    )


@app_core.get(
    path="/public/v1/stock_cn_list",
    description="A 股股票代码列表 (v1, 缓存)",
    summary="返回沪深京 A 股代码与名称，数据来自后台缓存，响应 <10ms",
)
def stock_cn_list(
    request: Request,
    page: int = Query(0, ge=0, description="页码，0=不分页"),
    page_size: int = Query(100, ge=1, le=1000, description="每页条数（最大 1000）"),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("stock_cn_list")

    if entry is not None:
        data = entry["data"]
        age = int(time.time() - entry["ts"])
        total = len(data)
        if page > 0:
            start = (page - 1) * page_size
            data = data[start : start + page_size]
        logger.info(f"股票列表缓存命中: age={age}s, page={page}, returned={len(data)}/{total}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=data,
            headers={"X-Total-Count": str(total)},
        )

    if not _spot_cache_warm.is_set():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "缓存预热中，请稍后重试"},
            headers={"Retry-After": "30"},
        )

    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"error": "股票列表数据源不可用，请稍后重试"},
    )


@app_core.get(
    path="/public/v1/fund_list",
    description="基金代码列表 (v1, 缓存)",
    summary="返回全部基金代码、简称与类型，数据来自后台缓存，响应 <10ms",
)
def fund_list_cached(
    request: Request,
    page: int = Query(0, ge=0, description="页码，0=不分页"),
    page_size: int = Query(100, ge=1, le=1000, description="每页条数（最大 1000）"),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("fund_list")

    if entry is not None:
        data = entry["data"]
        age = int(time.time() - entry["ts"])
        total = len(data)
        if page > 0:
            start = (page - 1) * page_size
            data = data[start : start + page_size]
        logger.info(f"基金列表缓存命中: age={age}s, page={page}, returned={len(data)}/{total}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=data,
            headers={"X-Total-Count": str(total)},
        )

    if not _spot_cache_warm.is_set():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "缓存预热中，请稍后重试"},
            headers={"Retry-After": "30"},
        )

    # 缓存已预热但此 key 缺失 — 后台刷新已失败，直接返回错误避免阻塞
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"error": "基金列表数据源不可用，请稍后重试"},
    )


@app_core.get(
    path="/public/v1/fund_etf_spot",
    description="ETF 实时行情接口 (v1, 缓存)",
    summary="返回 ETF 实时行情，数据来自后台缓存，响应 <10ms",
)
def fund_etf_spot_cached(
    request: Request,
    symbol: str = Query("", description="ETF 代码筛选，如 159915，留空返回全市场"),
):
    cache_key = "fund_etf_spot"
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)

    if entry is not None:
        data = entry["data"]
        age = int(time.time() - entry["ts"])
        stale_headers = _stale_headers(entry["ts"])
        logger.info(f"ETF 行情缓存命中: age={age}s, count={len(data)}")
    elif not _spot_cache_warm.is_set():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "ETF 行情缓存预热中，请稍后重试"},
            headers={"Retry-After": "30"},
        )
    else:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "ETF 行情数据源不可用，请稍后重试"},
        )

    # 按代码筛选
    if symbol:
        code = symbol.strip().lower()
        data = [row for row in data if code in str(row.get("基金代码", row.get("代码", ""))).lower()]
        if not data:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到 ETF 代码: {symbol}"},
            )

    return JSONResponse(
        status_code=status.HTTP_200_OK, content=data, headers=stale_headers
    )


@app_core.get(
    path="/public/v1/fund_etf_hist",
    description="统一 ETF 历史行情接口 (v1)",
    summary="支持切换数据源（eastmoney/sina），方便海外用户访问",
)
def fund_etf_hist_universal(
    request: Request,
    symbol: str = Query(..., description="ETF 代码，如 159915 或 sh510050"),
    source: str = Query(
        "", description=f"数据源，可选 eastmoney/sina，默认 {DEFAULT_SOURCE}"
    ),
    start_date: str = Query("19700101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("20500101", description="结束日期 YYYYMMDD"),
    adjust: str = Query("", description="复权类型: 空=不复权, qfq=前复权, hfq=后复权"),
):
    source = source or DEFAULT_SOURCE
    source_config = _FUND_ETF_HIST_SOURCE_MAP.get(source)
    if source_config is None:
        valid = ", ".join(_FUND_ETF_HIST_SOURCE_MAP)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": f"不支持的数据源: {source}，可选: {valid}"},
        )

    normalized = _normalize_symbol(symbol, source_config["prefixed"])
    logger.info(f"ETF 历史: symbol={symbol} → {normalized}, source={source}")

    try:
        received_df = _call_akshare_direct(
            source_config["func"],
            symbol=normalized,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        if received_df is None:
            logger.info("ETF 历史数据为空")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "该接口返回数据为空，请确认参数是否正确"},
            )
        temp_df = received_df.to_json(orient="records", date_format="iso")
    except (RequestsConnectionError, RequestsTimeout) as e:
        logger.error(f"ETF 历史 {source} 重试 {RETRY_MAX_ATTEMPTS} 次后仍失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"{source} 数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次，请稍后重试或切换数据源"
            },
        )
    except Exception as e:
        logger.error(f"ETF 历史调用失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": f"数据接口调用异常: {e}"},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=json.loads(temp_df))


@app_core.get(
    path="/public/v1/stock_us_list",
    description="美股代码列表 (v1, 缓存)",
    summary="返回美股代码与名称，数据来自后台缓存，响应 <10ms",
)
def stock_us_list_cached(
    request: Request,
    page: int = Query(0, ge=0, description="页码，0=不分页"),
    page_size: int = Query(100, ge=1, le=1000, description="每页条数（最大 1000）"),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("stock_us_list")

    if entry is not None:
        data = entry["data"]
        age = int(time.time() - entry["ts"])
        total = len(data)
        if page > 0:
            start = (page - 1) * page_size
            data = data[start : start + page_size]
        logger.info(f"美股列表缓存命中: age={age}s, page={page}, returned={len(data)}/{total}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=data,
            headers={"X-Total-Count": str(total)},
        )

    if not _spot_cache_warm.is_set():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "缓存预热中，请稍后重试"},
            headers={"Retry-After": "30"},
        )

    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"error": "美股列表数据源不可用，请稍后重试"},
    )


@app_core.get(
    path="/public/v1/stock_us_spot",
    description="美股实时行情接口 (v1, 缓存)",
    summary="返回美股实时行情，数据来自后台缓存，响应 <10ms",
)
def stock_us_spot_cached(
    request: Request,
    symbol: str = Query("", description="美股代码筛选，如 AAPL，留空返回全市场"),
):
    cache_key = "stock_us_spot"
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)

    if entry is not None:
        data = entry["data"]
        age = int(time.time() - entry["ts"])
        stale_headers = _stale_headers(entry["ts"])
        logger.info(f"美股行情缓存命中: age={age}s, count={len(data)}")
    elif not _spot_cache_warm.is_set():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "美股行情缓存预热中，请稍后重试"},
            headers={"Retry-After": "30"},
        )
    else:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "美股行情数据源不可用，请稍后重试"},
        )

    if symbol:
        code = symbol.strip().upper()
        data = [row for row in data if code in str(row.get("代码", row.get("code", ""))).upper()]
        if not data:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到美股代码: {symbol}"},
            )

    return JSONResponse(
        status_code=status.HTTP_200_OK, content=data, headers=stale_headers
    )


@app_core.get(
    path="/public/v1/stock_us_hist",
    description="统一美股历史行情接口 (v1)",
    summary="支持切换数据源（eastmoney/sina），方便海外用户访问",
)
def stock_us_hist_universal(
    request: Request,
    symbol: str = Query(..., description="美股代码，如 AAPL 或 105.MSFT"),
    source: str = Query(
        "", description=f"数据源，可选 eastmoney/sina，默认 {DEFAULT_SOURCE}"
    ),
    start_date: str = Query("19700101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("22220101", description="结束日期 YYYYMMDD"),
    adjust: str = Query("", description="复权类型: 空=不复权, qfq=前复权, hfq=后复权"),
):
    source = source or DEFAULT_SOURCE
    source_config = _US_HIST_SOURCE_MAP.get(source)
    if source_config is None:
        valid = ", ".join(_US_HIST_SOURCE_MAP)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": f"不支持的数据源: {source}，可选: {valid}"},
        )

    logger.info(f"美股历史: symbol={symbol}, source={source}")

    try:
        received_df = _call_akshare_direct(
            source_config["func"],
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        if received_df is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "该接口返回数据为空，请确认参数是否正确"},
            )
        temp_df = received_df.to_json(orient="records", date_format="iso")
    except (RequestsConnectionError, RequestsTimeout) as e:
        logger.error(f"美股历史 {source} 重试 {RETRY_MAX_ATTEMPTS} 次后仍失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"{source} 数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次，请稍后重试或切换数据源"
            },
        )
    except Exception as e:
        logger.error(f"美股历史调用失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": f"数据接口调用异常: {e}"},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=json.loads(temp_df))


# ── 板块 V1 端点 ──────────────────────────────────────────────

@app_core.get(
    path="/public/v1/board_industry_list",
    description="行业板块列表 (v1, 缓存)",
    summary="返回 A 股行业板块名称，数据来自后台缓存",
)
def board_industry_list_cached(
    request: Request,
    page: int = Query(0, ge=0, description="页码，0=不分页"),
    page_size: int = Query(100, ge=1, le=1000, description="每页条数（最大 1000）"),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("board_industry_list")
    if entry is not None:
        data = entry["data"]
        total = len(data)
        if page > 0:
            data = data[(page - 1) * page_size : page * page_size]
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=data,
            headers={"X-Total-Count": str(total)},
        )
    if not _spot_cache_warm.is_set():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "缓存预热中，请稍后重试"},
        )
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"error": "行业板块数据源不可用"},
    )


@app_core.get(
    path="/public/v1/board_concept_list",
    description="概念板块列表 (v1, 缓存)",
    summary="返回 A 股概念板块名称，数据来自后台缓存",
)
def board_concept_list_cached(
    request: Request,
    page: int = Query(0, ge=0, description="页码，0=不分页"),
    page_size: int = Query(100, ge=1, le=1000, description="每页条数（最大 1000）"),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("board_concept_list")
    if entry is not None:
        data = entry["data"]
        total = len(data)
        if page > 0:
            data = data[(page - 1) * page_size : page * page_size]
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=data,
            headers={"X-Total-Count": str(total)},
        )
    if not _spot_cache_warm.is_set():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "缓存预热中，请稍后重试"},
        )
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"error": "概念板块数据源不可用"},
    )


@app_core.get(
    path="/public/v1/board_industry_spot",
    description="行业板块实时行情 (v1)",
    summary="返回指定行业板块的实时行情",
)
def board_industry_spot(
    symbol: str = Query(..., description="行业名称，如 小金属、半导体"),
):
    data, err = _cached_on_demand(
        "board_industry_spot:" + symbol,
        ak.stock_board_industry_spot_em, symbol=symbol,
    )
    if err:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND if err == 404 else status.HTTP_502_BAD_GATEWAY,
            content={"error": f"未找到行业板块: {symbol}" if err == 404 else "数据源连接失败，请稍后重试"},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=data)


@app_core.get(
    path="/public/v1/board_concept_spot",
    description="概念板块实时行情 (v1)",
    summary="返回指定概念板块的实时行情",
)
def board_concept_spot(
    symbol: str = Query(..., description="概念名称，如 可燃冰、元宇宙"),
):
    data, err = _cached_on_demand(
        "board_concept_spot:" + symbol,
        ak.stock_board_concept_spot_em, symbol=symbol,
    )
    if err:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND if err == 404 else status.HTTP_502_BAD_GATEWAY,
            content={"error": f"未找到概念板块: {symbol}" if err == 404 else "数据源连接失败，请稍后重试"},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=data)


@app_core.get(
    path="/public/v1/board_industry_hist",
    description="行业板块历史指数 (v1)",
    summary="返回行业板块历史指数数据（同花顺源）",
)
def board_industry_hist(
    symbol: str = Query(..., description="行业名称，如 元件"),
    start_date: str = Query("20200101", description="开始日期"),
    end_date: str = Query("20250101", description="结束日期"),
):
    data, err = _cached_on_demand(
        f"board_industry_hist:{symbol}:{start_date}:{end_date}",
        ak.stock_board_industry_index_ths,
        symbol=symbol, start_date=start_date, end_date=end_date,
    )
    if err:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND if err == 404 else status.HTTP_502_BAD_GATEWAY,
            content={"error": f"未找到行业板块: {symbol}" if err == 404 else "数据源连接失败，请稍后重试"},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=data)


@app_core.get(
    path="/public/v1/board_concept_hist",
    description="概念板块历史指数 (v1)",
    summary="返回概念板块历史指数数据（同花顺源）",
)
def board_concept_hist(
    symbol: str = Query(..., description="概念名称，如 阿里巴巴概念"),
    start_date: str = Query("20200101", description="开始日期"),
    end_date: str = Query("20250228", description="结束日期"),
):
    data, err = _cached_on_demand(
        f"board_concept_hist:{symbol}:{start_date}:{end_date}",
        ak.stock_board_concept_index_ths,
        symbol=symbol, start_date=start_date, end_date=end_date,
    )
    if err:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND if err == 404 else status.HTTP_502_BAD_GATEWAY,
            content={"error": f"未找到概念板块: {symbol}" if err == 404 else "数据源连接失败，请稍后重试"},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=data)


@app_core.get(
    path="/public/v1/default_source",
    description="查看默认数据源",
    summary="返回当前默认数据源及可用选项",
)
def default_source_get():
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"default_source": DEFAULT_SOURCE, "available": list(_SOURCE_MAP)},
    )


@app_core.post(
    path="/private/v1/default_source",
    description="切换默认数据源",
    summary="切换默认数据源（需要认证）",
)
def default_source_set(
    source: str = Query(..., description="新默认源: eastmoney / sina / tencent"),
    _current_user: User = Depends(get_current_active_user),
):
    global DEFAULT_SOURCE
    if source not in _SOURCE_MAP:
        valid = ", ".join(_SOURCE_MAP)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": f"不支持的数据源: {source}，可选: {valid}"},
        )
    old = DEFAULT_SOURCE
    DEFAULT_SOURCE = source
    logger.info(f"默认数据源切换: {old} → {source}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"default_source": DEFAULT_SOURCE, "previous": old},
    )


@app_core.post(
    path="/private/v1/cache/pause",
    description="暂停缓存后台刷新",
    summary="暂停自动刷新，已在进行的刷新不受影响",
)
def cache_pause(
    keys: str = Query("", description="要暂停的缓存 key，逗号分隔，空=全部暂停"),
    _current_user: User = Depends(get_current_active_user),
):
    with _paused_lock:
        if keys:
            for k in keys.split(","):
                _paused_keys.add(k.strip())
            logger.info(f"缓存 {keys} 已暂停")
        else:
            _paused_keys.add("*")
            logger.info("缓存刷新已全局暂停")
    with _paused_lock:
        current = sorted(_paused_keys)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"paused": True, "paused_keys": current},
    )


@app_core.post(
    path="/private/v1/cache/resume",
    description="恢复缓存后台刷新",
    summary="恢复自动刷新",
)
def cache_resume(
    keys: str = Query("", description="要恢复的缓存 key，逗号分隔，空=全部恢复"),
    _current_user: User = Depends(get_current_active_user),
):
    with _paused_lock:
        if keys:
            for k in keys.split(","):
                _paused_keys.discard(k.strip())
            logger.info(f"缓存 {keys} 已恢复")
        else:
            _paused_keys.clear()
            logger.info("缓存刷新已全部恢复")
    with _paused_lock:
        current = sorted(_paused_keys)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"paused": len(current) > 0, "paused_keys": current},
    )


@app_core.get(
    path="/public/v1/cache_status",
    description="缓存状态",
    summary="返回所有缓存项的元信息（条数、最后更新时间）",
)
def cache_status(request: Request):
    # Map cache keys to their refresh intervals
    _intervals = {}
    for s in _SPOT_SOURCE_MAP:
        _intervals["stock_cn_spot_" + s] = _CACHE_TTL
    for s in _FUND_SPOT_SOURCE_MAP:
        _intervals["fund_etf_spot"] = _CACHE_TTL
    for s in _US_SPOT_SOURCE_MAP:
        _intervals["stock_us_spot"] = _CACHE_TTL
    for k in _STATIC_CACHE_MAP:
        _intervals[k] = _STATIC_CACHE_TTL

    with _spot_cache_lock:
        result = {}
        now = time.time()
        for key, entry in _spot_cache.items():
            result[key] = {
                "count": len(entry["data"]),
                "updated_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(entry["ts"])
                ),
                "age_seconds": int(now - entry["ts"]),
                "refresh_interval_seconds": _intervals.get(key, _CACHE_TTL),
            }
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "warm": _spot_cache_warm.is_set(),
            "paused": '*' in _paused_keys,
            "market_open": _is_market_open(),
            "caches": result,
        },
    )


_SPOT_STALE_THRESHOLD = 120  # 交易时段超过此秒数视为过期


def _cached_on_demand(cache_key: str, func, **kwargs) -> tuple[list | None, int | None]:
    """Serve from cache if available, otherwise call func and cache result.
    Returns (data, status_code_or_None). None status = 200 with data.
    """
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)
    if entry is not None:
        age = int(time.time() - entry["ts"])
        if age < _CACHE_TTL:
            return entry["data"], None
    try:
        df = _call_akshare_direct(func, **kwargs)
        if df is None:
            return None, 404
        data = json.loads(df.to_json(orient="records", date_format="iso"))
        with _spot_cache_lock:
            _spot_cache[cache_key] = {"data": data, "ts": time.time()}
        return data, None
    except (RequestsConnectionError, RequestsTimeout):
        # If we have stale cache, serve it anyway
        if entry is not None:
            return entry["data"], None
        return None, 502
    except Exception:
        return None, 502


def _stale_headers(cache_ts: float) -> dict:
    """Return headers indicating whether cached data is stale."""
    age = int(time.time() - cache_ts)
    market_open = _is_market_open()
    stale = market_open and age > _SPOT_STALE_THRESHOLD
    headers = {"X-Cache-Age": str(age)}
    if stale:
        headers["X-Cache-Stale"] = "true"
        headers["Warning"] = f'110 - "Response is Stale (age={age}s)"'
    return headers


def _search_cache(
    cache_key: str, q: str, limit: int, code_col: str, name_col: str
):
    """Search a cached list by code or name (case-insensitive substring)."""
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)
    if entry is None:
        return None, 0
    q_lower = q.strip().lower()
    matches = [
        {"code": str(row.get(code_col, "")), "name": str(row.get(name_col, ""))}
        for row in entry["data"]
        if q_lower in str(row.get(code_col, "")).lower()
        or q_lower in str(row.get(name_col, "")).lower()
    ]
    total = len(matches)
    return (matches if limit == 0 else matches[:limit]), total


@app_core.get(
    path="/public/v1/stock_cn_search",
    description="股票代码/名称搜索 (v1)",
    summary="基于缓存列表搜索股票代码或名称，支持模糊匹配",
)
def stock_cn_search(
    q: str = Query(..., min_length=1, description="搜索关键词（子串匹配，非前缀匹配）"),
    limit: int = Query(20, ge=0, le=1000, description="最大返回条数，0=不限制"),
):
    matches, total = _search_cache("stock_cn_list", q, limit, "code", "name")
    if matches is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "股票列表缓存未就绪，请稍后重试"},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=matches,
        headers={"X-Total-Count": str(total)},
    )


@app_core.get(
    path="/public/v1/fund_search",
    description="基金代码/名称搜索 (v1)",
    summary="基于缓存列表搜索基金代码或名称，支持模糊匹配",
)
def fund_search(
    q: str = Query(..., min_length=1, description="搜索关键词（子串匹配，非前缀匹配）"),
    limit: int = Query(20, ge=0, le=1000, description="最大返回条数，0=不限制"),
):
    matches, total = _search_cache("fund_list", q, limit, "基金代码", "基金简称")
    if matches is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "基金列表缓存未就绪，请稍后重试"},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=matches,
        headers={"X-Total-Count": str(total)},
    )


@app_core.get(
    path="/public/v1/stock_us_search",
    description="美股代码/名称搜索 (v1)",
    summary="基于缓存列表搜索美股代码或名称，支持模糊匹配",
)
def stock_us_search(
    q: str = Query(..., min_length=1, description="搜索关键词（子串匹配，非前缀匹配）"),
    limit: int = Query(20, ge=0, le=1000, description="最大返回条数，0=不限制"),
):
    matches, total = _search_cache("stock_us_list", q, limit, "code", "name")
    if matches is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "美股列表缓存未就绪，请稍后重试"},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=matches,
        headers={"X-Total-Count": str(total)},
    )


@app_core.get(path="/public/{item_id}", description="公开接口", summary="该接口主要提供公开访问来获取数据")
def root(request: Request, item_id: str):
    """
    接收请求参数及接口名称并返回 JSON 数据
    此处由于 AKShare 的请求中是同步模式，所以这边在定义 root 函数中没有使用 asyncio 来定义，这样可以开启多线程访问
    :param request: 请求信息
    :type request: Request
    :param item_id: 必选参数; 测试接口名 stock_dxsyl_em 来获取 打新收益率 数据
    :type item_id: str
    :return: 指定 接口名称 和 参数 的数据
    :rtype: json
    """
    interface_list = dir(ak)
    decode_params = urllib.parse.unquote(str(request.query_params))
    # print(decode_params)
    if item_id not in interface_list:
        logger.info("未找到该接口，请升级 AKShare 到最新版本并在文档中确认该接口的使用方式：https://akshare.akfamily.xyz")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "未找到该接口，请升级 AKShare 到最新版本并在文档中确认该接口的使用方式：https://akshare.akfamily.xyz"
            },
        )
    if "cookie" in decode_params:
        eval_str = (
                decode_params.split(sep="=", maxsplit=1)[0]
                + "='"
                + decode_params.split(sep="=", maxsplit=1)[1]
                + "'"
        )
        eval_str = eval_str.replace("+", " ")
    else:
        eval_str = decode_params.replace("&", '", ').replace("=", '="') + '"'
        eval_str = eval_str.replace("+", " ")  # 处理传递的参数中带空格的情况
    if not bool(request.query_params):
        try:
            received_df = _call_akshare(item_id, "")
            if received_df is None:
                logger.info("该接口返回数据为空，请确认参数是否正确：https://akshare.akfamily.xyz")
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"error": "该接口返回数据为空，请确认参数是否正确：https://akshare.akfamily.xyz"},
                )
            temp_df = received_df.to_json(orient="records", date_format="iso")
        except KeyError as e:
            logger.info(
                f"请输入正确的参数错误 {e}，请升级 AKShare 到最新版本并在文档中确认该接口的使用方式：https://akshare.akfamily.xyz")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": f"请输入正确的参数错误 {e}，请升级 AKShare 到最新版本并在文档中确认该接口的使用方式：https://akshare.akfamily.xyz"
                },
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            logger.error(f"接口 {item_id} 重试 {RETRY_MAX_ATTEMPTS} 次后仍失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"上游数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次，请稍后重试"
                },
            )
        except Exception as e:
            logger.error(f"接口 {item_id} 调用失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"数据接口调用异常: {e}，可能是上游数据源暂时不可用，请稍后重试"
                },
            )
        logger.info(f"获取到 {item_id} 的数据")
        return JSONResponse(status_code=status.HTTP_200_OK, content=json.loads(temp_df))
    else:
        try:
            received_df = _call_akshare(item_id, eval_str)
            if received_df is None:
                logger.info("该接口返回数据为空，请确认参数是否正确：https://akshare.akfamily.xyz")
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"error": "该接口返回数据为空，请确认参数是否正确：https://akshare.akfamily.xyz"},
                )
            temp_df = received_df.to_json(orient="records", date_format="iso")
        except KeyError as e:
            logger.info(
                f"请输入正确的参数错误 {e}，请升级 AKShare 到最新版本并在文档中确认该接口的使用方式：https://akshare.akfamily.xyz")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": f"请输入正确的参数错误 {e}，请升级 AKShare 到最新版本并在文档中确认该接口的使用方式：https://akshare.akfamily.xyz"
                },
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            logger.error(f"接口 {item_id} 重试 {RETRY_MAX_ATTEMPTS} 次后仍失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"上游数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次，请稍后重试"
                },
            )
        except Exception as e:
            logger.error(f"接口 {item_id} 调用失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"数据接口调用异常: {e}，可能是上游数据源暂时不可用，请稍后重试"
                },
            )
        logger.info(f"获取到 {item_id} 的数据")
        return JSONResponse(status_code=status.HTTP_200_OK, content=json.loads(temp_df))


def generate_html_response():
    file_path = get_pyscript_html(file="akscript.html")
    with open(file_path, encoding="utf8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)


short_path = get_template_path()
templates = Jinja2Templates(directory=short_path)


@app_core.get(
    path="/show-temp/{interface}",
    response_class=HTMLResponse,
    description="展示 PyScript",
    summary="该接口主要展示 PyScript 游览器运行 Python 代码",
)
def akscript_temp(request: Request, interface: str):
    return templates.TemplateResponse(
        "akscript.html",
        context={
            "request": request,
            "ip": request.headers["host"],
            "interface": interface,
        },
    )


@app_core.get(
    path="/show",
    response_class=HTMLResponse,
    description="展示 PyScript",
    summary="该接口主要展示 PyScript 游览器运行 Python 代码",
)
def akscript():
    return generate_html_response()
