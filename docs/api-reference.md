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
| `/api/public/stock_zh_a_hist?symbol=600000` | `ak.stock_zh_a_hist(symbol="600000")` |
| `/api/public/stock_zh_ah_daily?symbol=600000&start_date=20240101&end_date=20241231` | `ak.stock_zh_ah_daily(symbol="600000", start_date="20240101", end_date="20241231")` |
| `/api/public/stock_zh_a_spot_em` | `ak.stock_zh_a_spot_em()` |

**示例**

```sh
# A 股历史行情（东方财富）
curl "http://127.0.0.1:8080/api/public/stock_zh_a_hist?symbol=600000&period=daily&start_date=20240101&end_date=20241231&adjust=qfq"

# A 股实时行情
curl "http://127.0.0.1:8080/api/public/stock_zh_a_spot_em"

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

行为与公开接口一致，但需要 Bearer Token 认证（见下方[认证](#认证)章节）。

---

## 数据接口 — V1 版本化

### 统一 A 股历史行情

`GET /api/public/v1/stock_zh_a_hist`

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
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_hist?symbol=600000&source=sina"

# 指定日期 + 前复权
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_hist?symbol=000001&source=tencent&start_date=20240101&end_date=20241231&adjust=qfq"
```

### 统一 A 股实时行情

`GET /api/public/v1/stock_zh_a_spot`

返回全市场实时行情，支持按个股代码筛选。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `source` | 否 | `eastmoney` | 数据源：`eastmoney` / `sina` |
| `symbol` | 否 | 空（全市场） | 股票代码筛选，如 `600000` 或 `sh600000` |

```sh
# 全市场实时行情（Sina 源）
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_spot?source=sina"

# 筛选单只股票
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_spot?symbol=600000"
```

!!! note
    `tencent` 不适用于实时行情接口，当前仅支持 `eastmoney` 和 `sina`。
    若默认源设为 `tencent`，实时行情接口需显式传 `?source=sina` 或 `?source=eastmoney`。
    实时行情数据由后台线程缓存（每 60 秒刷新），请求直接从内存返回，响应时间 <10ms。

### A 股股票列表

`GET /api/public/v1/stock_list`

返回沪深京全部 A 股代码与名称，数据由后台缓存，响应 <10ms。

```sh
curl "http://127.0.0.1:8080/api/public/v1/stock_list"
```

响应示例：

```json
[
  {"代码": "000001", "名称": "平安银行"},
  {"代码": "000002", "名称": "万科A"},
  {"代码": "600000", "名称": "浦发银行"}
]
```

---

## 数据接口 — V1 基金/ETF

### 基金列表

`GET /api/public/v1/fund_list`

返回全部基金代码、简称与类型，数据由后台缓存（每日刷新），响应 <10ms。

```sh
curl "http://127.0.0.1:8080/api/public/v1/fund_list"
```

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

```sh
# ETF 历史数据（Sina 源）
curl "http://127.0.0.1:8080/api/public/v1/fund_etf_hist?symbol=sh510050&source=sina"
```

### 搜索接口

`GET /api/public/v1/stock_search` — 股票代码/名称模糊搜索

`GET /api/public/v1/fund_search` — 基金代码/名称模糊搜索

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `q` | 是 | — | 搜索关键词，子串匹配代码或名称 |
| `limit` | 否 | `20` | 最大返回条数，`0`=不限制 |

```sh
# 搜索股票
curl "http://127.0.0.1:8080/api/public/v1/stock_search?q=浦发&limit=5"

# 搜索基金
curl "http://127.0.0.1:8080/api/public/v1/fund_search?q=华夏&limit=0"
```

响应包含 `X-Total-Count` 头部，数据来自缓存，<10ms。

### 缓存控制

`POST /api/public/v1/cache/pause` — 暂停后台自动刷新

`POST /api/public/v1/cache/resume` — 恢复后台自动刷新

`GET /api/public/v1/cache_status` — 查看缓存状态

```sh
# 暂停
curl -X POST "http://127.0.0.1:8080/api/public/v1/cache/pause"

# 恢复
curl -X POST "http://127.0.0.1:8080/api/public/v1/cache/resume"

# 查看状态
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

`POST /api/public/v1/default_source?source=<name>` — 运行时切换

```sh
# 查看
curl http://127.0.0.1:8080/api/public/v1/default_source
# → {"default_source":"eastmoney","available":["eastmoney","sina","tencent"]}

# 切换为 Sina（即时生效，无需重启）
curl -X POST "http://127.0.0.1:8080/api/public/v1/default_source?source=sina"
# → {"default_source":"sina","previous":"eastmoney"}
```

切换后，V1 历史接口不传 `?source=` 时将使用新默认值。

---

## 认证

AKTools 使用 OAuth2 Password Bearer 流程（当前为简化实现）。

### 获取 Token

`POST /auth/token`

Content-Type: `application/x-www-form-urlencoded`

| 参数 | 值 |
| ----- | ----- |
| `username` | `akshare` |
| `password` | `akfamily` |

```sh
curl -X POST "http://127.0.0.1:8080/auth/token" \
  -d "username=akshare&password=akfamily"
# → {"access_token":"akshare","token_type":"bearer"}
```

### 使用 Token 访问私有接口

```sh
curl -H "Authorization: Bearer akshare" \
  "http://127.0.0.1:8080/api/private/stock_zh_a_hist?symbol=600000"
```

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
