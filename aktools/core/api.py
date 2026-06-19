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
_STATIC_CACHE_MAP = {
    "stock_info": ak.stock_info_a_code_name,
}

# ── 缓存（后台线程定期刷新） ──────────────────────────────────
_CACHE_TTL = 60          # 实时行情刷新间隔（秒）
_STATIC_CACHE_TTL = 86400  # 静态数据刷新间隔（秒，默认 1 天）
_spot_cache = {}  # {key: {"data": [...], "ts": float}}
_spot_cache_lock = threading.Lock()
_spot_cache_warm = threading.Event()  # 首次刷新完成后置位


def _refresh_cache():
    """Daemon thread: periodically refresh cached data."""
    cycle = 0
    _static_interval = max(1, _STATIC_CACHE_TTL // _CACHE_TTL)  # 每 N 个周期刷新一次静态数据
    while True:
        cycle += 1
        # 刷新实时行情（每周期）
        for source, func in _SPOT_SOURCE_MAP.items():
            try:
                df = func()
                if df is not None:
                    data = json.loads(df.to_json(orient="records", date_format="iso"))
                    with _spot_cache_lock:
                        _spot_cache[source] = {"data": data, "ts": time.time()}
                    logger.info(f"缓存已刷新: {source} ({len(data)} 条)")
            except Exception as e:
                logger.warning(f"刷新缓存失败 [{source}]: {e}")
        # 静态数据仅在启动或每 _static_interval 个周期刷新
        if cycle == 1 or cycle % _static_interval == 0:
            for key, func in _STATIC_CACHE_MAP.items():
                try:
                    df = func()
                    if df is not None:
                        data = json.loads(df.to_json(orient="records", date_format="iso"))
                        # 清理名称中的空白字符（如 "柳    工" → "柳工"）
                        for row in data:
                            if "name" in row and isinstance(row["name"], str):
                                row["name"] = "".join(row["name"].split())
                        with _spot_cache_lock:
                            _spot_cache[key] = {"data": data, "ts": time.time()}
                        logger.info(f"缓存已刷新: {key} ({len(data)} 条)")
                except Exception as e:
                    logger.warning(f"刷新缓存失败 [{key}]: {e}")
        if cycle == 1:
            _spot_cache_warm.set()
        time.sleep(_CACHE_TTL)


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
logger = logging.getLogger(name='AKToolsLog')
logger.setLevel(logging.INFO)

# 创建一个TimedRotatingFileHandler来进行日志轮转
handler = TimedRotatingFileHandler(
    filename='/tmp/aktools_log.log' if os.getenv('VERCEL') == '1' else 'aktools_log.log',
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
    path="/public/v1/stock_zh_a_hist",
    description="统一 A 股历史行情接口 (v1)",
    summary="支持切换数据源（eastmoney/sina/tencent），方便海外用户访问",
)
def stock_zh_a_hist_universal(
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
    path="/public/v1/stock_zh_a_spot",
    description="统一 A 股实时行情接口 (v1)",
    summary="支持切换数据源（eastmoney/sina），可筛选个股",
)
def stock_zh_a_spot_universal(
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
        entry = _spot_cache.get(source)
        fallback_entry = None
        if entry is None:
            for s in _SPOT_SOURCE_MAP:
                if s != source and s in _spot_cache:
                    fallback_entry = _spot_cache[s]
                    break

    if entry is not None:
        data = entry["data"]
        logger.info(
            f"实时行情缓存命中: source={source}, "
            f"age={int(time.time() - entry['ts'])}s"
        )
    elif fallback_entry is not None:
        data = fallback_entry["data"]
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

    return JSONResponse(status_code=status.HTTP_200_OK, content=data)


@app_core.get(
    path="/public/v1/stock_info_a_code_name",
    description="A 股股票代码列表 (v1, 缓存)",
    summary="返回沪深京 A 股代码与名称，数据来自后台缓存，响应 <10ms",
)
def stock_info_a_code_name_cached(request: Request):
    with _spot_cache_lock:
        entry = _spot_cache.get("stock_info")

    if entry is not None:
        data = entry["data"]
        age = int(time.time() - entry["ts"])
        logger.info(f"股票列表缓存命中: age={age}s, count={len(data)}")
        return JSONResponse(status_code=status.HTTP_200_OK, content=data)

    if not _spot_cache_warm.is_set():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "缓存预热中，请稍后重试"},
            headers={"Retry-After": "30"},
        )

    # 缓存已预热但此 key 缺失（不应发生，但做兜底）
    try:
        df = _call_akshare_direct(ak.stock_info_a_code_name)
        if df is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "该接口返回数据为空"},
            )
        data = json.loads(df.to_json(orient="records", date_format="iso"))
        return JSONResponse(status_code=status.HTTP_200_OK, content=data)
    except Exception as e:
        logger.error(f"股票列表直接调用失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": f"数据接口调用异常: {e}"},
        )


@app_core.get(
    path="/v1/default_source",
    description="查看 / 切换默认数据源",
    summary="GET 返回当前默认源，POST 切换默认源",
)
@app_core.post(
    path="/v1/default_source",
    description="查看 / 切换默认数据源",
    summary="GET 返回当前默认源，POST 切换默认源",
)
def default_source(
    request: Request,
    source: Optional[str] = Query(None, description="新默认源: eastmoney / sina / tencent"),
):
    global DEFAULT_SOURCE
    if request.method == "POST" and source:
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
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"default_source": DEFAULT_SOURCE, "available": list(_SOURCE_MAP)},
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
