# V1 API

AKTools v0.1.3 — 44 endpoints across 10 categories, smart caching, multi-source switching.

---

## 环境变量

| 变量 | 用途 | 默认值 |
| ----- | ----- | ----- |
| `AKSHARE_PROXY` | HTTP/HTTPS 代理地址 | 无 |
| `AKSHARE_DEFAULT_SOURCE` | 默认数据源 | `eastmoney` |
| `AKTOOLS_TOKENS_FILE` | 预配置 Token JSON 文件路径 | 无 |
| `AKTOOLS_DATA_DIR` | 持久化数据目录 | `./data/` |
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
| `source` | `eastmoney` | `eastmoney` / `sina` |
| `symbol` | 空 (全市场) | 个股代码筛选 |

### 历史行情

`GET /api/public/v1/stock_cn_hist`

| 参数 | 默认值 | 说明 |
| ----- | ----- | ----- |
| `symbol` | (必填) | 如 `600000` 或 `sh600000` |
| `source` | `eastmoney` | `eastmoney` / `sina` / `tencent` |
| `start_date` | `19900101` | |
| `end_date` | `20500101` | |
| `adjust` | `""` | `qfq` / `hfq` |

### 分时行情

`GET /api/public/v1/stock_cn_hist_intraday`

| 参数 | 默认值 | 说明 |
| ----- | ----- | ----- |
| `symbol` | (必填) | |
| `source` | `eastmoney` | `sina` (当日) / `eastmoney` (历史) |
| `period` | `5` | 1 / 5 / 15 / 30 / 60 |
| `start_date` | — | 仅 eastmoney |
| `end_date` | — | 仅 eastmoney |
| `adjust` | `""` | |

> `source=sina` 仅返回当日数据；历史日期自动回退到 `eastmoney`。

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
| `source` | `eastmoney` / `sina` |

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
| `source` | `eastmoney` / `sina` |
| `symbol` | 如 `00700` |

### 历史行情

`GET /api/public/v1/stock_hk_hist?symbol=00700&source=sina`

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
| `GET /api/public/v1/fund_etf_hist` | 历史，`?source=eastmoney/sina` |
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
| `GET /api/public/v1/index_hist` | 历史，`?symbol=OMX&source=sina` |
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
