# V1 API

AKTools v0.0.91+ 新增的版本化 API，提供多数据源切换、代理支持和自动重试。

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

`GET /api/public/v1/stock_zh_a_hist`

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
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_hist?symbol=600000&source=sina"

# 不指定 source，使用默认源
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_hist?symbol=000001"

# 指定日期范围和前复权
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_hist?symbol=600000&source=tencent&start_date=20240101&end_date=20241231&adjust=qfq"
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

`GET /api/public/v1/stock_zh_a_spot`

单个接口覆盖两个数据源，返回全市场实时行情，可按个股代码筛选。

| 参数 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `source` | 否 | `eastmoney` | `eastmoney` / `sina`（不支持 `tencent`） |
| `symbol` | 否 | 空（全市场） | 股票代码筛选，如 `600000` |

### 示例

```sh
# 全市场实时行情（从内存缓存返回，毫秒级响应）
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_spot?source=sina"

# 筛选单只股票
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_spot?symbol=600000&source=eastmoney"
```

!!! tip "缓存"
    实时行情数据由后台线程每 60 秒自动刷新。请求直接从内存读取，
    首次请求若缓存未就绪则回退为直接调用。缓存预热完成后响应时间 <10ms。

---

## A 股股票列表接口

`GET /api/public/v1/stock_info_a_code_name`

返回沪深京全部 A 股代码与名称列表，数据由后台缓存（每 60 秒刷新），响应 <10ms。

```sh
curl "http://127.0.0.1:8080/api/public/v1/stock_info_a_code_name"
```

---

## 默认数据源管理

`GET /api/v1/default_source` — 查看当前默认数据源

`POST /api/v1/default_source?source=<name>` — 运行时切换默认数据源

```sh
# 查看当前设置
curl http://127.0.0.1:8080/api/v1/default_source
# → {"default_source":"eastmoney","available":["eastmoney","sina","tencent"]}

# 切换到 Sina（即时生效，无需重启）
curl -X POST "http://127.0.0.1:8080/api/v1/default_source?source=sina"
# → {"default_source":"sina","previous":"eastmoney"}

# 此后所有不传 ?source= 的请求默认使用 Sina
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_hist?symbol=600000"
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

## 环境变量参考

| 变量 | 用途 | 默认值 |
| ----- | ----- | ----- |
| `AKSHARE_PROXY` | HTTP/HTTPS 代理地址 | 无（直连） |
| `AKSHARE_DEFAULT_SOURCE` | 默认数据源 | `eastmoney` |
