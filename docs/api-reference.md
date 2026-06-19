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

### 默认数据源管理

`GET /api/v1/default_source` — 查看当前默认源

`POST /api/v1/default_source?source=<name>` — 运行时切换

```sh
# 查看
curl http://127.0.0.1:8080/api/v1/default_source
# → {"default_source":"eastmoney","available":["eastmoney","sina","tencent"]}

# 切换为 Sina（即时生效，无需重启）
curl -X POST "http://127.0.0.1:8080/api/v1/default_source?source=sina"
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
