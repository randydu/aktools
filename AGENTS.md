# AGENTS.md — AKTools API Reference for AI Agents

## Architecture

AKTools wraps [AKShare](https://github.com/akfamily/akshare) functions as HTTP endpoints under FastAPI. A background cache thread refreshes no-arg data sources. On-demand endpoints use response caching or direct AKShare calls with 3-attempt / 5-second retry.

## URL Conventions

```
/api/public/v1/{category}_{type}     — public data
/api/private/v1/{category}/{action}  — management (auth required)
/api/private/v1/tokens              — token CRUD (auth required)
/api/public/{item_id}               — generic AKShare proxy (legacy)
/api/private/{item_id}              — generic proxy with auth
/auth/token                         — deprecated (returns 410)
```

## Auth Model

- API tokens stored in SQLite (`$AKTOOLS_DATA_DIR/tokens.db`)
- First startup auto-creates root token (printed to log)
- Pre-configured token file: `AKTOOLS_TOKENS_FILE` env var
- Use: `Authorization: Bearer <token>`

## Cache Model

| Type | Refresh | Persist | Stale |
|---|---|---|---|
| Spot (no-arg) | 60s market / 300s off | SQLite WAL every cycle | `X-Cache-Stale` header >120s |
| List (no-arg) | Daily | SQLite WAL | — |
| Profile (computed) | Daily | SQLite WAL | — |
| On-demand (with arg) | On first call + 60s TTL | At cycle boundary | — |

Cache persisted to `$AKTOOLS_DATA_DIR/cache.db` (WAL mode, crash-safe). Restored on restart — warm flag set immediately if cache.db has entries. Per-key pause/resume via `_paused_keys` set.

## Public Endpoints (44 total)

### A-Shares (China)

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/stock_cn_list` | GET | Daily, paginated | `page`(0=all), `page_size`(100) |
| `/api/public/v1/stock_cn_spot` | GET | 60s, fallback | `source`(eastmoney/sina), `symbol`(optional filter) |
| `/api/public/v1/stock_cn_hist` | GET | On-demand | `symbol`(req), `source`(eastmoney/sina/tencent), `start_date`, `end_date`, `adjust`(`""`/`qfq`/`hfq`) |
| `/api/public/v1/stock_cn_hist_intraday` | GET | On-demand | `symbol`(req), `source`(eastmoney/sina), `period`(1/5/15/30/60), `start_date`(eastmoney only), `end_date`, `adjust`(`""`/`qfq`/`hfq`) |
| `/api/public/v1/stock_cn_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |
| `/api/public/v1/stock_profile` | GET | Daily | `symbol`(req) → `{code, industry, concepts}` |

### US Stocks

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/stock_us_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/stock_us_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/stock_us_hist` | GET | On-demand | `symbol`(req), `source`(eastmoney/sina), `start_date`(eastmoney only), `end_date`(eastmoney only), `adjust`(`""`/`qfq`/`hfq`) |
| `/api/public/v1/stock_us_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |

### HK Stocks

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/stock_hk_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/stock_hk_spot` | GET | 60s, fallback | `source`(eastmoney/sina), `symbol`(optional filter) |
| `/api/public/v1/stock_hk_hist` | GET | On-demand | `symbol`(req), `source`(eastmoney/sina), `start_date`(eastmoney only), `end_date`(eastmoney only), `adjust`(`""`/`qfq`/`hfq`) |
| `/api/public/v1/stock_hk_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |

### Funds & ETFs

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/fund_list` | GET | Daily, paginated | `page`, `page_size` (all fund types) |
| `/api/public/v1/fund_etf_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/fund_etf_hist` | GET | On-demand | `symbol`(req), `source`(eastmoney/sina), `start_date`(eastmoney only), `end_date`(eastmoney only), `adjust`(`""`/`qfq`/`hfq`, eastmoney only) |
| `/api/public/v1/fund_etf_hist_intraday` | GET | On-demand | `symbol`(req), `period`(1/5/15/30/60), `start_date`, `end_date`, `adjust`(`""`/`qfq`/`hfq`) |
| `/api/public/v1/fund_lof_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/fund_lof_hist` | GET | On-demand | `symbol`(req), `period`(daily/weekly/monthly), `start_date`, `end_date`, `adjust`(`""`/`qfq`/`hfq`) |
| `/api/public/v1/fund_lof_hist_intraday` | GET | On-demand | `symbol`(req), `period`(1/5/15/30/60), `start_date`, `end_date`, `adjust`(`""`/`qfq`/`hfq`) |
| `/api/public/v1/fund_open_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/fund_open_hist` | GET | On-demand | `symbol`(req), `indicator`(单位净值走势/累计净值走势), `period`(1月/近1月, 3月/近3月, 6月/近6月, 1年/近1年, 3年, 5年, 今年来, 成立来) |
| `/api/public/v1/fund_search` | GET | Cached | `q`(req), `limit`(20, 0=all) (all funds) |
| `/api/public/v1/fund_open_search` | GET | Cached | `q`(req), `limit`(20, 0=all) (open-end only) |

### Convertible Bonds

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/bond_cov_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/bond_cov_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/bond_cov_hist` | GET | On-demand | `symbol`(req, get codes from bond_cov_spot, e.g. sh010107) |
| `/api/public/v1/bond_cov_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |

### Futures

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/futures_spot` | GET | 60s | `symbol`(optional filter, e.g. HG00Y) |
| `/api/public/v1/futures_hist` | GET | On-demand | `symbol`(req, get codes from futures_spot), `start_date`, `end_date` |

### Indices

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/index_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/index_spot` | GET | 60s | `symbol`(optional filter, e.g. OMX) |
| `/api/public/v1/index_hist` | GET | On-demand | `symbol`(req, get codes from index_spot), `source`(eastmoney/sina) |
| `/api/public/v1/index_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |

### Board / Sector

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/board_industry_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/board_concept_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/board_industry_spot` | GET | On-demand 60s | `symbol`(req, e.g. 半导体) |
| `/api/public/v1/board_concept_spot` | GET | On-demand 60s | `symbol`(req, e.g. 元宇宙) |
| `/api/public/v1/board_industry_hist` | GET | On-demand 60s | `symbol`(req), `start_date`, `end_date` |
| `/api/public/v1/board_concept_hist` | GET | On-demand 60s | `symbol`(req), `start_date`, `end_date` |

## Management (public, no auth)

| Endpoint | Method | Response |
|---|---|---|
| `/api/public/v1/cache_status` | GET | `{warm, paused, market_open, paused_keys, caches}` |
| `/api/public/v1/default_source` | GET | `{default_source, available}` |

## Management (auth required)

| Endpoint | Method | Params | Notes |
|---|---|---|---|
| `/api/private/v1/default_source` | POST | `source`(req) | Switch default source |
| `/api/private/v1/cache/pause` | POST | `keys`(opt, comma-sep) | Per-key or global |
| `/api/private/v1/cache/resume` | POST | `keys`(opt, comma-sep) | Per-key or global |
| `/api/private/v1/tokens` | POST | `user`(opt) | Create token |
| `/api/private/v1/tokens` | GET | — | List tokens (prefix only) |
| `/api/private/v1/tokens` | DELETE | `token`(req) | Revoke token |

## Common Parameters

| Param | Default | Description |
|---|---|---|
| `source` | `eastmoney` or `AKSHARE_DEFAULT_SOURCE` | Data source |
| `symbol` | (required) | Stock/fund/bond code |
| `page` | `0` (all) | 1-based page |
| `page_size` | `100` | Max 1000 |
| `q` | (required) | Case-insensitive substring |
| `limit` | `20` | Max results, `0`=unlimited |
| `start_date` | varies | YYYYMMDD or datetime |
| `end_date` | varies | YYYYMMDD or datetime |
| `adjust` | `""` | `""`/`qfq`/`hfq` |

## Compression

All JSON responses >1KB are gzip-compressed when the client sends `Accept-Encoding: gzip` (80-90% smaller). Most HTTP clients (browsers, reqwest, axios, fetch) do this by default — no code changes needed. Clients that don't send the header receive uncompressed JSON (fully backward compatible).

## Response Headers

| Header | When |
|---|---|
| `Content-Encoding` | `gzip` when compressed |
| `Vary` | `Accept-Encoding` on compressible responses |
| `X-Total-Count` | List, search |
| `X-Cache-Age` | Spot, cached |
| `X-Cache-Stale` | Spot >120s during market hours |
| `Retry-After` | 503 warmup |

## Error Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 400 | Bad parameter |
| 401 | Missing/invalid token |
| 404 | Not found |
| 410 | Deprecated |
| 502 | Upstream failed (3 retries) |
| 503 | Cache warming |

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `AKSHARE_PROXY` | — | HTTP proxy |
| `AKSHARE_DEFAULT_SOURCE` | `eastmoney` | Default source |
| `AKTOOLS_DATA_DIR` | `./data/` | Persistence directory |
| `AKTOOLS_LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `AKTOOLS_TOKENS_FILE` | — | Pre-configured tokens JSON |

## Source Availability

| Market | eastmoney | sina | tencent |
|---|---|---|---|
| A-shares hist | ✅ | ✅ | ✅ |
| A-shares spot | ✅ | ✅ | ❌ |
| A-shares intraday | ✅ | ✅ (today only) | ❌ |
| US stocks hist | ✅ | ✅ | ❌ |
| US stocks spot | ✅ | ❌ | ❌ |
| HK stocks hist | ✅ | ✅ | ❌ |
| HK stocks spot | ✅ | ✅ | ❌ |
| Indices hist | ✅ | ✅ | ❌ |
| ETF hist | ✅ | ✅ | ❌ |
| ETF/LOF intraday | ✅ | ❌ | ❌ |
| Bond cov hist | ❌ | ✅ | ❌ |
| Bond cov spot | ❌ | ✅ | ❌ |
