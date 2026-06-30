# -*- coding:utf-8 -*-
# /usr/bin/env python
"""
Date: 2024/1/12 22:05
Desc: HTTP 模式主文件
"""
import inspect as _inspect
import json
import logging

import orjson
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
from fastapi.responses import JSONResponse, HTMLResponse, Response
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


def _df_to_json_bytes(df):
    """Serialize a DataFrame to JSON bytes via orjson (single-pass, compact).

    Replaces the double-serialization dance of
        df.to_json(orient=\"records\") → json.loads() → JSONResponse.
    Uses orjson with numpy support + default=str fallback for NaT/null values.
    """
    records = df.to_dict(orient="records")
    return orjson.dumps(
        records, default=str, option=orjson.OPT_SERIALIZE_NUMPY
    )


DEFAULT_SOURCE = os.getenv("AKSHARE_DEFAULT_SOURCE", "auto")  # mutable — changed by /api/v1/default_source

_INTRADAY_SOURCE_MAP = {
    "eastmoney": {"func": ak.stock_zh_a_hist_min_em, "prefixed": False},
    "sina": {"func": ak.stock_zh_a_minute, "prefixed": True},
}

_SOURCE_MAP = {
    "eastmoney": {"func": ak.stock_zh_a_hist, "prefixed": False},
    "sina": {"func": ak.stock_zh_a_daily, "prefixed": True},
    "tencent": {"func": ak.stock_zh_a_hist_tx, "prefixed": True},
}

# ── A 股历史行情列名归一化 ──────────────────────────────────────
# 各数据源返回的 DataFrame 列名和单位不同，归一化为统一的英文 schema，
# 确保 API 无论使用哪个 source 都返回相同的 JSON 结构。
#
# 统一 schema（6 字段，零 null）：
#   date, open, high, low, close, volume
#
# 成交量单位统一为 股（shares）。Eastmoney 和 Tencent 原始单位为 手（lot=100 股），
# 归一化时乘以 100。
#
# 注意：Tencent 原始列名 `amount` 实际是成交量（手），非成交额。
#
# 每条映射: (统一字段名, 原始列名, 转换函数或None)


_HIST_NORMALIZE_MAP = {
    "eastmoney": [
        ("date",   "日期",   None),
        ("open",   "开盘",   None),
        ("high",   "最高",   None),
        ("low",    "最低",   None),
        ("close",  "收盘",   None),
        ("volume", "成交量", lambda s: s * 100),  # 手 → 股
    ],
    "sina": [
        ("date",   "date",   None),
        ("open",   "open",   None),
        ("high",   "high",   None),
        ("low",    "low",    None),
        ("close",  "close",  None),
        ("volume", "volume", None),
    ],
    "tencent": [
        ("date",   "date",   None),
        ("open",   "open",   None),
        ("high",   "high",   None),
        ("low",    "low",    None),
        ("close",  "close",  None),
        ("volume", "amount", lambda s: s * 100),  # amount 列实际为成交量（手）→ 股
    ],
}


# ── 其他端点的归一化映射 ───────────────────────────────────────
# 这些端点与 stock_cn_hist 共享相同的 6 字段核心 schema（date/open/high/low/close/volume），
# 但使用不同的数据源函数（不同的列名语言）。

_INTRADAY_NORMALIZE_MAP = {
    "eastmoney": [
        ("time", "时间", None),
        ("open", "开盘", None),
        ("high", "最高", None),
        ("low", "最低", None),
        ("close", "收盘", None),
        ("volume", "成交量", None),
    ],
    "sina": [
        ("time", "day", None),
        ("open", "open", None),
        ("high", "high", None),
        ("low", "low", None),
        ("close", "close", None),
        ("volume", "volume", None),
    ],
}

_FUND_ETF_HIST_NORMALIZE_MAP = {
    "eastmoney": [
        ("date", "日期", None),
        ("open", "开盘", None),
        ("high", "最高", None),
        ("low", "最低", None),
        ("close", "收盘", None),
        ("volume", "成交量", None),
    ],
    "sina": [
        ("date", "date", None),
        ("open", "open", None),
        ("high", "high", None),
        ("low", "low", None),
        ("close", "close", None),
        ("volume", "volume", None),
    ],
}

_US_HIST_NORMALIZE_MAP = {
    "eastmoney": [
        ("date", "日期", None),
        ("open", "开盘", None),
        ("high", "最高", None),
        ("low", "最低", None),
        ("close", "收盘", None),
        ("volume", "成交量", None),
    ],
    "sina": [
        ("date", "date", None),
        ("open", "open", None),
        ("high", "high", None),
        ("low", "low", None),
        ("close", "close", None),
        ("volume", "volume", None),
    ],
}

_HK_HIST_NORMALIZE_MAP = {
    "eastmoney": [
        ("date", "日期", None),
        ("open", "开盘", None),
        ("high", "最高", None),
        ("low", "最低", None),
        ("close", "收盘", None),
        ("volume", "成交量", None),
    ],
    "sina": [
        ("date", "date", None),
        ("open", "open", None),
        ("high", "high", None),
        ("low", "low", None),
        ("close", "close", None),
        ("volume", "volume", None),
    ],
}


def _normalize_df(df: "pd.DataFrame", source: str,
                  mapping: dict = None) -> "pd.DataFrame":
    """将数据源的原始 DataFrame 归一化为统一 schema。

    Args:
        df: 原始 DataFrame。
        source: 数据源名称。
        mapping: {source: [(unified_name, source_name, transform), ...]}。
                 默认使用 _HIST_NORMALIZE_MAP。
    """
    import pandas as pd

    if mapping is None:
        mapping = _HIST_NORMALIZE_MAP

    col_map = mapping.get(source)
    if col_map is None:
        return df  # 未知数据源直接透传

    result = pd.DataFrame()
    for unified_name, source_name, transform in col_map:
        if source_name in df.columns:
            series = df[source_name]
            if transform is not None:
                series = transform(series)
            result[unified_name] = series
        else:
            result[unified_name] = None

    result.index = df.index
    return result


def _normalize_stock_hist(df: "pd.DataFrame", source: str) -> "pd.DataFrame":
    """stock_cn_hist 专用归一化（向后兼容）。"""
    return _normalize_df(df, source, _HIST_NORMALIZE_MAP)


# ── 实时行情归一化映射（中文 → 英文） ─────────────────────────

_CN_SPOT_NORMALIZE_MAP = {
    "eastmoney": [
        ("code", "代码", None),
        ("name", "名称", None),
        ("latest", "最新价", None),
        ("change_pct", "涨跌幅", None),
        ("change_amt", "涨跌额", None),
        ("volume", "成交量", None),
        ("amount", "成交额", None),
        ("prev_close", "昨收", None),
        ("open", "今开", None),
        ("high", "最高", None),
        ("low", "最低", None),
    ],
    "sina": [
        ("code", "代码", None),
        ("name", "名称", None),
        ("latest", "最新价", None),
        ("change_pct", "涨跌幅", None),
        ("change_amt", "涨跌额", None),
        ("volume", "成交量", None),
        ("amount", "成交额", None),
        ("prev_close", "昨收", None),
        ("open", "今开", None),
        ("high", "最高", None),
        ("low", "最低", None),
    ],
}

_HK_SPOT_NORMALIZE_MAP = {
    "eastmoney": [
        ("code", "代码", None),
        ("latest", "最新价", None),
        ("change_amt", "涨跌额", None),
        ("change_pct", "涨跌幅", None),
        ("prev_close", "昨收", None),
        ("open", "今开", None),
        ("high", "最高", None),
        ("low", "最低", None),
        ("volume", "成交量", None),
        ("amount", "成交额", None),
    ],
    "sina": [
        ("code", "代码", None),
        ("latest", "最新价", None),
        ("change_amt", "涨跌额", None),
        ("change_pct", "涨跌幅", None),
        ("prev_close", "昨收", None),
        ("open", "今开", None),
        ("high", "最高", None),
        ("low", "最低", None),
        ("volume", "成交量", None),
        ("amount", "成交额", None),
    ],
}


def _normalize_records(records: list, source: str, mapping: dict) -> list:
    """将原始 records（list of dict）的键从源列名映射为统一英文名。

    Args:
        records: [{源列名: value, ...}, ...]
        source: 数据源名称。
        mapping: {source: [(unified_name, source_name, transform), ...]}。

    Returns:
        新 records 列表，键已重命名为统一英文名。未映射的列被丢弃。
    """
    col_map = mapping.get(source)
    if col_map is None:
        return records  # 未知源透传

    rename = {}
    transforms = {}
    for unified_name, source_name, transform in col_map:
        rename[source_name] = unified_name
        if transform is not None:
            transforms[unified_name] = transform

    result = []
    for row in records:
        new_row = {}
        for src_key, val in row.items():
            if src_key in rename:
                key = rename[src_key]
                if key in transforms:
                    val = transforms[key](val)
                new_row[key] = val
        result.append(new_row)
    return result


# ── 自动数据源选择 + 熔断器（按类别隔离） ─────────────────────
# 当 DEFAULT_SOURCE=auto 或 source=auto 时，按优先级尝试数据源。
# 连续失败 CIRCUIT_BREAKER_THRESHOLD 次后进入熔断冷却期（秒），
# 冷却期内 auto 模式跳过该源，避免无谓的超时等待。
#
# 每个端点类别有独立的优先级链和独立的熔断状态，
# 类别键如 "cn_hist", "cn_intraday", "fund_etf_hist", "us_hist", "hk_hist"。

_AUTO_SOURCE_PRIORITY = {
    "cn_hist": ["eastmoney", "tencent", "sina"],
    "cn_intraday": ["eastmoney", "sina"],
    "fund_etf_hist": ["eastmoney", "sina"],
    "us_hist": ["eastmoney", "sina"],
    "hk_hist": ["eastmoney", "sina"],
}

CIRCUIT_BREAKER_THRESHOLD = 2
CIRCUIT_BREAKER_COOLDOWN = 60

_source_health = {}  # key: "category:source"
_source_health_lock = threading.Lock()


def _health_key(category: str, src: str) -> str:
    return f"{category}:{src}"


def _ensure_health(category: str, src: str) -> dict:
    """Get-or-create health entry for a category:source pair."""
    key = _health_key(category, src)
    with _source_health_lock:
        if key not in _source_health:
            _source_health[key] = {"failures": 0, "cooldown_until": 0}
        return _source_health[key]


def _source_in_cooldown(category: str, src: str) -> bool:
    """检查数据源是否处于熔断冷却期。"""
    key = _health_key(category, src)
    with _source_health_lock:
        h = _source_health.get(key)
        if h and h["cooldown_until"] > time.time():
            return True
    return False


def _record_source_success(category: str, src: str) -> None:
    """记录数据源调用成功，重置失败计数器。"""
    h = _ensure_health(category, src)
    with _source_health_lock:
        h["failures"] = 0


def _record_source_failure(category: str, src: str) -> None:
    """记录数据源调用失败，达到阈值后进入熔断冷却。"""
    h = _ensure_health(category, src)
    with _source_health_lock:
        h["failures"] += 1
        if h["failures"] >= CIRCUIT_BREAKER_THRESHOLD:
            h["cooldown_until"] = time.time() + CIRCUIT_BREAKER_COOLDOWN
            logger.warning(
                f"数据源 {category}:{src} 连续失败 {h['failures']} 次，"
                f"进入熔断冷却 {CIRCUIT_BREAKER_COOLDOWN}s"
            )


class AutoSourceExhaustedError(Exception):
    """All sources in the priority chain have been exhausted."""

    def __init__(self, sources_tried: list, last_error: Exception = None):
        self.sources_tried = sources_tried
        self.last_error = last_error
        super().__init__(
            f"auto: 所有数据源不可用，已尝试 {sources_tried}"
        )


class EmptyDataError(Exception):
    """A source returned empty data — not a failure, just no data for this query.

    Distinguished from real failures (network errors, timeouts) so the
    circuit breaker doesn't penalize sources that are working but have
    no data for a particular symbol / date range.
    """


def _try_auto_sources(category: str, try_source: "callable"):
    """Try sources in priority order with circuit breaker.

    Args:
        category: key into _AUTO_SOURCE_PRIORITY dict.
        try_source: callable(src) -> DataFrame. Must raise on failure.
                    Raise EmptyDataError if the source works but returns
                    no data — this skips the source without recording a
                    circuit-breaker failure.

    Returns:
        (DataFrame, actual_source_name)

    Raises:
        AutoSourceExhaustedError if all sources fail.
    """
    priority = _AUTO_SOURCE_PRIORITY.get(category, [])
    sources_tried = []
    last_error = None

    # Phase 1: try non-cooldown sources in priority order
    for src in priority:
        if _source_in_cooldown(category, src):
            logger.info(f"auto({category}): 跳过 {src}（熔断冷却中）")
            continue

        logger.info(f"auto({category}): 尝试 {src}")
        try:
            df = try_source(src)
            _record_source_success(category, src)
            logger.info(f"auto({category}): 选中数据源 {src}")
            return df, src
        except EmptyDataError:
            logger.info(f"auto({category}): {src} 返回空数据，尝试下一个")
            sources_tried.append(src)
            # NOT a circuit-breaker failure — source is working, just no data
        except Exception as e:
            logger.warning(f"auto({category}): {src} 失败: {e}")
            _record_source_failure(category, src)
            sources_tried.append(src)
            last_error = e

    # Phase 2: last resort — retry sources that were in cooldown
    for src in priority:
        if src in sources_tried:
            continue
        logger.info(f"auto({category}): 所有源失败，尝试冷却中的 {src}")
        try:
            df = try_source(src)
            _record_source_success(category, src)
            logger.info(f"auto({category}): 冷却源 {src} 恢复，选中")
            return df, src
        except EmptyDataError:
            sources_tried.append(src)
        except Exception as e:
            sources_tried.append(src)
            last_error = e

    raise AutoSourceExhaustedError(sources_tried, last_error)


# 实时行情数据源（函数无参数，返回全市场数据）
_SPOT_SOURCE_MAP = {
    "eastmoney": ak.stock_zh_a_spot_em,
    "sina": ak.stock_zh_a_spot,
}

# 其他慢速无参接口（股票列表等），与实时行情共用缓存线程
# ETF 实时行情数据源
_FUND_SPOT_SOURCE_MAP = {
    "eastmoney": ak.fund_etf_spot_em,
    "lof": ak.fund_lof_spot_em,
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

# HK 股票数据源
_HK_SPOT_SOURCE_MAP = {
    "eastmoney": ak.stock_hk_spot_em,
    "sina": ak.stock_hk_spot,
}
_HK_HIST_SOURCE_MAP = {
    "eastmoney": {"func": ak.stock_hk_hist, "prefixed": False},
    "sina": {"func": ak.stock_hk_daily, "prefixed": False},
}

# 期货数据源
_FUTURES_SPOT_SOURCE_MAP = {"eastmoney": ak.futures_global_spot_em}

# 指数数据源
_INDEX_SPOT_SOURCE_MAP = {"eastmoney": ak.index_global_spot_em}
_INDEX_HIST_SOURCE_MAP = {
    "eastmoney": {"func": ak.index_global_hist_em, "prefixed": False},
    "sina": {"func": ak.index_global_hist_sina, "prefixed": False},
}

# 可转债数据源
_BOND_COV_SPOT_SOURCE_MAP = {"sina": ak.bond_zh_hs_cov_spot}
_BOND_COV_HIST_SOURCE_MAP = {"sina": {"func": ak.bond_zh_hs_cov_daily, "prefixed": False}}

_STATIC_CACHE_MAP = {
    "stock_cn_list": ak.stock_info_a_code_name,
    "fund_list": ak.fund_name_em,
    "fund_open_list": ak.fund_open_fund_daily_em,
    "stock_us_list": ak.get_us_stock_name,
    "stock_hk_list": ak.stock_hk_ggt_components_em,
    "index_list": ak.index_global_name_table,
    "bond_cov_list": ak.bond_zh_cov,
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
_CACHE_TTL_OFF = 3600                 # 非交易时段刷新间隔（秒，盘后数据不变）

# ── 缓存控制：静态 + 动态开关 ────────────────────────────────
_SPOT_DISABLED = os.getenv("AKTOOLS_DISABLE_SPOT", "").strip() in ("1", "true", "yes")
_SPOT_ADAPTIVE = os.getenv("AKTOOLS_SPOT_ADAPTIVE", "1").strip() in ("1", "true", "yes")
# 自适应阈值（秒）
_SPOT_ADAPTIVE_WARM_S = int(os.getenv("AKTOOLS_CACHE_WARM_S", "300"))   # 5 min
_SPOT_ADAPTIVE_COLD_S = int(os.getenv("AKTOOLS_CACHE_COLD_S", "1800"))  # 30 min
# 自适应间隔（周期数）
_SPOT_INTERVAL_WARM = 1
_SPOT_INTERVAL_SLOW = 10
_SPOT_INTERVAL_COLD = max(1, _SPOT_ADAPTIVE_COLD_S // _CACHE_TTL)
# 访问追踪 + 每缓存间隔
_cache_access = {}        # {key: last_access_ts}
_cache_interval = {}      # {key: refresh_every_n_cycles}
_cache_interval_lock = threading.Lock()

def _record_cache_access(key: str) -> None:
    """Record that a cache key was accessed by a client."""
    with _cache_interval_lock:
        _cache_access[key] = time.time()
        _cache_interval[key] = _SPOT_INTERVAL_WARM  # bump to warm

def _spot_cache_should_refresh(key: str, cycle: int) -> bool:
    """Check whether a spot cache should refresh this cycle (adaptive)."""
    if not _SPOT_ADAPTIVE:
        return True  # fixed interval — always refresh
    with _cache_interval_lock:
        interval = _cache_interval.get(key, _SPOT_INTERVAL_WARM)
    return (cycle % interval) == 0

def _spot_cache_update_interval(key: str) -> None:
    """Update a cache key's interval based on time since last access."""
    if not _SPOT_ADAPTIVE:
        return
    now = time.time()
    with _cache_interval_lock:
        last_access = _cache_access.get(key, 0)
        if last_access == 0:
            return  # never accessed — keep current interval
        elapsed = now - last_access
        if elapsed < _SPOT_ADAPTIVE_WARM_S:
            _cache_interval[key] = _SPOT_INTERVAL_WARM
        elif elapsed < _SPOT_ADAPTIVE_COLD_S:
            _cache_interval[key] = _SPOT_INTERVAL_SLOW
        else:
            _cache_interval[key] = _SPOT_INTERVAL_COLD

# ── 缓存持久化到 SQLite ──────────────────────────────────────
import sqlite3 as _sqlite3
_CACHE_DB = os.path.join(_DATA_DIR, "cache.db")


def _sanitize_records(records: list) -> list:
    """Convert non-JSON-serializable types (Timestamp, date, etc.) in records.

    df.to_dict(orient="records") can produce pandas Timestamp / NaT objects
    that json.dumps rejects.  Run this before caching or returning records.
    """
    import pandas as _pd
    for row in records:
        for k, v in list(row.items()):
            if isinstance(v, (_pd.Timestamp,)):
                row[k] = v.isoformat()
            elif hasattr(v, "isoformat"):
                row[k] = v.isoformat()
    return records


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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache_metadata "
                "(key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute("BEGIN IMMEDIATE")
            for key, entry in _spot_cache.items():
                # Use orjson to handle numpy types (int64, float64, NaN)
                # that json.dumps would reject with TypeError
                data_json = orjson.dumps(
                    entry["data"],
                    default=str,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ).decode("utf-8")
                conn.execute(
                    "INSERT OR REPLACE INTO persisted_cache VALUES (?, ?, ?)",
                    (key, data_json, entry["ts"]),
                )
            # Persist metadata for restart-aware scheduling
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO cache_metadata VALUES (?, ?)",
                ("last_persist", now_iso),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"缓存持久化失败 (cache.db 写入错误): {e}")


def _load_cache_from_db():
    """Restore cache from SQLite on startup.
    
    Returns (restored: bool, last_persist_ts: float | None).
    last_persist_ts is the UTC timestamp of the most recent persist.
    """
    _log = logging.getLogger("AKToolsLog")
    if not os.path.exists(_CACHE_DB):
        _log.info(f"cache.db 不存在 ({_CACHE_DB})，跳过恢复")
        return False, None
    try:
        conn = _sqlite3.connect(_CACHE_DB)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS persisted_cache "
            "(key TEXT PRIMARY KEY, data TEXT, ts REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cache_metadata "
            "(key TEXT PRIMARY KEY, value TEXT)"
        )
        rows = conn.execute("SELECT key, data, ts FROM persisted_cache").fetchall()
        # Read metadata
        meta_row = conn.execute(
            "SELECT value FROM cache_metadata WHERE key = 'last_persist'"
        ).fetchone()
        last_persist_ts = None
        if meta_row:
            try:
                last_persist_dt = datetime.fromisoformat(meta_row[0])
                last_persist_ts = last_persist_dt.timestamp()
            except (ValueError, TypeError):
                pass
        conn.close()
        if rows:
            # 迁移旧 cache key → 新命名（stock_list → stock_cn_list 等）
            _key_map = {
                "stock_list": "stock_cn_list",
                "stock_spot_eastmoney": "stock_cn_spot_eastmoney",
                "stock_spot_sina": "stock_cn_spot_sina",
            }
            with _spot_cache_lock:
                for key, data_json, ts in rows:
                    target_key = _key_map.get(key, key)
                    _spot_cache[target_key] = {"data": json.loads(data_json), "ts": ts}
            _log.info(f"从 cache.db 恢复了 {len(rows)} 个缓存项")
            return True, last_persist_ts
        else:
            _log.info("cache.db 存在但无缓存项")
            return False, None
    except Exception as e:
        _log.warning(f"从 cache.db 恢复失败: {e}")
        return False, None

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

    # 如果从 cache.db 恢复了数据，估算已过去的周期数，避免不必要的静态刷新
    _next_static_cycle = 0  # 冷启动：立即运行静态刷新
    if _last_persist_ts is not None:
        _elapsed = time.time() - _last_persist_ts
        _estimated_cycles = int(_elapsed / _CACHE_TTL)
        if _estimated_cycles > 0:
            cycle = _estimated_cycles
            logger.info(
                f"恢复周期计数: 距上次持久化 {_elapsed:.0f}s，"
                f"估算已过 {_estimated_cycles} 个周期"
            )
        # 计算下一次静态刷新应发生的周期
        _next_static_cycle = cycle + max(1, _static_interval - (cycle % _static_interval))
        if _elapsed < _STATIC_CACHE_TTL:
            # 静态数据仍新鲜，跳过本次，等待下一个 _static_interval 边界
            _next_static_cycle = cycle + _static_interval - (cycle % _static_interval)
            if _next_static_cycle == cycle:
                _next_static_cycle += _static_interval
            logger.info(
                f"上次静态刷新距今 {_elapsed:.0f}s（< {_STATIC_CACHE_TTL}s），"
                f"延至周期 {_next_static_cycle}"
            )

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
        # 刷新实时行情（每周期）
        # 休市时段跳过 — 数据不会变化，最后一次盘中刷新已捕获收盘价
        _do_spot = not _SPOT_DISABLED and market_open
        if _SPOT_DISABLED:
            logger.debug("实时行情已禁用 (AKTOOLS_DISABLE_SPOT=1)，跳过刷新")
        elif not market_open:
            logger.debug("休市时段，跳过实时行情刷新")
        # 更新自适应间隔（始终运行，让缓存冷却）
        for _spot_key in list(_SPOT_SOURCE_MAP.keys()):
            _spot_cache_update_interval("stock_cn_spot_" + _spot_key)

        # A 股
        if _do_spot:
            for source, func in _SPOT_SOURCE_MAP.items():
                if _SPOT_ADAPTIVE and not _spot_cache_should_refresh(
                    "stock_cn_spot_" + source, cycle
                ):
                    continue
                try:
                    logger.info(f"正在刷新: A股实时行情 ({source}) ...")
                    df = func()
                    if df is not None:
                        data = _sanitize_records(df.to_dict(orient="records"))
                        with _spot_cache_lock:
                            _spot_cache["stock_cn_spot_" + source] = {"data": data, "ts": time.time()}
                        logger.info(f"缓存已刷新: stock_spot_{source} ({len(data)} 条)")
                        succeeded += 1
                except Exception as e:
                    logger.warning(f"刷新缓存失败 [stock_spot_{source}]: {e}")
                    failed += 1
        # ETF / LOF
        if _do_spot:
            for source, func in _FUND_SPOT_SOURCE_MAP.items():
                cache_key = "fund_etf_spot" if source == "eastmoney" else "fund_lof_spot"
                if _SPOT_ADAPTIVE and not _spot_cache_should_refresh(cache_key, cycle):
                    continue
                try:
                    logger.info(f"正在刷新: {cache_key} ({source}) ...")
                    df = func()
                    if df is not None:
                        data = _sanitize_records(df.to_dict(orient="records"))
                        with _spot_cache_lock:
                            _spot_cache[cache_key] = {"data": data, "ts": time.time()}
                        logger.info(f"缓存已刷新: {cache_key} ({len(data)} 条)")
                        succeeded += 1
                except Exception as e:
                    logger.warning(f"刷新缓存失败 [{cache_key}]: {e}")
                    failed += 1
        # US
        if _do_spot:
            for source, func in _US_SPOT_SOURCE_MAP.items():
                if _SPOT_ADAPTIVE and not _spot_cache_should_refresh("stock_us_spot", cycle):
                    continue
                try:
                    logger.info(f"正在刷新: 美股实时行情 ({source}) ...")
                    df = func()
                    if df is not None:
                        data = _sanitize_records(df.to_dict(orient="records"))
                        with _spot_cache_lock:
                            _spot_cache["stock_us_spot"] = {"data": data, "ts": time.time()}
                        logger.info(f"缓存已刷新: stock_us_spot ({len(data)} 条)")
                        succeeded += 1
                except Exception as e:
                    logger.warning(f"刷新缓存失败 [stock_us_spot]: {e}")
                    failed += 1
        # HK
        if _do_spot:
            for source, func in _HK_SPOT_SOURCE_MAP.items():
                _hk_key = "stock_hk_spot_" + source
                if _SPOT_ADAPTIVE and not _spot_cache_should_refresh(_hk_key, cycle):
                    continue
                try:
                    logger.info(f"正在刷新: 港股实时行情 ({source}) ...")
                    df = func()
                    if df is not None:
                        data = _sanitize_records(df.to_dict(orient="records"))
                        with _spot_cache_lock:
                            _spot_cache[_hk_key] = {"data": data, "ts": time.time()}
                        logger.info(f"缓存已刷新: {_hk_key} ({len(data)} 条)")
                        succeeded += 1
                except Exception as e:
                    logger.warning(f"刷新缓存失败 [{_hk_key}]: {e}")
                    failed += 1
        # 期货 / 指数 / 可转债
        if _do_spot:
            for source, func in _FUTURES_SPOT_SOURCE_MAP.items():
                if _SPOT_ADAPTIVE and not _spot_cache_should_refresh("futures_spot", cycle):
                    continue
                try:
                    logger.info(f"正在刷新: 期货实时行情 ({source}) ...")
                    df = func()
                    if df is not None:
                        data = _sanitize_records(df.to_dict(orient="records"))
                        with _spot_cache_lock:
                            _spot_cache["futures_spot"] = {"data": data, "ts": time.time()}
                        logger.info(f"缓存已刷新: futures_spot ({len(data)} 条)")
                        succeeded += 1
                except Exception as e:
                    logger.warning(f"刷新缓存失败 [futures_spot]: {e}")
                    failed += 1
        if _do_spot:
            for source, func in _INDEX_SPOT_SOURCE_MAP.items():
                if _SPOT_ADAPTIVE and not _spot_cache_should_refresh("index_spot", cycle):
                    continue
                try:
                    logger.info(f"正在刷新: 指数实时行情 ({source}) ...")
                    df = func()
                    if df is not None:
                        data = _sanitize_records(df.to_dict(orient="records"))
                        with _spot_cache_lock:
                            _spot_cache["index_spot"] = {"data": data, "ts": time.time()}
                        logger.info(f"缓存已刷新: index_spot ({len(data)} 条)")
                        succeeded += 1
                except Exception as e:
                    logger.warning(f"刷新缓存失败 [index_spot]: {e}")
                    failed += 1
        if _do_spot:
            for source, func in _BOND_COV_SPOT_SOURCE_MAP.items():
                if _SPOT_ADAPTIVE and not _spot_cache_should_refresh("bond_cov_spot", cycle):
                    continue
                try:
                    logger.info(f"正在刷新: 可转债实时行情 ({source}) ...")
                    df = func()
                    if df is not None:
                        data = _sanitize_records(df.to_dict(orient="records"))
                        with _spot_cache_lock:
                            _spot_cache["bond_cov_spot"] = {"data": data, "ts": time.time()}
                        logger.info(f"缓存已刷新: bond_cov_spot ({len(data)} 条)")
                        succeeded += 1
                except Exception as e:
                    logger.warning(f"刷新缓存失败 [bond_cov_spot]: {e}")
                    failed += 1

        # 持久化实时行情（不等慢速静态数据 — 避免 _build_stock_profile 阻塞）
        _persist_cache_to_db()

        # 静态数据按计划刷新（恢复时跳过新鲜数据，减少 API 调用）
        if cycle >= _next_static_cycle:
            for key, func in _STATIC_CACHE_MAP.items():
                try:
                    logger.info(f"正在刷新: 静态数据 {key} ...")
                    if func is None and key == "stock_profile":
                        # 持久化已刷新的列表缓存（在慢速 _build_stock_profile 之前）
                        _persist_cache_to_db()
                        data = _build_stock_profile()
                    else:
                        df = func()
                        if df is not None:
                            data = _sanitize_records(df.to_dict(orient="records"))
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
            _next_static_cycle = cycle + _static_interval
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

# ── 启动横幅（分隔不同进程的日志） ────────────────────────────
logger.info("=" * 60)
logger.info(f" AKTools 启动 — {datetime.now(timezone.utc).isoformat()}")
logger.info(f" 数据目录: {_DATA_DIR}")
logger.info(f" 默认数据源: {DEFAULT_SOURCE}")
logger.info(f" 日志级别: {_LOG_LEVEL}")
logger.info(f" 实时行情: {'禁用' if _SPOT_DISABLED else ('自适应刷新' if _SPOT_ADAPTIVE else '固定间隔')}")
logger.info("=" * 60)

# 启动时从 SQLite 恢复缓存（若有），避免冷启动等待
_restored, _last_persist_ts = _load_cache_from_db()
if _restored:
    _spot_cache_warm.set()  # 恢复后可立即服务
    if _last_persist_ts:
        _elapsed = time.time() - _last_persist_ts
        logger.info(
            f"缓存已从磁盘恢复，预热完成 "
            f"(上次持久化: {_elapsed:.0f}s 前)"
        )
    else:
        logger.info("缓存已从磁盘恢复，预热完成")
else:
    _last_persist_ts = None  # 无历史持久化

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
    """Call an AKShare function directly with retry.
    Filters kwargs to only parameters the function actually accepts,
    so source-dependent params (e.g. start_date for sina) are silently dropped.
    """
    _accepted = set(_inspect.signature(func).parameters.keys())
    if _accepted:
        kwargs = {k: v for k, v in kwargs.items() if k in _accepted}
    # Build a concise context string from the most useful params
    _ctx_parts = [f"{func.__name__}"]
    for _key in ("symbol", "start_date", "end_date", "period", "indicator"):
        if _key in kwargs:
            _ctx_parts.append(f"{_key}={kwargs[_key]}")
    logger.info(f"正在获取数据: {' '.join(_ctx_parts)} ...")
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
        return Response(content=_df_to_json_bytes(received_df), media_type="application/json")
    else:
        try:
            received_df = _call_akshare(item_id, eval_str)
            if received_df is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"error": "该接口返回数据为空，请确认参数是否正确：https://akshare.akfamily.xyz"},
                )
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
        return Response(content=_df_to_json_bytes(received_df), media_type="application/json")


@app_core.get(
    path="/public/v1/stock_cn_hist",
    description="A 股历史行情接口 (v1)",
    summary="支持切换数据源（eastmoney/sina/tencent），方便海外用户访问",
)
def stock_cn_hist(
    request: Request,
    symbol: str = Query(..., description="股票代码，如 600000 或 sh600000"),
    source: str = Query(
        "", description=f"数据源，可选 eastmoney/sina/tencent/auto，默认 {DEFAULT_SOURCE}"
    ),
    start_date: str = Query("19900101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("20500101", description="结束日期 YYYYMMDD"),
    adjust: str = Query("", description="复权类型: 空=不复权, qfq=前复权, hfq=后复权"),
):
    source = source or DEFAULT_SOURCE

    # ── 显式数据源 ──────────────────────────────────────────
    if source != "auto":
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
            received_df = _normalize_stock_hist(received_df, source)
        except (RequestsConnectionError, RequestsTimeout) as e:
            logger.error(f"统一接口 {source} 重试 {RETRY_MAX_ATTEMPTS} 次后仍失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"{source} 数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次，请稍后重试或切换数据源"
                },
            )
        except Exception as e:
            logger.warning(f"统一接口 {source} 查询失败 ({symbol}): {e}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到数据: {symbol}（{source}）"},
            )

        return Response(
            content=_df_to_json_bytes(received_df),
            media_type="application/json",
            headers={"X-Market-Source": source},
        )

    # ── auto 模式：按优先级尝试数据源 ────────────────────────
    def _try_cn_hist_source(src: str):
        source_config = _SOURCE_MAP[src]
        normalized = _normalize_symbol(symbol, source_config["prefixed"])
        logger.info(f"auto: 尝试 {src}，symbol={symbol} → {normalized}")
        received_df = _call_akshare_direct(
            source_config["func"],
            symbol=normalized,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        if received_df is None:
            raise EmptyDataError(f"{src} 返回空数据")
        return _normalize_stock_hist(received_df, src)

    try:
        received_df, actual_source = _try_auto_sources(
            "cn_hist", _try_cn_hist_source
        )
        return Response(
            content=_df_to_json_bytes(received_df),
            media_type="application/json",
            headers={"X-Market-Source": actual_source},
        )
    except AutoSourceExhaustedError as e:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"auto: 所有数据源不可用，已尝试 {e.sources_tried}，"
                f"最后错误: {e.last_error}"
            },
        )


@app_core.get(
    path="/public/v1/stock_cn_hist_intraday",
    description="A 股分时行情接口 (v1)",
    summary="支持切换数据源（eastmoney/sina/auto），返回分钟级 K 线",
)
def stock_cn_hist_intraday(
    request: Request,
    symbol: str = Query(..., description="股票代码，如 000001 或 sh600519"),
    source: str = Query(
        "", description=f"数据源：eastmoney/sina/auto（默认 {DEFAULT_SOURCE}）"
    ),
    period: str = Query("5", description="分时周期: 1, 5, 15, 30, 60"),
    start_date: str = Query("1979-09-01 09:32:00", description="开始时间 YYYY-MM-DD HH:MM:SS"),
    end_date: str = Query("2222-01-01 09:32:00", description="结束时间"),
    adjust: str = Query("", description="复权: 空=不复权, qfq=前复权, hfq=后复权"),
):
    source = source or DEFAULT_SOURCE

    def _try_intraday(src: str) -> "pd.DataFrame":
        sc = _INTRADAY_SOURCE_MAP[src]
        s = _normalize_symbol(symbol, sc["prefixed"])
        kwargs = {"symbol": s, "period": period, "adjust": adjust}
        if src == "eastmoney":
            kwargs["start_date"] = start_date
            kwargs["end_date"] = end_date
        df = _call_akshare_direct(sc["func"], **kwargs)
        if df is None:
            raise EmptyDataError(f"{src} 返回空数据")
        return _normalize_df(df, src, _INTRADAY_NORMALIZE_MAP)

    # ── 显式数据源 ──────────────────────────────────────────
    if source != "auto":
        if source not in _INTRADAY_SOURCE_MAP:
            valid = ", ".join(_INTRADAY_SOURCE_MAP)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": f"不支持的数据源: {source}，可选: {valid}"},
            )
        try:
            received_df = _try_intraday(source)
        except EmptyDataError:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "该接口返回数据为空，请确认参数是否正确"},
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"error": f"{source} 连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"},
            )
        except Exception as e:
            logger.warning(f"分时行情 {source} 查询失败 ({symbol}): {e}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到数据: {symbol}（{source}）"},
            )
        return Response(
            content=_df_to_json_bytes(received_df),
            media_type="application/json",
            headers={"X-Market-Source": source},
        )

    # ── auto 模式 ──────────────────────────────────────────
    try:
        received_df, actual_source = _try_auto_sources(
            "cn_intraday", _try_intraday
        )
        return Response(
            content=_df_to_json_bytes(received_df),
            media_type="application/json",
            headers={"X-Market-Source": actual_source},
        )
    except AutoSourceExhaustedError as e:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"auto: 所有数据源不可用，已尝试 {e.sources_tried}"
            },
        )


@app_core.get(
    path="/public/v1/stock_profile",
    description="个股行业/概念归属 (v1, 缓存)",
    summary="返回指定股票的行业与概念板块，数据来自后台缓存（每日刷新）",
)
def stock_profile(
    symbol: str = Query(..., description="股票代码，如 600000"),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("stock_profile")
    if entry is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "板块数据缓存未就绪，请稍后重试"},
        )
    code = symbol.strip()
    for row in entry["data"]:
        if row.get("code") == code:
            return JSONResponse(status_code=status.HTTP_200_OK, content=row)
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": f"未找到股票代码: {symbol}"},
    )


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
        if entry is not None:
            _record_cache_access(cache_key)
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
        cache_key_matched = next(
            s for s, e in _spot_cache.items() if e is fallback_entry
        )
        # 从缓存键提取源名（"stock_cn_spot_eastmoney" → "eastmoney"）
        source = cache_key_matched.replace("stock_cn_spot_", "")
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
            data = _sanitize_records(df.to_dict(orient="records"))
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

    data = _normalize_records(data, source, _CN_SPOT_NORMALIZE_MAP)
    stale_headers["X-Market-Source"] = source
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
    path="/public/v1/fund_etf_hist_intraday",
    description="ETF 分时行情 (v1)",
    summary="返回 ETF 分钟级 K 线（东方财富源）",
)
def fund_etf_hist_intraday(
    symbol: str = Query(..., description="ETF 代码，如 159707"),
    period: str = Query("5", description="分时周期: 1, 5, 15, 30, 60"),
    start_date: str = Query("1979-09-01 09:32:00"),
    end_date: str = Query("2222-01-01 09:32:00"),
    adjust: str = Query(""),
):
    try:
        df = _call_akshare_direct(
            ak.fund_etf_hist_min_em,
            symbol=symbol, period=period, start_date=start_date,
            end_date=end_date, adjust=adjust,
        )
        if df is None:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "数据为空"})
    except (RequestsConnectionError, RequestsTimeout) as e:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": f"连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"})
    except Exception as e:
        logger.warning(f"ETF 分时查询失败 ({symbol}): {e}")
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": f"未找到: {symbol}"})
    return Response(content=_df_to_json_bytes(df), media_type="application/json")


@app_core.get(
    path="/public/v1/fund_lof_hist_intraday",
    description="LOF 分时行情 (v1)",
    summary="返回 LOF 分钟级 K 线（东方财富源）",
)
def fund_lof_hist_intraday(
    symbol: str = Query(..., description="LOF 代码，如 166009"),
    period: str = Query("5", description="分时周期: 1, 5, 15, 30, 60"),
    start_date: str = Query("1979-09-01 09:32:00"),
    end_date: str = Query("2222-01-01 09:32:00"),
    adjust: str = Query(""),
):
    try:
        df = _call_akshare_direct(
            ak.fund_lof_hist_min_em,
            symbol=symbol, period=period, start_date=start_date,
            end_date=end_date, adjust=adjust,
        )
        if df is None:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "数据为空"})
    except (RequestsConnectionError, RequestsTimeout) as e:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": f"连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"})
    except Exception as e:
        logger.warning(f"LOF 分时查询失败 ({symbol}): {e}")
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": f"未找到: {symbol}"})
    return Response(content=_df_to_json_bytes(df), media_type="application/json")


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
            _record_cache_access(cache_key)

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
        "", description=f"数据源，可选 eastmoney/sina/auto，默认 {DEFAULT_SOURCE}"
    ),
    start_date: str = Query("19700101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("20500101", description="结束日期 YYYYMMDD"),
    adjust: str = Query("", description="复权类型: 空=不复权, qfq=前复权, hfq=后复权"),
):
    source = source or DEFAULT_SOURCE

    def _try_fund_etf_hist(src: str) -> "pd.DataFrame":
        sc = _FUND_ETF_HIST_SOURCE_MAP[src]
        s = _normalize_symbol(symbol, sc["prefixed"])
        df = _call_akshare_direct(
            sc["func"], symbol=s,
            start_date=start_date, end_date=end_date, adjust=adjust,
        )
        if df is None:
            raise EmptyDataError(f"{src} 返回空数据")
        return _normalize_df(df, src, _FUND_ETF_HIST_NORMALIZE_MAP)

    # ── 显式数据源 ──────────────────────────────────────────
    if source != "auto":
        if source not in _FUND_ETF_HIST_SOURCE_MAP:
            valid = ", ".join(_FUND_ETF_HIST_SOURCE_MAP)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": f"不支持的数据源: {source}，可选: {valid}"},
            )
        try:
            received_df = _try_fund_etf_hist(source)
        except EmptyDataError:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "该接口返回数据为空，请确认参数是否正确"},
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"error": f"{source} 连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"},
            )
        except Exception as e:
            logger.warning(f"ETF 历史 {source} 查询失败 ({symbol}): {e}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到数据: {symbol}（{source}）"},
            )
        return Response(
            content=_df_to_json_bytes(received_df),
            media_type="application/json",
            headers={"X-Market-Source": source},
        )

    # ── auto 模式 ──────────────────────────────────────────
    try:
        received_df, actual_source = _try_auto_sources(
            "fund_etf_hist", _try_fund_etf_hist
        )
        return Response(
            content=_df_to_json_bytes(received_df),
            media_type="application/json",
            headers={"X-Market-Source": actual_source},
        )
    except AutoSourceExhaustedError as e:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"auto: 所有数据源不可用，已尝试 {e.sources_tried}"
            },
        )


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
            _record_cache_access(cache_key)

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
        "", description=f"数据源，可选 eastmoney/sina/auto，默认 {DEFAULT_SOURCE}"
    ),
    start_date: str = Query("19700101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("22220101", description="结束日期 YYYYMMDD"),
    adjust: str = Query("", description="复权类型: 空=不复权, qfq=前复权, hfq=后复权"),
):
    source = source or DEFAULT_SOURCE

    def _try_us_hist(src: str) -> "pd.DataFrame":
        sc = _US_HIST_SOURCE_MAP[src]
        df = _call_akshare_direct(
            sc["func"], symbol=symbol,
            start_date=start_date, end_date=end_date, adjust=adjust,
        )
        if df is None:
            raise EmptyDataError(f"{src} 返回空数据")
        return _normalize_df(df, src, _US_HIST_NORMALIZE_MAP)

    # ── 显式数据源 ──────────────────────────────────────────
    if source != "auto":
        if source not in _US_HIST_SOURCE_MAP:
            valid = ", ".join(_US_HIST_SOURCE_MAP)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": f"不支持的数据源: {source}，可选: {valid}"},
            )
        try:
            received_df = _try_us_hist(source)
        except EmptyDataError:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "该接口返回数据为空，请确认参数是否正确"},
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"error": f"{source} 连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"},
            )
        except Exception as e:
            logger.warning(f"美股历史 {source} 查询失败 ({symbol}): {e}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到数据: {symbol}（{source}）"},
            )
        return Response(
            content=_df_to_json_bytes(received_df),
            media_type="application/json",
            headers={"X-Market-Source": source},
        )

    # ── auto 模式 ──────────────────────────────────────────
    try:
        received_df, actual_source = _try_auto_sources(
            "us_hist", _try_us_hist
        )
        return Response(
            content=_df_to_json_bytes(received_df),
            media_type="application/json",
            headers={"X-Market-Source": actual_source},
        )
    except AutoSourceExhaustedError as e:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"auto: 所有数据源不可用，已尝试 {e.sources_tried}"
            },
        )


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
    _intervals["fund_lof_spot"] = _CACHE_TTL
    for s in _HK_SPOT_SOURCE_MAP:
        _intervals["stock_hk_spot_" + s] = _CACHE_TTL
    _intervals["futures_spot"] = _CACHE_TTL
    _intervals["index_spot"] = _CACHE_TTL
    _intervals["bond_cov_spot"] = _CACHE_TTL
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
    # Add adaptive state and per-cache interval info
    _adaptive_info = {}
    with _cache_interval_lock:
        for key in result:
            interval = _cache_interval.get(key, _SPOT_INTERVAL_WARM)
            last_access = _cache_access.get(key, 0)
            _adaptive_info[key] = {
                "interval_cycles": interval,
                "last_access_age_s": int(now - last_access) if last_access else None,
                "tier": ("warm" if interval <= _SPOT_INTERVAL_WARM else
                         "slow" if interval <= _SPOT_INTERVAL_SLOW else "cold"),
            }
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "warm": _spot_cache_warm.is_set(),
            "paused": '*' in _paused_keys,
            "market_open": _is_market_open(),
            "spot_disabled": _SPOT_DISABLED,
            "spot_adaptive": _SPOT_ADAPTIVE,
            "caches": result,
            "adaptive": _adaptive_info,
        },
    )


@app_core.post(
    path="/private/v1/cache/adaptive",
    description="开关自适应缓存刷新",
    summary="启用/禁用自适应刷新（需认证）",
)
def cache_adaptive_toggle(
    enabled: str = Query(..., description="1=启用, 0=禁用"),
    _current_user: User = Depends(get_current_active_user),
):
    global _SPOT_ADAPTIVE
    new_val = enabled.strip() in ("1", "true", "yes")
    old_val = _SPOT_ADAPTIVE
    _SPOT_ADAPTIVE = new_val
    logger.info(f"自适应刷新: {old_val} → {new_val}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"spot_adaptive": _SPOT_ADAPTIVE, "previous": old_val},
    )


@app_core.post(
    path="/private/v1/cache/interval",
    description="设置单个缓存刷新间隔",
    summary="手动控制缓存刷新频率（需认证）",
)
def cache_set_interval(
    key: str = Query(..., description="缓存 key"),
    interval: int = Query(..., description="刷新间隔（周期数），0=禁用直到下次访问"),
    _current_user: User = Depends(get_current_active_user),
):
    with _cache_interval_lock:
        old = _cache_interval.get(key, _SPOT_INTERVAL_WARM)
        _cache_interval[key] = interval
    logger.info(f"缓存间隔 {key}: {old} → {interval} 周期")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"key": key, "interval_cycles": interval, "previous": old},
    )


_SPOT_STALE_THRESHOLD = 120  # 交易时段超过此秒数视为过期


def _cached_on_demand(cache_key: str, func, **kwargs) -> tuple[list | None, int | None]:
    """Serve from cache if available, otherwise call func and cache result.
    Returns (data, status_code_or_None). None status = 200 with data.
    """
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)
        if entry is not None:
            _record_cache_access(cache_key)
    if entry is not None:
        age = int(time.time() - entry["ts"])
        if age < _CACHE_TTL:
            return entry["data"], None
    try:
        df = _call_akshare_direct(func, **kwargs)
        if df is None:
            return None, 404
        data = _sanitize_records(df.to_dict(orient="records"))
        with _spot_cache_lock:
            _spot_cache[cache_key] = {"data": data, "ts": time.time()}
        return data, None
    except (RequestsConnectionError, RequestsTimeout):
        # If we have stale cache, serve it anyway
        if entry is not None:
            return entry["data"], None
        return None, 502
    except Exception:
        # Non-network error — likely bad symbol/params (KeyError, ValueError, etc.)
        return None, 404


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
        if entry is not None:
            _record_cache_access(cache_key)
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
    path="/public/v1/fund_lof_spot",
    description="LOF 实时行情接口 (v1, 缓存)",
    summary="返回 LOF 实时行情，数据来自后台缓存",
)
def fund_lof_spot_cached(
    request: Request,
    symbol: str = Query("", description="LOF 代码筛选，留空返回全市场"),
):
    cache_key = "fund_lof_spot"
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)
        if entry is not None:
            _record_cache_access(cache_key)
    if entry is not None:
        data = entry["data"]
        age = int(time.time() - entry["ts"])
        stale_headers = _stale_headers(entry["ts"])
        logger.info(f"LOF 行情缓存命中: age={age}s, count={len(data)}")
    elif not _spot_cache_warm.is_set():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "LOF 行情缓存预热中，请稍后重试"},
            headers={"Retry-After": "30"},
        )
    else:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "LOF 行情数据源不可用，请稍后重试"},
        )
    if symbol:
        code = symbol.strip()
        data = [row for row in data if code in str(row.get("基金代码", row.get("代码", "")))]
        if not data:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到 LOF 代码: {symbol}"},
            )
    return JSONResponse(
        status_code=status.HTTP_200_OK, content=data, headers=stale_headers
    )


@app_core.get(
    path="/public/v1/fund_lof_hist",
    description="LOF 历史行情接口 (v1)",
    summary="返回 LOF 历史行情",
)
def fund_lof_hist(
    symbol: str = Query(..., description="LOF 代码，如 166009"),
    period: str = Query("daily", description="周期: daily / weekly / monthly"),
    start_date: str = Query("19700101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("20500101", description="结束日期 YYYYMMDD"),
    adjust: str = Query("", description="复权类型"),
):
    try:
        received_df = _call_akshare_direct(
            ak.fund_lof_hist_em, symbol=symbol, period=period,
            start_date=start_date, end_date=end_date, adjust=adjust,
        )
        if received_df is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "该接口返回数据为空"},
            )
    except (RequestsConnectionError, RequestsTimeout) as e:
        logger.error(f"LOF 历史重试 {RETRY_MAX_ATTEMPTS} 次后仍失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": f"数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"},
        )
    except Exception as e:
        logger.warning(f"LOF 历史查询失败 ({symbol}): {e}")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": f"未找到数据: {symbol}"},
        )
    return Response(content=_df_to_json_bytes(received_df), media_type="application/json")


@app_core.get(
    path="/public/v1/fund_open_list",
    description="场外开放式基金列表 (v1, 缓存)",
    summary="返回全部开放式基金及最新净值，数据来自后台缓存",
)
def fund_open_list_cached(
    request: Request,
    page: int = Query(0, ge=0, description="页码，0=不分页"),
    page_size: int = Query(100, ge=1, le=1000, description="每页条数（最大 1000）"),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("fund_open_list")
    if entry is not None:
        data = entry["data"]
        age = int(time.time() - entry["ts"])
        total = len(data)
        if page > 0:
            start = (page - 1) * page_size
            data = data[start : start + page_size]
        logger.info(f"场外基金列表缓存命中: age={age}s, returned={len(data)}/{total}")
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
        content={"error": "场外基金列表数据源不可用，请稍后重试"},
    )


@app_core.get(
    path="/public/v1/fund_open_hist",
    description="场外开放式基金历史净值接口 (v1)",
    summary="返回开放式基金历史净值走势",
)
def fund_open_hist(
    symbol: str = Query(..., description="基金代码，如 710001"),
    indicator: str = Query("单位净值走势", description="指标: 单位净值走势 / 累计净值走势"),
    period: str = Query("成立来", description="周期: 1月/近1月, 3月/近3月, 6月/近6月, 1年/近1年, 3年, 5年, 今年来, 成立来"),
):
    try:
        received_df = _call_akshare_direct(
            ak.fund_open_fund_info_em,
            symbol=symbol, indicator=indicator, period=period,
        )
        if received_df is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到基金: {symbol}"},
            )
    except (RequestsConnectionError, RequestsTimeout) as e:
        logger.error(f"场外基金历史 {symbol} 网络错误: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": f"数据源连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"},
        )
    except Exception as e:
        # 非网络异常通常意味着无效的 symbol/参数（KeyError, ValueError 等）
        logger.warning(f"场外基金历史 {symbol} 查询失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": f"未找到基金或数据: {symbol}"},
        )

    # Upstream AKShare ignores the 'period' parameter — apply client-side date filter
    import pandas as pd
    _now = datetime.now(timezone(timedelta(hours=8)))  # Beijing time
    _period_days = {
        "1月": 30, "近1月": 30,
        "3月": 90, "近3月": 90,
        "6月": 180, "近6月": 180,
        "1年": 365, "近1年": 365,
        "3年": 1095,
        "5年": 1825,
    }
    if period == "今年来":
        _cutoff = _now.replace(month=1, day=1).date()
    elif period in _period_days:
        _cutoff = (_now - timedelta(days=_period_days[period])).date()
    else:
        _cutoff = None  # "成立来" — no filter

    if _cutoff is not None:
        _date_col = "净值日期"
        if _date_col in received_df.columns:
            received_df = received_df[
                pd.to_datetime(received_df[_date_col]).dt.date >= _cutoff
            ]

    return Response(content=_df_to_json_bytes(received_df), media_type="application/json")


@app_core.get(
    path="/public/v1/fund_open_search",
    description="场外基金搜索 (v1)",
    summary="基于缓存列表搜索场外基金代码或名称",
)
def fund_open_search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(20, ge=0, le=1000, description="最大返回条数，0=不限制"),
):
    matches, total = _search_cache("fund_open_list", q, limit, "基金代码", "基金简称")
    if matches is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "场外基金列表缓存未就绪，请稍后重试"},
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
    path="/public/v1/stock_hk_list",
    description="港股代码列表 (v1, 缓存)",
    summary="返回港股通成份股，数据来自后台缓存",
)
def stock_hk_list_cached(
    request: Request,
    page: int = Query(0, ge=0, description="页码，0=不分页"),
    page_size: int = Query(100, ge=1, le=1000, description="每页条数（最大 1000）"),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("stock_hk_list")
    if entry is not None:
        data = entry["data"]
        total = len(data)
        if page > 0:
            data = data[(page - 1) * page_size : page * page_size]
        return JSONResponse(status_code=status.HTTP_200_OK, content=data, headers={"X-Total-Count": str(total)})
    if not _spot_cache_warm.is_set():
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "缓存预热中，请稍后重试"})
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": "港股列表数据源不可用"})


@app_core.get(
    path="/public/v1/stock_hk_spot",
    description="港股实时行情 (v1, 缓存)",
    summary="支持切换数据源（eastmoney/sina），可筛选个股",
)
def stock_hk_spot_universal(
    request: Request,
    source: str = Query("", description="eastmoney / sina"),
    symbol: str = Query("", description="港股代码筛选，如 00700"),
):
    source = source or DEFAULT_SOURCE
    if source not in _HK_SPOT_SOURCE_MAP:
        valid = ", ".join(_HK_SPOT_SOURCE_MAP)
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": f"不支持的数据源: {source}，可选: {valid}"})
    cache_key = "stock_hk_spot_" + source
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)
        if entry is not None:
            _record_cache_access(cache_key)
    if entry is not None:
        data = entry["data"]
        stale_headers = _stale_headers(entry["ts"])
    elif not _spot_cache_warm.is_set():
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "港股行情缓存预热中"})
    else:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": "港股行情数据源不可用"})
    if symbol:
        code = symbol.strip().zfill(5)
        data = [row for row in data if code in str(row.get("代码", row.get("code", "")))]
        if not data:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": f"未找到港股: {symbol}"})
    data = _normalize_records(data, source, _HK_SPOT_NORMALIZE_MAP)
    stale_headers["X-Market-Source"] = source
    return JSONResponse(status_code=status.HTTP_200_OK, content=data, headers=stale_headers)


@app_core.get(
    path="/public/v1/stock_hk_hist",
    description="港股历史行情 (v1)",
    summary="支持切换数据源（eastmoney/sina）",
)
def stock_hk_hist(
    symbol: str = Query(..., description="港股代码，如 00700"),
    source: str = Query("", description=f"eastmoney / sina / auto（默认 {DEFAULT_SOURCE}）"),
    start_date: str = Query("19700101"),
    end_date: str = Query("22220101"),
    adjust: str = Query(""),
):
    source = source or DEFAULT_SOURCE

    def _try_hk_hist(src: str) -> "pd.DataFrame":
        sc = _HK_HIST_SOURCE_MAP[src]
        df = _call_akshare_direct(
            sc["func"], symbol=symbol,
            start_date=start_date, end_date=end_date, adjust=adjust,
        )
        if df is None:
            raise EmptyDataError(f"{src} 返回空数据")
        return _normalize_df(df, src, _HK_HIST_NORMALIZE_MAP)

    # ── 显式数据源 ──────────────────────────────────────────
    if source != "auto":
        if source not in _HK_HIST_SOURCE_MAP:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": f"不支持: {source}"},
            )
        try:
            df = _try_hk_hist(source)
        except EmptyDataError:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "数据为空"},
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"error": f"连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"},
            )
        except Exception as e:
            logger.warning(f"港股历史 {source} 查询失败 ({symbol}): {e}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"未找到数据: {symbol}（{source}）"},
            )
        return Response(
            content=_df_to_json_bytes(df),
            media_type="application/json",
            headers={"X-Market-Source": source},
        )

    # ── auto 模式 ──────────────────────────────────────────
    try:
        df, actual_source = _try_auto_sources("hk_hist", _try_hk_hist)
        return Response(
            content=_df_to_json_bytes(df),
            media_type="application/json",
            headers={"X-Market-Source": actual_source},
        )
    except AutoSourceExhaustedError as e:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"auto: 所有数据源不可用，已尝试 {e.sources_tried}"
            },
        )


@app_core.get(
    path="/public/v1/stock_hk_search",
    description="港股搜索 (v1)",
    summary="基于缓存列表搜索港股代码或名称",
)
def stock_hk_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=0, le=1000),
):
    matches, total = _search_cache("stock_hk_list", q, limit, "code", "name")
    if matches is None:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "港股列表缓存未就绪"})
    return JSONResponse(status_code=status.HTTP_200_OK, content=matches, headers={"X-Total-Count": str(total)})


@app_core.get(
    path="/public/v1/futures_spot",
    description="期货实时行情 (v1, 缓存)",
    summary="返回国际期货实时行情",
)
def futures_spot_cached(request: Request, symbol: str = Query("")):
    cache_key = "futures_spot"
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)
        if entry is not None:
            _record_cache_access(cache_key)
    if entry is not None:
        data = entry["data"]
        stale_headers = _stale_headers(entry["ts"])
    elif not _spot_cache_warm.is_set():
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "期货行情缓存预热中"})
    else:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": "期货行情数据源不可用"})
    if symbol:
        code = symbol.strip().upper()
        data = [row for row in data if code in str(row).upper()]
        if not data:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": f"未找到: {symbol}"})
    return JSONResponse(status_code=status.HTTP_200_OK, content=data, headers=stale_headers)


@app_core.get(
    path="/public/v1/futures_hist",
    description="期货历史行情 (v1)",
    summary="返回国际期货历史行情",
)
def futures_hist(
    symbol: str = Query(..., description="期货代码，如 HG00Y"),
    start_date: str = Query("19700101"),
    end_date: str = Query("22220101"),
):
    try:
        df = _call_akshare_direct(ak.futures_global_hist_em, symbol=symbol, start_date=start_date, end_date=end_date)
        if df is None:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "数据为空"})
    except (RequestsConnectionError, RequestsTimeout) as e:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": f"连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"})
    except Exception as e:
        logger.warning(f"期货历史查询失败 ({symbol}): {e}")
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": f"未找到: {symbol}"})
    return Response(content=_df_to_json_bytes(df), media_type="application/json")


@app_core.get(
    path="/public/v1/index_list",
    description="全球指数列表 (v1, 缓存)",
    summary="返回全球指数代码与名称",
)
def index_list_cached(
    request: Request,
    page: int = Query(0, ge=0),
    page_size: int = Query(100, ge=1, le=1000),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("index_list")
    if entry is not None:
        data = entry["data"]
        total = len(data)
        if page > 0:
            data = data[(page - 1) * page_size : page * page_size]
        return JSONResponse(status_code=status.HTTP_200_OK, content=data, headers={"X-Total-Count": str(total)})
    if not _spot_cache_warm.is_set():
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "缓存预热中"})
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": "指数列表数据源不可用"})


@app_core.get(
    path="/public/v1/index_spot",
    description="全球指数实时行情 (v1, 缓存)",
    summary="返回全球指数实时行情",
)
def index_spot_cached(request: Request, symbol: str = Query("")):
    cache_key = "index_spot"
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)
        if entry is not None:
            _record_cache_access(cache_key)
    if entry is not None:
        data = entry["data"]
        stale_headers = _stale_headers(entry["ts"])
    elif not _spot_cache_warm.is_set():
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "指数行情缓存预热中"})
    else:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": "指数行情数据源不可用"})
    if symbol:
        code = symbol.strip().upper()
        data = [row for row in data if code in str(row).upper()]
        if not data:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": f"未找到: {symbol}"})
    return JSONResponse(status_code=status.HTTP_200_OK, content=data, headers=stale_headers)


@app_core.get(
    path="/public/v1/index_hist",
    description="全球指数历史行情 (v1)",
    summary="支持切换数据源（eastmoney/sina）",
)
def index_hist(
    symbol: str = Query(..., description="指数代码，如 OMX"),
    source: str = Query(""),
):
    source = source or DEFAULT_SOURCE
    sc = _INDEX_HIST_SOURCE_MAP.get(source)
    if sc is None:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": f"不支持: {source}"})
    try:
        df = _call_akshare_direct(sc["func"], symbol=symbol)
        if df is None:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "数据为空"})
    except (RequestsConnectionError, RequestsTimeout) as e:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": f"连接失败，已重试 {RETRY_MAX_ATTEMPTS} 次"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": f"异常: {e}"})
    return Response(
        content=_df_to_json_bytes(df),
        media_type="application/json",
        headers={"X-Market-Source": source},
    )


@app_core.get(
    path="/public/v1/index_search",
    description="全球指数搜索 (v1)",
    summary="基于缓存列表搜索指数名称或代码",
)
def index_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=0, le=1000),
):
    matches, total = _search_cache("index_list", q, limit, "代码", "指数名称")
    if matches is None:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "指数列表缓存未就绪"})
    return JSONResponse(status_code=status.HTTP_200_OK, content=matches, headers={"X-Total-Count": str(total)})


@app_core.get(
    path="/public/v1/bond_cov_list",
    description="可转债列表 (v1, 缓存)",
    summary="返回可转债代码、名称与核心指标",
)
def bond_cov_list_cached(
    request: Request,
    page: int = Query(0, ge=0),
    page_size: int = Query(100, ge=1, le=1000),
):
    with _spot_cache_lock:
        entry = _spot_cache.get("bond_cov_list")
    if entry is not None:
        data = entry["data"]
        total = len(data)
        if page > 0:
            data = data[(page - 1) * page_size : page * page_size]
        return JSONResponse(status_code=status.HTTP_200_OK, content=data, headers={"X-Total-Count": str(total)})
    if not _spot_cache_warm.is_set():
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "缓存预热中"})
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": "可转债列表数据源不可用"})


@app_core.get(
    path="/public/v1/bond_cov_spot",
    description="可转债实时行情 (v1, 缓存)",
    summary="返回可转债实时行情",
)
def bond_cov_spot_cached(request: Request, symbol: str = Query("")):
    cache_key = "bond_cov_spot"
    with _spot_cache_lock:
        entry = _spot_cache.get(cache_key)
        if entry is not None:
            _record_cache_access(cache_key)
    if entry is not None:
        data = entry["data"]
        stale_headers = _stale_headers(entry["ts"])
    elif not _spot_cache_warm.is_set():
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "可转债行情缓存预热中"})
    else:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": "可转债行情数据源不可用"})
    if symbol:
        code = symbol.strip().lower()
        data = [row for row in data if code in str(row.get("symbol", row.get("code", ""))).lower()]
        if not data:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": f"未找到: {symbol}"})
    return JSONResponse(status_code=status.HTTP_200_OK, content=data, headers=stale_headers)


@app_core.get(
    path="/public/v1/bond_cov_hist",
    description="可转债历史行情 (v1)",
    summary="返回可转债历史行情",
)
def bond_cov_hist(symbol: str = Query(..., description="可转债代码，如 sh010107")):
    sc = _BOND_COV_HIST_SOURCE_MAP.get("sina")
    try:
        df = _call_akshare_direct(sc["func"], symbol=symbol)
        if df is None:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "数据为空"})
    except (RequestsConnectionError, RequestsTimeout) as e:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"error": f"连接失败"})
    except Exception as e:
        logger.warning(f"可转债历史查询失败 ({symbol}): {e}")
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": f"未找到: {symbol}"})
    return Response(content=_df_to_json_bytes(df), media_type="application/json")


@app_core.get(
    path="/public/v1/bond_cov_search",
    description="可转债搜索 (v1)",
    summary="基于缓存列表搜索可转债代码或名称",
)
def bond_cov_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=0, le=1000),
):
    matches, total = _search_cache("bond_cov_list", q, limit, "债券代码", "债券简称")
    if matches is None:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"error": "可转债列表缓存未就绪"})
    return JSONResponse(status_code=status.HTTP_200_OK, content=matches, headers={"X-Total-Count": str(total)})

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
            logger.warning(f"接口 {item_id} 查询失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": f"未找到数据: {item_id}，请确认参数是否正确"
                },
            )
        logger.info(f"获取到 {item_id} 的数据")
        return Response(content=_df_to_json_bytes(received_df), media_type="application/json")
    else:
        try:
            received_df = _call_akshare(item_id, eval_str)
            if received_df is None:
                logger.info("该接口返回数据为空，请确认参数是否正确：https://akshare.akfamily.xyz")
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"error": "该接口返回数据为空，请确认参数是否正确：https://akshare.akfamily.xyz"},
                )
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
            logger.warning(f"接口 {item_id} 查询失败: {e}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": f"未找到数据: {item_id}，请确认参数是否正确"
                },
            )
        logger.info(f"获取到 {item_id} 的数据")
        return Response(content=_df_to_json_bytes(received_df), media_type="application/json")


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
