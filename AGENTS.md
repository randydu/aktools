# AGENTS.md — AKTools API Reference for AI Agents

## Architecture

AKTools wraps [AKShare](https://github.com/akfamily/akshare) functions as HTTP endpoints under FastAPI. A background cache thread refreshes no-arg data sources. On-demand endpoints (history, board spot) use response caching or direct AKShare calls with 3-attempt / 5-second retry.

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

- API tokens stored in SQLite (`data/tokens.db`)
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

Cache persisted to `$AKTOOLS_DATA_DIR/cache.db` (WAL mode, crash-safe). Restored on restart — warm flag set immediately if cache.db has entries.

## Public Endpoints

### A-Shares (China)

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/stock_cn_list` | GET | Daily, paginated | `page`(0=all), `page_size`(100) |
| `/api/public/v1/stock_cn_spot` | GET | 60s, fallback | `source`(eastmoney/sina), `symbol`(optional filter) |
| `/api/public/v1/stock_cn_hist` | GET | On-demand | `symbol`(req), `source`, `start_date`, `end_date`, `adjust` |
| `/api/public/v1/stock_cn_hist_intraday` | GET | On-demand | `symbol`(req), `source`(eastmoney/sina), `period`(1/5/15/30/60), `start_date`, `end_date`, `adjust` |
| `/api/public/v1/stock_cn_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |
| `/api/public/v1/stock_profile` | GET | Daily | `symbol`(req) → `{code, industry, concepts}` |

### US Stocks

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/stock_us_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/stock_us_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/stock_us_hist` | GET | On-demand | `symbol`(req), `source`(eastmoney/sina), `start_date`, `end_date`, `adjust` |
| `/api/public/v1/stock_us_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |

### HK Stocks

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/stock_hk_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/stock_hk_spot` | GET | 60s, fallback | `source`(eastmoney/sina), `symbol`(optional filter) |
| `/api/public/v1/stock_hk_hist` | GET | On-demand | `symbol`(req), `source`, `start_date`, `end_date`, `adjust` |
| `/api/public/v1/stock_hk_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |

### Funds & ETFs

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/fund_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/fund_etf_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/fund_etf_hist` | GET | On-demand | `symbol`(req), `source`(eastmoney/sina), `start_date`, `end_date`, `adjust` |
| `/api/public/v1/fund_lof_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/fund_lof_hist` | GET | On-demand | `symbol`(req), `period`, `start_date`, `end_date`, `adjust` |
| `/api/public/v1/fund_open_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/fund_open_hist` | GET | On-demand | `symbol`(req), `indicator`, `period` |
| `/api/public/v1/fund_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |
| `/api/public/v1/fund_open_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |

### Convertible Bonds

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/bond_cov_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/bond_cov_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/bond_cov_hist` | GET | On-demand | `symbol`(req) |
| `/api/public/v1/bond_cov_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |

### Futures & Indices

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/futures_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/futures_hist` | GET | On-demand | `symbol`(req), `start_date`, `end_date` |
| `/api/public/v1/index_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/index_spot` | GET | 60s | `symbol`(optional filter) |
| `/api/public/v1/index_hist` | GET | On-demand | `symbol`(req), `source`(eastmoney/sina) |
| `/api/public/v1/index_search` | GET | Cached | `q`(req), `limit`(20, 0=all) |

### Board / Sector

| Endpoint | Method | Cache | Params |
|---|---|---|---|
| `/api/public/v1/board_industry_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/board_concept_list` | GET | Daily, paginated | `page`, `page_size` |
| `/api/public/v1/board_industry_spot` | GET | On-demand 60s | `symbol`(req) |
| `/api/public/v1/board_concept_spot` | GET | On-demand 60s | `symbol`(req) |
| `/api/public/v1/board_industry_hist` | GET | On-demand 60s | `symbol`(req), `start_date`, `end_date` |
| `/api/public/v1/board_concept_hist` | GET | On-demand 60s | `symbol`(req), `start_date`, `end_date` |

## Management Endpoints (public, no auth)

| Endpoint | Method | Response |
|---|---|---|
| `/api/public/v1/cache_status` | GET | `{warm, paused, market_open, paused_keys, caches}` |
| `/api/public/v1/default_source` | GET | `{default_source, available}` |

## Management Endpoints (auth required)

| Endpoint | Method | Params | Notes |
|---|---|---|---|
| `/api/private/v1/default_source` | POST | `source`(req) | Switch default source |
| `/api/private/v1/cache/pause` | POST | `keys`(opt, comma-sep) | Per-key or global pause |
| `/api/private/v1/cache/resume` | POST | `keys`(opt, comma-sep) | Per-key or global resume |
| `/api/private/v1/tokens` | POST | `user`(opt) | Create token |
| `/api/private/v1/tokens` | GET | — | List tokens (prefix only) |
| `/api/private/v1/tokens` | DELETE | `token`(req) | Revoke token |

## Common Parameters

| Param | Used by | Default | Description |
|---|---|---|---|
| `source` | hist, spot | `eastmoney` or `AKSHARE_DEFAULT_SOURCE` | Data source: eastmoney/sina/tencent |
| `symbol` | hist, spot, profile | (required) | Stock/fund/bond code |
| `page` | list | `0` (all) | 1-based page number |
| `page_size` | list | `100` | Items per page, max 1000 |
| `q` | search | (required) | Case-insensitive substring |
| `limit` | search | `20` | Max results, `0`=unlimited |
| `start_date` | hist | varies | YYYYMMDD |
| `end_date` | hist | varies | YYYYMMDD |
| `adjust` | hist | `""` | `""`/`qfq`/`hfq` |

## Response Headers

| Header | When | Meaning |
|---|---|---|
| `X-Total-Count` | List, search | Total items (for pagination) |
| `X-Cache-Age` | Spot, cached | Seconds since cache refreshed |
| `X-Cache-Stale` | Spot, market open + age >120s | `"true"` |
| `Retry-After` | 503 warmup | Seconds until retry suggested |

## Error Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 400 | Bad parameter (invalid source, etc.) |
| 401 | Missing/invalid token |
| 404 | Data not found |
| 410 | Deprecated endpoint (`/auth/token`) |
| 500 | Internal error |
| 502 | Upstream data source unavailable (retried 3x) |
| 503 | Cache warming up |

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `AKSHARE_PROXY` | — | HTTP proxy for upstream requests |
| `AKSHARE_DEFAULT_SOURCE` | `eastmoney` | Default data source for v1 endpoints |
| `AKTOOLS_DATA_DIR` | `./data/` | Persistent data directory (cache.db, tokens.db, logs) |
| `AKTOOLS_LOG_LEVEL` | `INFO` | Log level: DEBUG/INFO/WARNING/ERROR |
| `AKTOOLS_TOKENS_FILE` | — | Pre-configured token JSON file path |

## Cache Keys (for pause/resume)

`stock_spot_eastmoney`, `stock_spot_sina`, `fund_etf_spot`, `fund_lof_spot`, `stock_us_spot`, `stock_hk_spot_eastmoney`, `stock_hk_spot_sina`, `futures_spot`, `index_spot`, `stock_list`, `fund_list`, `stock_us_list`, `stock_hk_list`, `index_list`, `board_industry_list`, `board_concept_list`, `bond_cov_list`, `fund_open_list`, `stock_profile`

## Source Availability by Market

| Market | eastmoney | sina | tencent |
|---|---|---|---|
| A-shares hist | ✅ | ✅ | ✅ |
| A-shares spot | ✅ | ✅ | ❌ |
| US stocks hist | ✅ | ✅ | ❌ |
| US stocks spot | ✅ | ❌ | ❌ |
| HK stocks hist | ✅ | ✅ | ❌ |
| HK stocks spot | ✅ | ✅ | ❌ |
| Indices hist | ✅ | ✅ | ❌ |
| ETF hist | ✅ | ✅ | ❌ |
| Bond cov hist | ❌ | ✅ | ❌ |
