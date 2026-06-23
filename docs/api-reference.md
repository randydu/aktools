# HTTP API Reference

所有接口返回 JSON（除特别标注外）。基础地址 `http://127.0.0.1:8080`。

---

## 系统接口

### 首页

`GET /`

返回 AKTools 主页 HTML，显示当前版本及快速跳转链接。

### 版本信息

`GET /version`

```json
{
  "ak_current_version": "1.15.25",
  "at_current_version": "0.0.91",
  "ak_latest_version": "1.15.90",
  "at_latest_version": "0.0.91"
}
```

---

## 数据接口 — 通用代理

### 公开接口

`GET /api/public/{item_id}`

将 URL 路径中的 `{item_id}` 映射为 `akshare.{item_id}()` 调用，
查询参数映射为函数的关键字参数。

**参数传递规则** — `?key=value` 直接转为 `key="value"`：

| 请求 | AKShare 调用 |
| ----- | ----- |
| `/api/public/stock_cn_hist?symbol=600000` | `ak.stock_cn_hist(symbol="600000")` |
| `/api/public/stock_zh_ah_daily?symbol=600000&start_date=20240101&end_date=20241231` | `ak.stock_zh_ah_daily(symbol="600000", start_date="20240101", end_date="20241231")` |
| `/api/public/stock_cn_spot_em` | `ak.stock_cn_spot_em()` |

**示例**

```sh
# A 股历史行情（东方财富）
curl "http://127.0.0.1:8080/api/public/stock_cn_hist?symbol=600000&period=daily&start_date=20240101&end_date=20241231&adjust=qfq"

# A 股实时行情
curl "http://127.0.0.1:8080/api/public/stock_cn_spot_em"

# 期货历史数据
curl "http://127.0.0.1:8080/api/public/futures_main_sina?symbol=V0&start_date=20240101&end_date=20241231"

# 基金历史净值
curl "http://127.0.0.1:8080/api/public/fund_etf_hist_sina?symbol=sz159915"

# 美股历史数据
curl "http://127.0.0.1:8080/api/public/stock_us_daily?symbol=AAPL&start_date=20240101&end_date=20241231"

# 港股历史数据
curl "http://127.0.0.1:8080/api/public/stock_hk_daily?symbol=00700&start_date=20240101&end_date=20241231"
```

**响应格式**

```json
[
  {
    "日期": "2024-01-02",
    "开盘": 6.53,
    "收盘": 6.48,
    "最高": 6.55,
    "最低": 6.45,
    "成交量": 523456,
    "成交额": 3398765432.0,
    "振幅": 1.53,
    "涨跌幅": -0.76,
    "涨跌额": -0.05,
    "换手率": 0.27
  }
]
```

!!! note "可用接口列表"
    `{item_id}` 可取 AKShare 中任意公开函数名。
    完整列表见 [AKShare 文档](https://akshare.akfamily.xyz/)。
    也可通过 Swagger UI 浏览：`http://127.0.0.1:8080/docs`

### 私有接口

`GET /api/private/{item_id}`（需要认证）

行为与公开接口一致，但需要 Bearer Token 认证（见下方[认证](#auth)章节）。

---

## 数据接口 — V1 板块

### 行业板块列表

`GET /api/public/v1/board_industry_list` — 每日缓存，A 股行业板块名称

### 概念板块列表

`GET /api/public/v1/board_concept_list` — 每日缓存，A 股概念板块名称

### 行业板块行情

`GET /api/public/v1/board_industry_spot?symbol=半导体`

### 概念板块行情

`GET /api/public/v1/board_concept_spot?symbol=元宇宙`

### 行业板块历史指数

`GET /api/public/v1/board_industry_hist?symbol=元件&start_date=20240101&end_date=20250101`

### 概念板块历史指数

`GET /api/public/v1/board_concept_hist?symbol=阿里巴巴概念`

---

## 数据接口 — V1 可转债

### 可转债列表

`GET /api/public/v1/bond_cov_list`

返回可转债代码、名称与核心指标（转股价、溢价率等），数据由后台缓存（每日刷新），支持分页。

### 可转债实时行情

`GET /api/public/v1/bond_cov_spot`

返回可转债实时行情，数据由后台缓存（60s 刷新），支持 `?symbol=sh123121` 筛选。

### 可转债历史行情

`GET /api/public/v1/bond_cov_hist?symbol=sh010107`

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | 可转债代码（新浪格式），如 `sh010107` |

---

## 数据接口 — V1 期货

### 期货实时行情

`GET /api/public/v1/futures_spot`

返回国际期货实时行情，数据由后台缓存（60s 刷新），支持 `?symbol=HG00Y` 筛选。

### 期货历史行情

`GET /api/public/v1/futures_hist?symbol=HG00Y`

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | 期货代码，如 `HG00Y` |
| `start_date` | 否 | `19700101` | 开始日期 |
| `end_date` | 否 | `22220101` | 结束日期 |

---

## 数据接口 — V1 指数

### 指数列表

`GET /api/public/v1/index_list`

返回全球指数代码与名称，数据由后台缓存（每日刷新），支持分页。

### 指数实时行情

`GET /api/public/v1/index_spot`

返回全球指数实时行情，缓存 <10ms，支持 `?symbol=OMX` 筛选。

### 指数历史行情

`GET /api/public/v1/index_hist?symbol=OMX&source=sina`

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | 指数代码，如 `OMX` 或 `美元指数` |
| `source` | 否 | `eastmoney` | `eastmoney` / `sina` |

---

## 数据接口 — V1 港股

### 港股列表

`GET /api/public/v1/stock_hk_list`

返回港股通成份股，数据由后台缓存（每日刷新），支持分页。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `page` | 否 | `0`（不分页） | 页码，1-based |
| `page_size` | 否 | `100` | 每页条数，最大 1000 |

### 港股实时行情

`GET /api/public/v1/stock_hk_spot`

支持切换数据源（eastmoney / sina），可筛选个股，缓存 + 回退。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `source` | 否 | `eastmoney` | `eastmoney` / `sina` |
| `symbol` | 否 | 空（全市场） | 港股代码筛选，如 `00700` |

### 港股历史行情

`GET /api/public/v1/stock_hk_hist?symbol=00700&source=sina`

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | 港股代码，如 `00700` |
| `source` | 否 | `eastmoney` | `eastmoney` / `sina` |
| `start_date` | 否 | `19700101` | 开始日期 YYYYMMDD |
| `end_date` | 否 | `22220101` | 结束日期 YYYYMMDD |
| `adjust` | 否 | `""` | 复权类型 |

---

## 数据接口 — V1 美股

### 美股列表

`GET /api/public/v1/stock_us_list`

返回美股代码与名称，数据由后台缓存（每日刷新），响应 <10ms。支持分页。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `page` | 否 | `0`（不分页） | 页码，1-based |
| `page_size` | 否 | `100` | 每页条数，最大 1000 |

```sh
curl "http://127.0.0.1:8080/api/public/v1/stock_us_list?page=1&page_size=50"
```

### 美股实时行情

`GET /api/public/v1/stock_us_spot`

返回美股实时行情，支持按代码筛选，数据由后台缓存（60s 刷新）。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 否 | 空（全市场） | 美股代码筛选，如 `AAPL` |

```sh
curl "http://127.0.0.1:8080/api/public/v1/stock_us_spot?symbol=AAPL"
```

### 美股历史行情

`GET /api/public/v1/stock_us_hist`

支持切换数据源（eastmoney / sina），带自动重试。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | 美股代码，如 `AAPL` 或 `105.MSFT` |
| `source` | 否 | `eastmoney` | `eastmoney` / `sina` |
| `start_date` | 否 | `19700101` | 开始日期 YYYYMMDD |
| `end_date` | 否 | `22220101` | 结束日期 YYYYMMDD |
| `adjust` | 否 | `""` | 复权类型 |

```sh
# Sina 源（简洁代码）
curl "http://127.0.0.1:8080/api/public/v1/stock_us_hist?symbol=AAPL&source=sina"

# East Money 源（交易所前缀代码）
curl "http://127.0.0.1:8080/api/public/v1/stock_us_hist?symbol=105.MSFT&source=eastmoney"
```

---

## 数据接口 — V1 版本化

### 统一 A 股历史行情

`GET /api/public/v1/stock_cn_hist`

单个接口覆盖三个数据源，自动转换符号格式。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | 股票代码，如 `600000` 或 `sh600000` |
| `source` | 否 | `eastmoney` | 数据源：`eastmoney` / `sina` / `tencent` |
| `start_date` | 否 | `19900101` | 开始日期 YYYYMMDD |
| `end_date` | 否 | `20500101` | 结束日期 YYYYMMDD |
| `adjust` | 否 | `""` | 复权：`""`=不复权, `qfq`=前复权, `hfq`=后复权 |

**数据源对比**

| 值 | 上游 | 海外可用 |
| ----- | ----- | :---: |
| `eastmoney` | 东方财富 (East Money) | 可能受限 |
| `sina` | 新浪财经 (Sina) | :white_check_mark: 好 |
| `tencent` | 腾讯证券 (Tencent) | :white_check_mark: 好 |

```sh
# Sina 源（推荐海外用户）
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_hist?symbol=600000&source=sina"

# 指定日期 + 前复权
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_hist?symbol=000001&source=tencent&start_date=20240101&end_date=20241231&adjust=qfq"
```

### A 股分时行情

`GET /api/public/v1/stock_cn_hist_intraday`

分钟级 K 线，支持双数据源。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | 股票代码，如 `000001` 或 `sh600519` |
| `source` | 否 | `eastmoney` | `eastmoney` / `sina`（海外推荐 sina） |
| `period` | 否 | `5` | 分时周期: 1, 5, 15, 30, 60 |
| `start_date` | 否 | `1979-09-01 09:32:00` | 开始时间（仅 eastmoney） |
| `end_date` | 否 | `2222-01-01 09:32:00` | 结束时间（仅 eastmoney） |
| `adjust` | 否 | `""` | 复权类型 |

```sh
# Sina 源（海外推荐，仅返回最近交易日数据）
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_hist_intraday?symbol=sh600519&source=sina&period=1"

# East Money 源（支持日期范围）
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_hist_intraday?symbol=000001&period=5&start_date=2024-06-01 09:30:00"
```

!!! note "Sina 源限制"
    `source=sina` 仅返回最近一个交易日的数据。若请求的 `start_date` 不是今天，
    接口自动回退到 `eastmoney` 源，无需手动切换。

### 统一 A 股实时行情

`GET /api/public/v1/stock_cn_spot`

返回全市场实时行情，支持按个股代码筛选。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `source` | 否 | `eastmoney` | 数据源：`eastmoney` / `sina` |
| `symbol` | 否 | 空（全市场） | 股票代码筛选，如 `600000` 或 `sh600000` |

```sh
# 全市场实时行情（Sina 源）
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_spot?source=sina"

# 筛选单只股票
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_spot?symbol=600000"
```

!!! note
    `tencent` 不适用于实时行情接口，当前仅支持 `eastmoney` 和 `sina`。
    若默认源设为 `tencent`，实时行情接口需显式传 `?source=sina` 或 `?source=eastmoney`。
    实时行情数据由后台线程缓存（每 60 秒刷新），请求直接从内存返回，响应时间 <10ms。

### A 股股票列表

`GET /api/public/v1/stock_cn_list`

返回沪深京全部 A 股代码与名称，数据由后台缓存，响应 <10ms。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `page` | 否 | `0`（不分页） | 页码，1-based |
| `page_size` | 否 | `100` | 每页条数，最大 1000 |

```sh
# 第一页，每页 50 条
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_list?page=1&page_size=50"

# 不分页（返回全部）
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_list"
```

响应包含 `X-Total-Count` 头部，示例：

```json
[
  {"code": "000001", "name": "平安银行"},
  {"code": "000002", "name": "万科A"},
  {"code": "600000", "name": "浦发银行"}
]
```

---

## 数据接口 — V1 基金/ETF

### 基金列表

`GET /api/public/v1/fund_list`

返回全部基金代码、简称与类型，数据由后台缓存（每日刷新），响应 <10ms。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `page` | 否 | `0`（不分页） | 页码，1-based |
| `page_size` | 否 | `100` | 每页条数，最大 1000 |

```sh
# 第一页，每页 50 条
curl "http://127.0.0.1:8080/api/public/v1/fund_list?page=1&page_size=50"
```

响应包含 `X-Total-Count` 头部，列出基金代码、简称与类型。

### ETF 实时行情

`GET /api/public/v1/fund_etf_spot`

返回 ETF 实时行情，支持按代码筛选，数据由后台缓存（60s 刷新）。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 否 | 空（全市场） | ETF 代码筛选，如 `159915` |

```sh
# 全市场 ETF 行情
curl "http://127.0.0.1:8080/api/public/v1/fund_etf_spot"

# 筛选单只 ETF
curl "http://127.0.0.1:8080/api/public/v1/fund_etf_spot?symbol=159915"
```

### LOF 实时行情

`GET /api/public/v1/fund_lof_spot`

返回 LOF 实时行情，数据由后台缓存（60s 刷新），支持 `?symbol=166009` 筛选。

### LOF 历史行情

`GET /api/public/v1/fund_lof_hist?symbol=166009`

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | LOF 代码，如 `166009` |
| `period` | 否 | `daily` | daily / weekly / monthly |
| `start_date` | 否 | `19700101` | 开始日期 |
| `end_date` | 否 | `20500101` | 结束日期 |
| `adjust` | 否 | `""` | 复权类型 |

### 场外基金列表

`GET /api/public/v1/fund_open_list`

返回全部开放式基金及最新净值，数据由后台缓存（每日刷新），支持分页。

### 场外基金历史净值

`GET /api/public/v1/fund_open_hist?symbol=710001`

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | 基金代码，如 `710001` |
| `indicator` | 否 | `单位净值走势` | 单位净值走势 / 累计净值走势 |
| `period` | 否 | `成立来` | 成立来 / 近1年 / 近6月 / 近3月 / 近1月 |

### ETF 历史行情

`GET /api/public/v1/fund_etf_hist`

支持切换数据源（eastmoney / sina），带自动重试。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `symbol` | 是 | — | ETF 代码，如 `159915` 或 `sh510050` |
| `source` | 否 | `eastmoney` | `eastmoney` / `sina` |
| `start_date` | 否 | `19700101` | 开始日期 YYYYMMDD |
| `end_date` | 否 | `20500101` | 结束日期 YYYYMMDD |
| `adjust` | 否 | `""` | 复权类型 |

### ETF 分时行情

`GET /api/public/v1/fund_etf_hist_intraday?symbol=159707&period=5`

### LOF 分时行情

`GET /api/public/v1/fund_lof_hist_intraday?symbol=166009&period=5`

分钟级 K 线，仅东方财富源，支持 `start_date` / `end_date`。

### 个股档案

`GET /api/public/v1/stock_profile?symbol=600000`

返回个股的行业与概念板块归属，数据由后台缓存（每日刷新）。

### 搜索接口

### 搜索接口

所有搜索基于缓存列表，子串匹配代码或名称（大小写不敏感），响应 <10ms，含 `X-Total-Count` 头部。

| 端点 | 搜索范围 |
| ----- | ----- |
| `/api/public/v1/stock_cn_search` | A 股代码/名称 |
| `/api/public/v1/stock_us_search` | 美股代码/名称 |
| `/api/public/v1/stock_hk_search` | 港股代码/名称 |
| `/api/public/v1/fund_search` | 基金代码/简称 |
| `/api/public/v1/fund_open_search` | 场外基金代码/简称 |
| `/api/public/v1/stock_hk_search` | 港股代码/名称 |
| `/api/public/v1/bond_cov_search` | 可转债代码/简称 |
| `/api/public/v1/index_search` | 全球指数名称/代码 |

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `q` | 是 | — | 搜索关键词，子串匹配 |
| `limit` | 否 | `20` | 最大返回条数，`0`=不限制 |

```sh
# 搜索股票
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_search?q=浦发&limit=5"

# 搜索基金
curl "http://127.0.0.1:8080/api/public/v1/fund_search?q=华夏&limit=0"

# 搜索指数
curl "http://127.0.0.1:8080/api/public/v1/index_search?q=恒生"
```

### 缓存控制

`POST /api/private/v1/cache/pause` — 暂停后台自动刷新

`POST /api/private/v1/cache/resume` — 恢复后台自动刷新

`GET /api/public/v1/cache_status` — 查看缓存状态

```sh
# 暂停（需要认证）
curl -X POST "http://127.0.0.1:8080/api/private/v1/cache/pause" \
  -H "Authorization: Bearer <token>"

# 恢复（需要认证）
curl -X POST "http://127.0.0.1:8080/api/private/v1/cache/resume" \
  -H "Authorization: Bearer <token>"

# 查看状态（公开，无需认证）
curl "http://127.0.0.1:8080/api/public/v1/cache_status"
```

缓存状态响应：

```json
{
  "warm": true,
  "paused": false,
  "market_open": true,
  "caches": { ... }
}
```

#### 智能刷新策略

| 时段 | 刷新间隔 | 说明 |
| ----- | :---: | ----- |
| A 股交易时段 (Mon-Fri 9:30-11:30, 13:00-15:00 CST) | 60s | 活跃刷新 |
| 非交易时段 / 周末 | 300s | 低频刷新 |

#### 数据新鲜度

实时行情接口在响应头中返回新鲜度信息：

```
X-Cache-Age: 85
X-Cache-Stale: true              # 仅交易时段 age > 120s 时出现
Warning: 110 - "Response is Stale (age=85s)"
```

客户端可检查 `X-Cache-Stale` 头决定是否重试或显示时效提示。过期数据仍然返回，不会阻塞请求。

### 默认数据源管理

`GET /api/public/v1/default_source` — 查看当前默认源

`POST /api/private/v1/default_source?source=<name>` — 切换（需要认证）

```sh
# 查看（无需认证）
curl http://127.0.0.1:8080/api/public/v1/default_source
# → {"default_source":"eastmoney","available":["eastmoney","sina","tencent"]}

# 切换为 Sina（需要认证）
curl -X POST "http://127.0.0.1:8080/api/private/v1/default_source?source=sina" \
  -H "Authorization: Bearer <token>"
# → {"default_source":"sina","previous":"eastmoney"}
```

切换后，V1 历史接口不传 `?source=` 时将使用新默认值。

---

<a id="auth"></a>

## 认证

AKTools 使用 **API Token** 认证（SQLite 持久化）。

### 首次启动

服务器首次启动时，若 `tokens.db` 为空，会自动创建一个 root token 并打印到日志：

```
============================================================
 ROOT API TOKEN (shown once): akt_f1f22e9bbf...
 Save this token — it's required to manage other tokens.
============================================================
```

### 预配置 Token 文件

通过 JSON 文件预置 Token（由文件系统权限保护）：

```json
[
  {"token": "akt_...", "user_name": "myapp"},
  {"token": "akt_...", "user_name": "monitoring"}
]
```

```sh
# 设置文件权限
chmod 600 /etc/aktools/tokens.json

# 通过环境变量指定
AKTOOLS_TOKENS_FILE=/etc/aktools/tokens.json python -m aktools
```

服务启动时自动导入，已存在的 Token 跳过。若文件提供了至少一个 Token，则不自动创建 root token。

### API Token 管理

`POST /api/private/v1/tokens` — 创建 Token（仅返回一次）

`GET /api/private/v1/tokens` — 列出所有 Token（不含完整 Token）

`DELETE /api/private/v1/tokens?token=<full>` — 撤销 Token

```sh
# 创建 Token（需要认证）
curl -X POST "http://127.0.0.1:8080/api/private/v1/tokens?user=myapp" \
  -H "Authorization: Bearer <root-token>"
# → {"token":"akt_a1b2c3d4...","user_name":"myapp"}

# 列出 Token
curl "http://127.0.0.1:8080/api/private/v1/tokens" \
  -H "Authorization: Bearer <root-token>"

# 撤销 Token
curl -X DELETE "http://127.0.0.1:8080/api/private/v1/tokens?token=akt_a1b2c3d4..." \
  -H "Authorization: Bearer <root-token>"
```

使用 Token 访问私有接口：

```sh
curl -H "Authorization: Bearer akt_a1b2c3d4..." \
  "http://127.0.0.1:8080/api/private/stock_cn_hist?symbol=600000"
```

Token 存储在 `aktools/tokens.db`（SQLite），服务器重启后依然有效。

### 使用 Token 访问私有接口

```sh
curl -H "Authorization: Bearer akt_..." \
  "http://127.0.0.1:8080/api/private/stock_cn_hist?symbol=600000"
```

!!! note "旧凭据已废弃"
    原有的 `akshare`/`akfamily` 用户名密码登录已禁用。
    `POST /auth/token` 返回 410，引导用户使用 API Token。

---

## 辅助接口

### PyScript 演示

`GET /api/show` — 返回 PyScript 交互页面 HTML

`GET /api/show-temp/{interface}` — 为指定接口生成 PyScript 模板页面

---

## 错误码

| 状态码 | 含义 |
| :---: | ----- |
| 200 | 成功 |
| 400 | 请求参数错误（如不支持的 `source`） |
| 401 | 未认证或 Token 无效 |
| 404 | 接口不存在或返回数据为空 |
| 500 | 服务器内部错误 |
| 502 | 上游数据源连接失败（已自动重试 3 次） |

---


## 配置

通过环境变量控制行为：

| 变量 | 用途 | 默认值 |
| ----- | ----- | ----- |
| `AKSHARE_PROXY` | HTTP/HTTPS 代理，如 `http://127.0.0.1:7890` | 无 |
| `AKSHARE_DEFAULT_SOURCE` | V1 历史接口默认数据源 | `eastmoney` |
| `AKTOOLS_TOKENS_FILE` | 预配置 Token 的 JSON 文件路径 | 无 |
| `AKTOOLS_DATA_DIR` | 持久化数据目录（缓存、日志、Token），默认 `./data/` | `./data/` |
| `AKTOOLS_LOG_LEVEL` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |
