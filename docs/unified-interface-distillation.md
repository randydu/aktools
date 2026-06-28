# Unified Interface Distillation

How multi-source API endpoints are normalized to return consistent output regardless of which data source served the request.

---

## Methodology

For each endpoint that supports multiple data sources (`source` parameter), we follow three rules:

1. **Maximum shared subset** — return only the fields that ALL sources semantically provide. Drop source-only fields. Zero nulls in the normalized output.
2. **Auto source selection** — `source=auto` tries sources by priority with a circuit breaker (2 consecutive failures → 60s cooldown).
3. **`X-Market-Source` header** — every response tells the client which source actually served the data.

Field semantics are determined by cross-source data comparison, NOT by column name matching alone. Names can mislead (e.g., Tencent's `amount` column is volume-in-lots, not 成交额).

---

## Endpoint: `stock_cn_hist` (REFERENCE)

**Route:** `/public/v1/stock_cn_hist`  
**Sources:** eastmoney, sina, tencent  
**Shared fields:** 6

### Per-source field inventory

| Source | Function | Columns returned |
|--------|----------|------------------|
| eastmoney | `ak.stock_zh_a_hist()` | `日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率` |
| sina | `ak.stock_zh_a_daily()` | `date, open, high, low, close, volume, amount, outstanding_share, turnover` |
| tencent | `ak.stock_zh_a_hist_tx()` | `date, open, close, high, low, amount` |

### Normalize map

| Unified (English) | eastmoney | sina | tencent | Transform |
|---|---|---|---|---|
| `date` | `日期` | `date` | `date` | — |
| `open` | `开盘` | `open` | `open` | — |
| `high` | `最高` | `high` | `high` | — |
| `low` | `最低` | `low` | `low` | — |
| `close` | `收盘` | `close` | `close` | — |
| `volume` | `成交量` | `volume` | `amount` | eastmoney: ×100 (手→股), tencent: ×100 (amount列实为成交量手) |

### Gotchas

- **Tencent `amount` ≠ 成交额.** The column named `amount` contains volume in 手 (lots), confirmed by cross-referencing with eastmoney's `成交量` values. Transformed by ×100 to unify to 股.
- **Sina returns all-time data regardless of date params.** The function signature accepts `start_date`/`end_date` but ignores them — `_call_akshare_direct` silently drops unaccepted kwargs per source.
- **Sina `amount` = actual 成交额.** Unlike Tencent, Sina's `amount` column IS the turnover in yuan. Not included in shared subset (dropped to keep zero-null guarantee).

---

## Endpoint: `stock_cn_hist_intraday`

**Route:** `/public/v1/stock_cn_hist_intraday`  
**Sources:** eastmoney, sina  
**Shared fields:** 6

### Per-source field inventory

| Source | Function | Columns returned |
|--------|----------|------------------|
| eastmoney | `ak.stock_zh_a_hist_min_em()` | `时间, 开盘, 收盘, 最高, 最低, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅, 换手率` |
| sina | `ak.stock_zh_a_minute()` | `day, open, high, low, close, volume, amount` |

### Normalize map (proposed)

| Unified (English) | eastmoney | sina | Transform |
|---|---|---|---|
| `time` | `时间` | `day` | — |
| `open` | `开盘` | `open` | — |
| `high` | `最高` | `high` | — |
| `low` | `最低` | `low` | — |
| `close` | `收盘` | `close` | — |
| `volume` | `成交量` | `volume` | — |

### Gotchas

- **Sina only returns TODAY's intraday data.** The existing code auto-falls-back to eastmoney when `start_date` is not today. This fallback is subsumed by auto-source in Phase 3.
- **Timestamp format differs:** eastmoney returns `时间` as `2026-06-26 09:35:00`, sina returns `day` as `2026-04-24 14:55:00`. Both are datetime strings — no transform needed.

---

## Endpoint: `stock_cn_spot`

**Route:** `/public/v1/stock_cn_spot`  
**Sources:** eastmoney, sina  
**Shared fields:** 11  
**Cache layer:** Background thread refreshes every cycle; request-time serves from `_spot_cache`.

### Per-source field inventory

| Source | Function | Columns returned |
|--------|----------|------------------|
| eastmoney | `ak.stock_zh_a_spot_em()` | `序号, 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅, 最高, 最低, 今开, 昨收, 量比, 换手率, 市盈率-动态, 市净率, 总市值, 流通市值, 涨速, 5分钟涨跌, 60日涨跌幅, 年初至今涨跌幅` |
| sina | `ak.stock_zh_a_spot()` | `代码, 名称, 最新价, 涨跌额, 涨跌幅, 买入, 卖出, 昨收, 今开, 最高, 最低, 成交量, 成交额, 时间戳` |

### Fields dropped (source-only)

| Field | Source | Reason |
|-------|--------|--------|
| `序号` | eastmoney | Row index, not data |
| `振幅` | eastmoney | Not in sina |
| `量比` | eastmoney | Not in sina |
| `换手率` | eastmoney | Not in sina |
| `市盈率-动态` | eastmoney | Not in sina |
| `市净率` | eastmoney | Not in sina |
| `总市值` | eastmoney | Not in sina |
| `流通市值` | eastmoney | Not in sina |
| `涨速` | eastmoney | Not in sina |
| `5分钟涨跌` | eastmoney | Not in sina |
| `60日涨跌幅` | eastmoney | Not in sina |
| `年初至今涨跌幅` | eastmoney | Not in sina |
| `买入` | sina | Not in eastmoney |
| `卖出` | sina | Not in eastmoney |
| `时间戳` | sina | Not in eastmoney |

### Normalize map (proposed)

Both sources use Chinese column names. Map to English for consistency:

| Unified (English) | eastmoney | sina | Notes |
|---|---|---|---|
| `code` | `代码` | `代码` | |
| `name` | `名称` | `名称` | |
| `latest` | `最新价` | `最新价` | Latest trading price |
| `change_pct` | `涨跌幅` | `涨跌幅` | Percentage change |
| `change_amt` | `涨跌额` | `涨跌额` | Absolute change |
| `volume` | `成交量` | `成交量` | |
| `amount` | `成交额` | `成交额` | Turnover in yuan |
| `prev_close` | `昨收` | `昨收` | Previous close |
| `open` | `今开` | `今开` | Today's open |
| `high` | `最高` | `最高` | Day high |
| `low` | `最低` | `最低` | Day low |

---

## Endpoint: `fund_etf_hist_universal`

**Route:** `/public/v1/stock_etf_hist`  
**Sources:** eastmoney, sina  
**Shared fields:** 6

### Per-source field inventory

| Source | Function | Columns returned |
|--------|----------|------------------|
| eastmoney | `ak.fund_etf_hist_em()` | `日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率` |
| sina | `ak.fund_etf_hist_sina()` | `date, prevclose, open, high, low, close, volume, amount` |

### Normalize map (proposed)

| Unified (English) | eastmoney | sina | Transform |
|---|---|---|---|
| `date` | `日期` | `date` | — |
| `open` | `开盘` | `open` | — |
| `high` | `最高` | `high` | — |
| `low` | `最低` | `low` | — |
| `close` | `收盘` | `close` | — |
| `volume` | `成交量` | `volume` | — |

### Gotchas

- **Sina requires prefixed symbol** (`sh510050`, not bare `510050`). The existing code handles this via `_normalize_symbol(symbol, source_config["prefixed"])`.
- **Sina `prevclose` dropped** — eastmoney doesn't provide a separate prev_close column.
- **Sina `amount` dropped** — eastmoney's `成交额` exists but keeping the shared-subset rule means dropping both.

---

## Endpoint: `stock_us_hist_universal`

**Route:** `/public/v1/stock_us_hist`  
**Sources:** eastmoney, sina  
**Shared fields:** 6

### Per-source field inventory

| Source | Function | Columns returned |
|--------|----------|------------------|
| eastmoney | `ak.stock_us_hist()` | `日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率` |
| sina | `ak.stock_us_daily()` | `date, open, high, low, close, volume` |

### Normalize map (proposed)

| Unified (English) | eastmoney | sina | Transform |
|---|---|---|---|
| `date` | `日期` | `date` | — |
| `open` | `开盘` | `open` | — |
| `high` | `最高` | `high` | — |
| `low` | `最低` | `low` | — |
| `close` | `收盘` | `close` | — |
| `volume` | `成交量` | `volume` | — |

---

## Endpoint: `stock_hk_spot_universal`

**Route:** `/public/v1/stock_hk_spot`  
**Sources:** eastmoney, sina  
**Shared fields:** 10  
**Cache layer:** Same background thread as `stock_cn_spot`.

### Per-source field inventory

| Source | Function | Columns returned |
|--------|----------|------------------|
| eastmoney | `ak.stock_hk_spot_em()` | `序号, 代码, 名称, 最新价, 涨跌额, 涨跌幅, 今开, 最高, 最低, 昨收, 成交量, 成交额` |
| sina | `ak.stock_hk_spot()` | `日期时间, 代码, 中文名称, 英文名称, 交易类型, 最新价, 涨跌额, 涨跌幅, 昨收, 今开, 最高, 最低, 成交量, 成交额, 买一, 卖一` |

### Fields dropped (source-only)

| Field | Source | Reason |
|-------|--------|--------|
| `序号` | eastmoney | Row index |
| `名称` | eastmoney | Sina has `中文名称` which is richer |
| `日期时间` | sina | Eastmoney has no timestamp |
| `中文名称` | sina | Eastmoney has bare `名称` — dropped from shared set to keep zero-null |
| `英文名称` | sina | Eastmoney-only |
| `交易类型` | sina | Eastmoney-only |
| `买一` | sina | Eastmoney-only |
| `卖一` | sina | Eastmoney-only |

### Normalize map (proposed)

| Unified (English) | eastmoney | sina | Notes |
|---|---|---|---|
| `code` | `代码` | `代码` | |
| `latest` | `最新价` | `最新价` | |
| `change_amt` | `涨跌额` | `涨跌额` | |
| `change_pct` | `涨跌幅` | `涨跌幅` | |
| `prev_close` | `昨收` | `昨收` | |
| `open` | `今开` | `今开` | |
| `high` | `最高` | `最高` | |
| `low` | `最低` | `最低` | |
| `volume` | `成交量` | `成交量` | |
| `amount` | `成交额` | `成交额` | |

### Gotchas

- **HK spot's `名称` mismatch:** eastmoney has `名称` (short name), sina has `中文名称` + `英文名称` (richer). Dropped from shared set to avoid mismatch. Clients who need names should use the search/list endpoints.
- **Sina adds timestamp (`日期时间`)** which eastmoney lacks — dropped.

---

## Endpoint: `stock_hk_hist`

**Route:** `/public/v1/stock_hk_hist`  
**Sources:** eastmoney, sina  
**Shared fields:** 6

### Per-source field inventory

| Source | Function | Columns returned |
|--------|----------|------------------|
| eastmoney | `ak.stock_hk_hist()` | `日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率` |
| sina | `ak.stock_hk_daily()` | `date, open, high, low, close, volume, amount` |

### Normalize map (proposed)

| Unified (English) | eastmoney | sina | Transform |
|---|---|---|---|
| `date` | `日期` | `date` | — |
| `open` | `开盘` | `open` | — |
| `high` | `最高` | `high` | — |
| `low` | `最低` | `low` | — |
| `close` | `收盘` | `close` | — |
| `volume` | `成交量` | `volume` | — |

### Gotchas

- **Sina `amount` = 成交额** (sometimes zero for illiquid early dates). Dropped per shared-subset rule.

---

## Endpoint: `index_hist`

**Route:** `/public/v1/index_hist`  
**Sources:** eastmoney, sina  
**Status:** **Skip normalization** — the two sources serve non-overlapping markets.

### Per-source field inventory

| Source | Function | Columns returned |
|--------|----------|------------------|
| eastmoney | `ak.index_global_hist_em()` | `日期, 代码, 名称, 今开, 最新价, 最高, 最低, 振幅` |
| sina | `ak.index_global_hist_sina()` | `date, open, high, low, close, volume` |

### Why no normalization

| Factor | Detail |
|--------|--------|
| **Symbol overlap** | Near-zero. Eastmoney covers Chinese indices (上证指数, 深证成指, 恒生指数); Sina covers global indices (英国富时100指数, 日经225指数). No symbol works in both sources. |
| **Column mismatch** | Eastmoney has 8 Chinese-named columns; Sina has 6 English-named columns. |
| **Use case** | The `source` parameter here is a genuine market selector, not a redundancy mechanism. Clients choose the source that covers their desired index. |

**Recommendation:** Add `X-Market-Source` header only. Skip auto-source and normalize — the two sources are complementary, not redundant.

---

## Cross-cutting: column naming convention

All normalized outputs use English snake_case names:

| Domain | Convention | Examples |
|--------|------------|----------|
| OHLCV | Standard market-data names | `open`, `high`, `low`, `close`, `volume` |
| Date/time | `date` for daily, `time` for intraday | `date`, `time` |
| Amount/turnover | `amount` = turnover in base currency | `amount` |
| Change | `change_pct` (%), `change_amt` (absolute) | `change_pct`, `change_amt` |
| Previous close | `prev_close` | `prev_close` |
| Latest price | `latest` (preferred over `close` for spot data) | `latest` |
| Identifier | `code` for symbol, `name` for display name | `code`, `name` |

---

## Auto-source priority chains

| Endpoint | Category key | Priority | Notes |
|---|---|---|---|
| `stock_cn_hist` | `cn_hist` | eastmoney → tencent → sina | |
| `stock_cn_hist_intraday` | `cn_intraday` | eastmoney → sina | Sina only has today's data |
| `fund_etf_hist_universal` | `fund_etf_hist` | eastmoney → sina | |
| `stock_us_hist_universal` | `us_hist` | eastmoney → sina | |
| `stock_hk_hist` | `hk_hist` | eastmoney → sina | |
| `stock_cn_spot` | `cn_spot` | eastmoney → sina | Cache-layer auto-source |
| `stock_hk_spot_universal` | `hk_spot` | eastmoney → sina | Cache-layer auto-source |
| `index_hist` | — | **Skip** | Non-overlapping sources |

---

## Sampling script

The `var/sample_sources.py` script calls every source function with representative symbols and dumps column names + sample values. Run it to validate normalize maps after AKShare version upgrades:

```sh
.venv/bin/python var/sample_sources.py
```
