# 数据源差异与统一接口规范

本文档记录 `GET /api/public/v1/stock_cn_hist` 三个底层数据源（Eastmoney、Sina、Tencent）
返回格式的差异，以及 AKTools 的统一归一化 schema。

> **全量参考：** [unified-interface-distillation.md](unified-interface-distillation.md) 涵盖所有多源端点的完整字段清单、归一化映射和蒸馏过程。

---

## 底层数据源对比

### Eastmoney (`ak.stock_zh_a_hist`)

| 原始列名（中文） | 含义 | 示例值 | 备注 |
| --- | --- | --- | --- |
| `日期` | 交易日期 | `"2025-01-02"` | |
| `开盘` | 开盘价 | `4.34` | |
| `收盘` | 收盘价 | `4.24` | |
| `最高` | 最高价 | `4.37` | |
| `最低` | 最低价 | `4.20` | |
| `成交量` | 成交量 | `115945` | **单位：手**（1 手 = 100 股） |

额外列（归一化丢弃）：`股票代码`、`成交额`、`振幅`、`涨跌幅`、`涨跌额`、`换手率`

参数支持：`symbol`、`start_date`、`end_date`、`adjust`

### Sina (`ak.stock_zh_a_daily`)

| 原始列名（英文） | 含义 | 示例值 | 备注 |
| --- | --- | --- | --- |
| `date` | 交易日期 | `"2025-01-02"` | |
| `open` | 开盘价 | `4.34` | |
| `high` | 最高价 | `4.37` | |
| `low` | 最低价 | `4.20` | |
| `close` | 收盘价 | `4.24` | |
| `volume` | 成交量 | `11594465` | **单位：股** |

额外列（归一化丢弃）：`amount`、`outstanding_share`、`turnover`

参数支持：仅 `symbol`（不支持日期筛选和复权，返回该股票全部历史数据）

### Tencent (`ak.stock_zh_a_hist_tx`)

| 原始列名（英文） | 含义 | 示例值 | 备注 |
| --- | --- | --- | --- |
| `date` | 交易日期 | `"2025-01-02"` | |
| `open` | 开盘价 | `4.34` | |
| `close` | 收盘价 | `4.24` | |
| `high` | 最高价 | `4.37` | |
| `low` | 最低价 | `4.20` | |
| `amount` | 成交量 | `115945` | **⚠ 列名 misnamed：实际是成交量（手），不是成交额** |

参数支持：`symbol`、`start_date`、`end_date`

### 差异汇总

| 方面 | Eastmoney | Sina | Tencent |
| --- | --- | --- | --- |
| 列名语言 | 中文 | 英文 | 英文 |
| 成交量单位 | 手（×100 = 股） | 股 | 手（×100 = 股，列名为 `amount`） |
| 日期筛选 | 支持 | **不支持**（返回全部历史） | 支持 |
| 复权 | 支持 | 不支持 | 不支持 |
| 海外访问 | 可能受限 | 友好 | 友好 |

---

## AKTools 统一输出 Schema

无论使用哪个 `source` 参数（含 `auto`），API 始终返回以下 **6 字段** JSON 结构，**零 null**：

```json
[
  {
    "date": "2025-01-02",
    "open": 4.34,
    "high": 4.37,
    "low": 4.2,
    "close": 4.24,
    "volume": 11594465
  }
]
```

### 字段规范

| 统一字段 | 类型 | 含义 | Eastmoney 来源 | Sina 来源 | Tencent 来源 |
| --- | --- | --- | --- | --- | --- |
| `date` | string | 交易日期 | `日期` | `date` | `date` |
| `open` | float | 开盘价 | `开盘` | `open` | `open` |
| `high` | float | 最高价 | `最高` | `high` | `high` |
| `low` | float | 最低价 | `最低` | `low` | `low` |
| `close` | float | 收盘价 | `收盘` | `close` | `close` |
| `volume` | int | 成交量（股） | `成交量` × 100 | `volume` | `amount` × 100 |

> **规则：** 所有源都提供全部 6 个字段，无 null。超出 schema 的源特有字段被丢弃。

### 单位归一化

- **成交量：** Eastmoney 和 Tencent 原始单位为"手"（1 手 = 100 股），归一化为**股**（×100）。
  Sina 原始单位即为股，无需转换。

---

## 自动数据源选择 (`source=auto`)

当 `source=auto`（或环境变量 `AKSHARE_DEFAULT_SOURCE=auto`）时，AKTools
按优先级自动选择可用数据源，无需客户端关心地域可用性。

### 优先级

```
eastmoney → tencent → sina
  (richest)   (filtered)  (full history, last resort)
```

### 熔断器

| 参数 | 值 | 说明 |
| --- | --- | --- |
| 失败阈值 | 2 次 | 连续失败 N 次后进入冷却 |
| 冷却期 | 60 秒 | 冷却期内 auto 模式跳过该源 |
| 最后手段 | 全部尝试 | 所有源都在冷却时，重新尝试所有源 |

- 显式指定 `source=eastmoney` 等会**绕过**熔断器，直接调用指定源。
- 每次成功调用自动重置该源的失败计数器。

---

## 实现位置

- 配置：`aktools/core/api.py` → `_HIST_NORMALIZE_MAP`
- 归一化函数：`aktools/core/api.py` → `_normalize_stock_hist()`
- 自动选择 + 熔断：`aktools/core/api.py` → `_AUTO_SOURCE_PRIORITY`、`_source_health`、`_source_in_cooldown()`
- 调用点：`stock_cn_hist` handler
- 测试：`tests/test_api.py`
