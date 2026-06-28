# -*- coding:utf-8 -*-
# /usr/bin/env python
"""
Date: 2025/06/25
Desc: API 归一化层单元测试 — 验证 6 字段统一 schema、单位转换和自动数据源选择
"""
import time

import pandas as pd
import pytest

from aktools.core.api import (
    _normalize_stock_hist,
    _source_in_cooldown,
    _record_source_success,
    _record_source_failure,
    CIRCUIT_BREAKER_COOLDOWN,
)

# ── 统一 6 字段 schema ──────────────────────────────────────────
UNIFIED_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


# ── Eastmoney 测试 ───────────────────────────────────────────────

def test_eastmoney_columns_and_values():
    """东方财富中文列名 → 统一 6 字段英文 schema"""
    df = pd.DataFrame(
        {
            "日期": ["2025-01-02", "2025-01-03"],
            "开盘": [4.34, 4.30],
            "最高": [4.37, 4.35],
            "最低": [4.20, 4.22],
            "收盘": [4.24, 4.28],
            "成交量": [115945, 98000],
            # 多余列（应被丢弃）
            "股票代码": ["600075", "600075"],
            "成交额": [49760077, 42000000],
            "振幅": [3.91, 2.50],
        }
    )
    result = _normalize_stock_hist(df, "eastmoney")

    assert list(result.columns) == UNIFIED_COLUMNS
    assert result["date"].tolist() == ["2025-01-02", "2025-01-03"]
    assert result["open"].tolist() == [4.34, 4.30]
    assert result["close"].tolist() == [4.24, 4.28]
    # 多余列不应出现
    assert "stock_code" not in result.columns
    assert "amount" not in result.columns


def test_eastmoney_volume_conversion():
    """东方财富成交量：手 → 股（×100）"""
    df = pd.DataFrame(
        {
            "日期": ["2025-01-02"],
            "开盘": [4.34],
            "最高": [4.37],
            "最低": [4.20],
            "收盘": [4.24],
            "成交量": [115945],  # 115,945 手
        }
    )
    result = _normalize_stock_hist(df, "eastmoney")

    assert result["volume"].iloc[0] == 11_594_500


def test_eastmoney_empty_dataframe():
    """空 DataFrame 仍返回正确的 6 列"""
    df = pd.DataFrame(
        columns=["日期", "开盘", "最高", "最低", "收盘", "成交量"]
    )
    result = _normalize_stock_hist(df, "eastmoney")
    assert list(result.columns) == UNIFIED_COLUMNS
    assert len(result) == 0


# ── Sina 测试 ────────────────────────────────────────────────────

def test_sina_columns_and_values():
    """Sina 英文列名 → 统一 schema（多余列丢弃）"""
    df = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "open": [4.34],
            "high": [4.37],
            "low": [4.20],
            "close": [4.24],
            "volume": [11594465],
            # 多余列
            "amount": [49760077],
            "outstanding_share": [1707362663],
            "turnover": [0.00679],
        }
    )
    result = _normalize_stock_hist(df, "sina")

    assert list(result.columns) == UNIFIED_COLUMNS
    assert result["date"].iloc[0] == "2025-01-02"
    assert result["open"].iloc[0] == 4.34
    assert result["volume"].iloc[0] == 11594465  # 已经是股，不转换
    assert "amount" not in result.columns
    assert "turnover_rate" not in result.columns


# ── Tencent 测试 ─────────────────────────────────────────────────

def test_tencent_volume_conversion():
    """腾讯 amount 列实际是成交量（手）→ 归一化为 volume（股）×100"""
    df = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "open": [4.34],
            "high": [4.37],
            "low": [4.20],
            "close": [4.24],
            "amount": [115945],  # 实际是成交量（手），非成交额
        }
    )
    result = _normalize_stock_hist(df, "tencent")

    assert list(result.columns) == UNIFIED_COLUMNS
    assert result["volume"].iloc[0] == 11_594_500  # 115945 × 100


def test_tencent_preserves_row_count():
    """多行数据行数不变"""
    df = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-03", "2025-01-06"],
            "open": [4.34, 4.30, 4.28],
            "close": [4.24, 4.28, 4.35],
            "high": [4.37, 4.35, 4.38],
            "low": [4.20, 4.22, 4.25],
            "amount": [115945, 98000, 102000],
        }
    )
    result = _normalize_stock_hist(df, "tencent")
    assert len(result) == 3


# ── 通用测试 ─────────────────────────────────────────────────────

def test_unknown_source_passthrough():
    """未知数据源直接透传，不做任何修改"""
    df = pd.DataFrame({"foo": [1, 2], "bar": [3, 4]})
    result = _normalize_stock_hist(df, "nonexistent")
    pd.testing.assert_frame_equal(result, df)


# ── 熔断器单元测试 ──────────────────────────────────────────────

def test_circuit_breaker_not_in_cooldown_initially():
    """初始状态：所有源都不在冷却期"""
    for src in ["eastmoney", "tencent", "sina"]:
        assert not _source_in_cooldown("cn_hist", src)


def test_circuit_breaker_enters_cooldown_after_threshold():
    """连续失败 CIRCUIT_BREAKER_THRESHOLD 次后进入冷却"""
    cat, src = "cn_hist", "eastmoney"
    _record_source_success(cat, src)

    _record_source_failure(cat, src)
    assert not _source_in_cooldown(cat, src)

    _record_source_failure(cat, src)
    assert _source_in_cooldown(cat, src)


def test_circuit_breaker_success_resets_counter():
    """成功后重置失败计数器，冷却解除"""
    cat, src = "cn_hist", "sina"
    _record_source_success(cat, src)
    _record_source_failure(cat, src)
    assert not _source_in_cooldown(cat, src)

    _record_source_success(cat, src)
    _record_source_failure(cat, src)
    assert not _source_in_cooldown(cat, src)
    _record_source_failure(cat, src)
    assert _source_in_cooldown(cat, src)


def test_circuit_breaker_cooldown_expires():
    """冷却期过后自动恢复"""
    cat, src = "cn_hist", "tencent"
    from aktools.core.api import _source_health, _source_health_lock, _health_key

    _record_source_success(cat, src)
    _record_source_failure(cat, src)
    _record_source_failure(cat, src)
    assert _source_in_cooldown(cat, src)

    key = _health_key(cat, src)
    with _source_health_lock:
        _source_health[key]["cooldown_until"] = time.time() - 1

    assert not _source_in_cooldown(cat, src)
