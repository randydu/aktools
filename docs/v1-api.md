# V1 API

AKTools v0.1.0 版本化 API — 30+ 端点覆盖十大品类，智能缓存引擎，多数据源切换。

---

## 代理配置

通过环境变量 `AKSHARE_PROXY` 为所有 AKShare 请求设置 HTTP/HTTPS 代理，
适用于海外用户或需要通过代理访问国内数据源的场景。

```sh
# 启动时设置代理
AKSHARE_PROXY=http://127.0.0.1:7890 python -m aktools

# Docker
docker run -e AKSHARE_PROXY=http://your-proxy:port ...
```

---

## 统一 A 股历史行情接口

`GET /api/public/v1/stock_cn_hist`

单个接口覆盖三个数据源，`symbol` 格式统一（有无交易所前缀均可自动转换）。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | ----- | ----- | ----- |
| `symbol` | 是 | — | 股票代码，如 `600000` 或 `sh600000` |
| `source` | 否 | 环境变量 `AKSHARE_DEFAULT_SOURCE` 或 `eastmoney` | `eastmoney` / `sina` / `tencent` |
| `start_date` | 否 | `19900101` | 开始日期 YYYYMMDD |
| `end_date` | 否 | `20500101` | 结束日期 YYYYMMDD |
| `adjust` | 否 | `""` | `""`=不复权，`qfq`=前复权，`hfq`=后复权 |

### 数据源对比

| 数据源 | 上游网站 | 海外可用性 | 参数值 |
| ----- | ----- | ----- | ----- |
| 东方财富 | East Money | 可能受限 | `eastmoney` |
| 新浪财经 | Sina Finance | 较好 | `sina` |
| 腾讯证券 | Tencent | 较好 | `tencent` |

### 示例

```sh
# 使用 Sina 数据源（推荐海外用户）
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_hist?symbol=600000&source=sina"

# 不指定 source，使用默认源
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_hist?symbol=000001"

# 指定日期范围和前复权
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_hist?symbol=600000&source=tencent&start_date=20240101&end_date=20241231&adjust=qfq"
```

### 符号自动转换

无论传入何种格式，接口自动适配数据源要求：

| 输入 | eastmoney 发送 | sina/tencent 发送 |
| ----- | ----- | ----- |
| `600000` | `600000` | `sh600000` |
| `sh600000` | `600000` | `sh600000` |
| `000001` | `000001` | `sz000001` |
| `sz000001` | `000001` | `sz000001` |

---

## 统一 A 股实时行情接口

`GET /api/public/v1/stock_cn_spot`

单个接口覆盖两个数据源，返回全市场实时行情，可按个股代码筛选。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `source` | 否 | `eastmoney` | `eastmoney` / `sina`（不支持 `tencent`） |
| `symbol` | 否 | 空（全市场） | 股票代码筛选，如 `600000` |

### 示例

```sh
# 全市场实时行情（从内存缓存返回，毫秒级响应）
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_spot?source=sina"

# 筛选单只股票
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_spot?symbol=600000&source=eastmoney"
```

!!! tip "缓存"
    实时行情数据由后台线程每 60 秒自动刷新。请求直接从内存读取，
    首次请求若缓存未就绪则回退为直接调用。缓存预热完成后响应时间 <10ms。

---

## A 股股票列表接口

`GET /api/public/v1/stock_cn_list`

返回沪深京全部 A 股代码与名称列表，数据由后台缓存（每日刷新），响应 <10ms。
支持分页，响应包含 `X-Total-Count` 头部。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `page` | 否 | `0`（不分页） | 页码，1-based |
| `page_size` | 否 | `100` | 每页条数，最大 1000 |

```sh
# 分页获取
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_list?page=1&page_size=50"

# 不分页（返回全部）
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_list"
```

---

## LOF 接口

### LOF 实时行情

`GET /api/public/v1/fund_lof_spot` — 60s 缓存，支持 `?symbol=166009` 筛选

### LOF 历史行情

`GET /api/public/v1/fund_lof_hist?symbol=166009`

```sh
curl "http://127.0.0.1:8080/api/public/v1/fund_lof_hist?symbol=166009"
```

---

## 场外基金接口

### 场外基金列表

`GET /api/public/v1/fund_open_list` — 全部开放式基金 + 最新净值，每日缓存，支持分页

### 场外基金历史净值

`GET /api/public/v1/fund_open_hist?symbol=710001&indicator=单位净值走势&period=成立来`

```sh
curl "http://127.0.0.1:8080/api/public/v1/fund_open_hist?symbol=710001"
```

---

## 基金列表接口

`GET /api/public/v1/fund_list`

返回全部基金代码、简称与类型，数据由后台缓存（每日刷新），响应 <10ms。
支持分页，响应包含 `X-Total-Count` 头部。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `page` | 否 | `0`（不分页） | 页码，1-based |
| `page_size` | 否 | `100` | 每页条数，最大 1000 |

```sh
curl "http://127.0.0.1:8080/api/public/v1/fund_list?page=1&page_size=50"
```

---

## 板块接口

### 行业板块

`GET /api/public/v1/board_industry_list` — 每日缓存
`GET /api/public/v1/board_industry_spot?symbol=半导体`
`GET /api/public/v1/board_industry_hist?symbol=元件`

### 概念板块

`GET /api/public/v1/board_concept_list` — 每日缓存
`GET /api/public/v1/board_concept_spot?symbol=元宇宙`
`GET /api/public/v1/board_concept_hist?symbol=阿里巴巴概念`

---

## 可转债接口

### 可转债列表

`GET /api/public/v1/bond_cov_list` — 每日缓存，含转股价、溢价率等核心指标，支持分页

### 可转债实时行情

`GET /api/public/v1/bond_cov_spot` — 60s 缓存，支持 `?symbol=sh123121` 筛选

### 可转债历史行情

`GET /api/public/v1/bond_cov_hist?symbol=sh010107`

```sh
curl "http://127.0.0.1:8080/api/public/v1/bond_cov_hist?symbol=sh010107"
```

---

## 期货接口

### 期货实时行情

`GET /api/public/v1/futures_spot` — 国际期货，60s 缓存，支持 `?symbol=HG00Y` 筛选

### 期货历史行情

`GET /api/public/v1/futures_hist?symbol=HG00Y`

```sh
curl "http://127.0.0.1:8080/api/public/v1/futures_hist?symbol=HG00Y"
```

---

## 指数接口

### 指数列表

`GET /api/public/v1/index_list` — 全球指数代码，每日缓存，支持分页

### 指数实时行情

`GET /api/public/v1/index_spot` — 全球指数，60s 缓存，支持 `?symbol=OMX` 筛选

### 指数历史行情

`GET /api/public/v1/index_hist?symbol=OMX&source=sina`

```sh
curl "http://127.0.0.1:8080/api/public/v1/index_hist?symbol=OMX&source=sina"
```

---

## 港股接口

### 港股列表

`GET /api/public/v1/stock_hk_list` — 港股通成份股，每日缓存，支持分页与搜索

### 港股实时行情

`GET /api/public/v1/stock_hk_spot` — 60s 缓存，双源（eastmoney/sina），`?symbol=00700` 筛选

### 港股历史行情

`GET /api/public/v1/stock_hk_hist?symbol=00700&source=sina`

```sh
curl "http://127.0.0.1:8080/api/public/v1/stock_hk_hist?symbol=00700&source=sina"
```

---

## 美股接口

### 美股列表

`GET /api/public/v1/stock_us_list` — 每日缓存，支持分页与搜索

### 美股实时行情

`GET /api/public/v1/stock_us_spot` — 60s 缓存，支持 `?symbol=AAPL` 筛选

### 美股历史行情

`GET /api/public/v1/stock_us_hist?symbol=AAPL&source=sina`

| 数据源 | 代码格式 | 上游 |
| ----- | ----- | ----- |
| `sina` | `AAPL` | 新浪财经 |
| `eastmoney` | `105.MSFT` | 东方财富 |

```sh
curl "http://127.0.0.1:8080/api/public/v1/stock_us_hist?symbol=AAPL&source=sina"
```

---

## 默认数据源管理

`GET /api/public/v1/default_source` — 查看当前默认数据源

`POST /api/private/v1/default_source?source=<name>` — 切换（需要认证）

```sh
# 查看当前设置（无需认证）
curl http://127.0.0.1:8080/api/public/v1/default_source
# → {"default_source":"eastmoney","available":["eastmoney","sina","tencent"]}

# 切换到 Sina（需要认证）
curl -X POST "http://127.0.0.1:8080/api/private/v1/default_source?source=sina" \
  -H "Authorization: Bearer <token>"
# → {"default_source":"sina","previous":"eastmoney"}

# 此后所有不传 ?source= 的请求默认使用 Sina
curl "http://127.0.0.1:8080/api/public/v1/stock_cn_hist?symbol=600000"
```

!!! note
    `POST` 切换仅在当前进程生命周期内有效。服务重启后，
    若设置了 `AKSHARE_DEFAULT_SOURCE` 环境变量则使用环境变量值，
    否则回退为 `eastmoney`。

---

## 自动重试

所有数据接口在遇到网络瞬断（`ConnectionError` / `Timeout`）时自动重试 **3 次**，
每次间隔 **5 秒**。重试耗尽后返回 HTTP 502 及明确的错误信息。

```json
{
  "error": "sina 数据源连接失败，已重试 3 次，请稍后重试或切换数据源"
}
```

---

## 智能缓存引擎

后台缓存线程感知 A 股交易时段（北京时间 Mon-Fri 9:30-11:30, 13:00-15:00）。

| 时段 | 刷新间隔 |
| ----- | :---: |
| 交易时段 | 60s |
| 非交易时段 / 周末 | 300s |

### 暂停/恢复

```sh
# 暂停（需要认证）
curl -X POST "http://127.0.0.1:8080/api/private/v1/cache/pause" \
  -H "Authorization: Bearer <token>"

# 恢复（需要认证）
curl -X POST "http://127.0.0.1:8080/api/private/v1/cache/resume" \
  -H "Authorization: Bearer <token>"
```

### 数据新鲜度

实时行情响应头携带新鲜度信息：

```
X-Cache-Age: 85
X-Cache-Stale: true
Warning: 110 - "Response is Stale"
```

`X-Cache-Stale` 仅在交易时段且缓存年龄 > 120s 时出现。数据仍然返回，不会阻塞。

### 缓存状态

`GET /api/public/v1/cache_status` 返回 `warm`、`paused`、`market_open` 及各缓存项的条数与时间。

---

## 环境变量参考

| 变量 | 用途 | 默认值 |
| ----- | ----- | ----- |
| `AKSHARE_PROXY` | HTTP/HTTPS 代理地址 | 无（直连） |
| `AKSHARE_DEFAULT_SOURCE` | 默认数据源 | `eastmoney` |
| `AKTOOLS_TOKENS_FILE` | 预配置 Token JSON 文件路径 | 无 |
| `AKTOOLS_DATA_DIR` | 持久化数据目录，默认 `./data/` | `./data/` |
