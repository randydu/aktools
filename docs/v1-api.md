# V1 API

AKTools v0.2.4 — 45 endpoints across 10 categories, unified interface normalization, adaptive caching, fund NAV estimation.

---

## 环境变量

| 变量 | 用途 | 默认值 |
| ----- | ----- | ----- |
| `AKSHARE_PROXY` | HTTP/HTTPS 代理地址 | 无 |
| `AKSHARE_DEFAULT_SOURCE` | 默认数据源 | `auto` |
| `AKTOOLS_TOKENS_FILE` | 预配置 Token JSON 文件路径 | 无 |
| `AKTOOLS_DATA_DIR` | 持久化数据目录 | `./data/` |
| `AKTOOLS_DISABLE_SPOT` | 禁用实时行情刷新 | `0` |
| `AKTOOLS_SPOT_ADAPTIVE` | 自适应缓存刷新 | `1` |
| `AKTOOLS_CACHE_WARM_S` | 高频阈值（秒） | `300` |
| `AKTOOLS_CACHE_COLD_S` | 低频阈值（秒） | `1800` |
| `AKTOOLS_LOG_LEVEL` | 日志级别 | `INFO` |

---

## A 股 (China)

### 列表

`GET /api/public/v1/stock_cn_list`

| 参数 | 默认值 | 说明 |
| ----- | ----- | ----- |
| `page` | `0` (不分页) | 页码，1-based |
| `page_size` | `100` | 每页条数，最大 1000 |

### 实时行情

`GET /api/public/v1/stock_cn_spot`

| 参数 | 默认值 | 说明 |
| ----- | ----- | ----- |
| `source` | `eastmoney` | `eastmoney` / `sina` / `auto` |
| `symbol` | 空 (全市场) | 个股代码筛选 |

**返回字段**（统一归一化，与数据源无关）：

| 字段 | 类型 | 含义 |
| ----- | ----- | ----- |
| `code` | string | 股票代码 |
| `name` | string | 股票名称 |
| `latest` | float | 最新价 |
| `change_pct` | float | 涨跌幅 (%) |
| `change_amt` | float | 涨跌额 |
| `volume` | float | 成交量 |
| `amount` | float | 成交额 |
| `prev_close` | float | 昨收 |
| `open` | float | 今开 |
| `high` | float | 最高 |
| `low` | float | 最低 |

> 原始数据源返回中文列名（`代码`、`名称`、`最新价` 等），归一化后统一为英文 snake_case。详见[统一接口蒸馏文档](unified-interface-distillation.md#endpoint-stock_cn_spot)。

### 历史行情

`GET /api/public/v1/stock_cn_hist`

| 参数 | 默认值 | 说明 |
| ----- | ----- | ----- |
| `symbol` | (必填) | 如 `600000` 或 `sh600000` |
| `source` | `auto` | `eastmoney` / `sina` / `tencent` / `auto` |
| `start_date` | `19900101` | |
| `end_date` | `20500101` | |
| `adjust` | `""` | `qfq` / `hfq` |

> `source=auto` 按优先级自动选择可用数据源，含熔断保护。详见[数据源差异与归一化](source-differences.md)。
>
> 统一输出 6 字段：`date`, `open`, `high`, `low`, `close`, `volume`（成交量单位：股）。

### 分时行情

`GET /api/public/v1/stock_cn_hist_intraday`

| 参数 | 默认值 | 说明 |
| ----- | ----- | ----- |
| `symbol` | (必填) | |
| `source` | `auto` | `eastmoney` / `sina` / `auto`（sina 仅当日数据） |
| `period` | `5` | 1 / 5 / 15 / 30 / 60 |
| `start_date` | — | 仅 eastmoney |
| `end_date` | — | 仅 eastmoney |
| `adjust` | `""` | |

**返回字段**（统一归一化，6 字段）：

| 字段 | 类型 | 含义 |
| ----- | ----- | ----- |
| `time` | string | 时间 |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `close` | float | 收盘价 |
| `volume` | float | 成交量 |

> `source=auto` 按优先级尝试数据源（含熔断保护）。Sina 仅支持当日数据，历史日期自动回退到 eastmoney。详见[统一接口蒸馏文档](unified-interface-distillation.md#endpoint-stock_cn_hist_intraday)。

### 搜索

`GET /api/public/v1/stock_cn_search?q=浦发&limit=20`

### 个股档案

`GET /api/public/v1/stock_profile?symbol=600000`

返回行业与概念板块归属。

---

## 美股 (US)

### 列表

`GET /api/public/v1/stock_us_list` (分页参数同上)

### 实时行情

`GET /api/public/v1/stock_us_spot` — eastmoney 源，`?symbol=AAPL`

### 历史行情

`GET /api/public/v1/stock_us_hist`

| 参数 | 说明 |
| ----- | ----- |
| `symbol` | `AAPL` (sina) / `105.MSFT` (eastmoney) |
| `source` | `eastmoney` / `sina` / `auto` |

**返回字段**（统一归一化，6 字段，与 `stock_cn_hist` 相同）：

| 字段 | 类型 | 含义 |
| ----- | ----- | ----- |
| `date` | string | 交易日期 |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `close` | float | 收盘价 |
| `volume` | float | 成交量 |

> 详见[统一接口蒸馏文档](unified-interface-distillation.md#endpoint-stock_us_hist_universal)。

### 搜索

`GET /api/public/v1/stock_us_search?q=AAPL`

---

## 港股 (HK)

### 列表

`GET /api/public/v1/stock_hk_list` — 港股通成份股

### 实时行情

`GET /api/public/v1/stock_hk_spot`

| 参数 | 说明 |
| ----- | ----- |
| `source` | `eastmoney` / `sina` / `auto` |
| `symbol` | 如 `00700` |

**返回字段**（统一归一化，与数据源无关）：

| 字段 | 类型 | 含义 |
| ----- | ----- | ----- |
| `code` | string | 股票代码 |
| `latest` | float | 最新价 |
| `change_amt` | float | 涨跌额 |
| `change_pct` | float | 涨跌幅 (%) |
| `prev_close` | float | 昨收 |
| `open` | float | 今开 |
| `high` | float | 最高 |
| `low` | float | 最低 |
| `volume` | float | 成交量 |
| `amount` | float | 成交额 |

> 详见[统一接口蒸馏文档](unified-interface-distillation.md#endpoint-stock_hk_spot_universal)。

### 历史行情

`GET /api/public/v1/stock_hk_hist?symbol=00700`

| 参数 | 说明 |
| ----- | ----- |
| `source` | `eastmoney` / `sina` / `auto` |

**返回字段**（统一归一化，6 字段，与 `stock_cn_hist` 相同）：

| 字段 | 类型 | 含义 |
| ----- | ----- | ----- |
| `date` | string | 交易日期 |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `close` | float | 收盘价 |
| `volume` | float | 成交量 |

> 详见[统一接口蒸馏文档](unified-interface-distillation.md#endpoint-stock_hk_hist)。

### 搜索

`GET /api/public/v1/stock_hk_search?q=00700`

---

## 基金 (Fund)

### 全部基金列表

`GET /api/public/v1/fund_list` (分页)

### ETF

| 端点 | 类型 |
| ----- | ----- |
| `GET /api/public/v1/fund_etf_spot` | 实时行情，60s 缓存 |
| `GET /api/public/v1/fund_etf_hist` | 历史，`?source=eastmoney/sina/auto` |

**返回字段**（统一归一化，6 字段）：`date`, `open`, `high`, `low`, `close`, `volume`。详见[统一接口蒸馏文档](unified-interface-distillation.md#endpoint-fund_etf_hist_universal)。
| `GET /api/public/v1/fund_etf_hist_intraday` | 分时，eastmoney 源 |

### LOF

| 端点 | 类型 |
| ----- | ----- |
| `GET /api/public/v1/fund_lof_spot` | 实时行情 |
| `GET /api/public/v1/fund_lof_hist` | 历史 |
| `GET /api/public/v1/fund_lof_hist_intraday` | 分时 |

### 场外基金

| 端点 | 类型 |
| ----- | ----- |
| `GET /api/public/v1/fund_open_list` | 列表 + 最新净值 |
| `GET /api/public/v1/fund_portfolio` | 基金持仓（最新季报），`?symbol=009568` |
| `GET /api/public/v1/fund_est_nav` | 实时估值，`?symbol=009568` → 基于持仓+实时行情估算净值 |
| `GET /api/public/v1/fund_open_hist` | 历史净值，`?symbol=710001&indicator=单位净值走势` |

### 搜索

`GET /api/public/v1/fund_search?q=华夏` — 全部基金
`GET /api/public/v1/fund_open_search?q=永赢` — 场外基金

---

## 可转债 (Convertible Bond)

| 端点 | 类型 |
| ----- | ----- |
| `GET /api/public/v1/bond_cov_list` | 列表，每日缓存 |
| `GET /api/public/v1/bond_cov_spot` | 实时行情，60s 缓存 |
| `GET /api/public/v1/bond_cov_hist` | 历史，`?symbol=sh010107` |
| `GET /api/public/v1/bond_cov_search` | 搜索 |

---

## 期货 (Futures)

| 端点 | 类型 |
| ----- | ----- |
| `GET /api/public/v1/futures_spot` | 国际期货实时行情，60s 缓存 |
| `GET /api/public/v1/futures_hist` | 历史，`?symbol=HG00Y` |

---

## 指数 (Index)

| 端点 | 类型 |
| ----- | ----- |
| `GET /api/public/v1/index_list` | 全球指数列表，每日缓存 |
| `GET /api/public/v1/index_spot` | 实时行情，60s 缓存 |
| `GET /api/public/v1/index_hist` | 历史，`?symbol=OMX&source=sina` |\n\n> ⚠️ 指数端点不归一化：eastmoney 和 sina 覆盖不同市场的指数（无符号交集），`source` 参数是市场选择器而非冗余机制。详见[统一接口蒸馏文档](unified-interface-distillation.md#endpoint-index_hist)。
| `GET /api/public/v1/index_search` | 搜索 |

---

## 板块 (Board/Sector)

### 行业板块

| 端点 | 类型 |
| ----- | ----- |
| `GET /api/public/v1/board_industry_list` | 列表 |
| `GET /api/public/v1/board_industry_spot?symbol=半导体` | 实时 |
| `GET /api/public/v1/board_industry_hist?symbol=元件` | 历史 |

### 概念板块

| 端点 | 类型 |
| ----- | ----- |
| `GET /api/public/v1/board_concept_list` | 列表 |
| `GET /api/public/v1/board_concept_spot?symbol=元宇宙` | 实时 |
| `GET /api/public/v1/board_concept_hist?symbol=阿里巴巴概念` | 历史 |

---

## 管理接口

### 公开

| 端点 | 说明 |
| ----- | ----- |
| `GET /api/public/v1/cache_status` | 缓存状态 |
| `GET /api/public/v1/default_source` | 当前默认数据源 |

### 需认证

| 端点 | 方法 | 说明 |
| ----- | ----- | ----- |
| `/api/private/v1/default_source` | POST | 切换默认源 |
| `/api/private/v1/cache/pause` | POST | 暂停缓存 (`?keys=a,b`) |
| `/api/private/v1/cache/resume` | POST | 恢复缓存 |
| `/api/private/v1/tokens` | GET/POST/DELETE | Token CRUD |

---

## 通用参数

| 参数 | 默认值 | 说明 |
| ----- | ----- | ----- |
| `source` | `eastmoney` | 数据源 |
| `page` | `0` | 0=不分页 |
| `page_size` | `100` | 最大 1000 |
| `q` | (必填) | 搜索关键词，子串匹配 |
| `limit` | `20` | 搜索结果数，0=不限制 |

## 错误码

| 状态码 | 含义 |
| :---: | ----- |
| 200 | 成功 |
| 400 | 参数错误 |
| 401 | 未认证 |
| 404 | 数据不存在 |
| 502 | 上游数据源故障（已重试 3 次） |
| 503 | 缓存预热中 |
