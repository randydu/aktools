# Cache Architecture

AKTools uses a three-tier in-memory cache refreshed by a background daemon thread. All caches are persisted to SQLite (`cache.db`, WAL mode) for crash-safe recovery on restart.

---

## Tier 1: Spot caches (real-time market data)

Refreshed every **60s during market hours only**. Completely skipped when markets are closed (nights, weekends) — spot data doesn't change. Last market-hours cycle captures final closing prices. These are full-market scans — no symbol filter applied at fetch time; filtering happens at request time from the cached dataset.

| Cache key | Market | AKShare function | Serves endpoints |
|-----------|--------|-----------------|-----------------|
| `stock_cn_spot_eastmoney` | A-shares | `ak.stock_zh_a_spot_em()` | `stock_cn_spot` (source=eastmoney) |
| `stock_cn_spot_sina` | A-shares | `ak.stock_zh_a_spot()` | `stock_cn_spot` (source=sina) |
| `fund_etf_spot` | ETF | `ak.fund_etf_spot_em()` | `fund_etf_spot` |
| `fund_lof_spot` | LOF | `ak.fund_lof_spot_em()` | `fund_lof_spot` |
| `stock_us_spot` | US stocks | `ak.stock_us_spot_em()` | `stock_us_spot` |
| `stock_hk_spot_eastmoney` | HK stocks | `ak.stock_hk_spot_em()` | `stock_hk_spot` (source=eastmoney) |
| `stock_hk_spot_sina` | HK stocks | `ak.stock_hk_spot()` | `stock_hk_spot` (source=sina) |
| `futures_spot` | Futures | `ak.futures_global_spot_em()` | `futures_spot` |
| `index_spot` | Indices | `ak.index_global_spot_em()` | `index_spot` |
| `bond_cov_spot` | Convertible bonds | `ak.bond_zh_hs_cov_spot()` | `bond_cov_spot` |

**Why cached:** These endpoints return full-market data. Without cache, every request triggers a 2–30s AKShare API call. With cache, responses are <10ms (lock-protected dict read).

**Staleness:** During market hours, responses include `X-Cache-Age` (seconds since refresh) and `X-Cache-Stale: true` if the cache is >120s old.

**Persist timing:** Written to cache.db after the spot refresh phase completes (~2 min into the first cycle).

---

## Tier 2: Static caches (reference data)

Refreshed every **_static_interval** cycles (1440 cycles ≈ daily during market hours). These are lists and lookup tables that change slowly.

| Cache key | Description | AKShare function | Serves endpoints |
|-----------|-------------|-----------------|-----------------|
| `stock_cn_list` | A-share codes + names | `ak.stock_info_a_code_name()` | `stock_cn_list`, `stock_cn_search` |
| `fund_list` | All fund codes + names | `ak.fund_name_em()` | `fund_list`, `fund_search` |
| `fund_open_list` | Open-end fund codes + names | `ak.fund_open_fund_daily_em()` | `fund_open_list`, `fund_open_search` |
| `stock_us_list` | US stock codes + names | `ak.get_us_stock_name()` | `stock_us_list`, `stock_us_search` |
| `stock_hk_list` | HK Stock Connect members | `ak.stock_hk_ggt_components_em()` | `stock_hk_list`, `stock_hk_search` |
| `index_list` | Global index names + codes | `ak.index_global_name_table()` | `index_list`, `index_search` |
| `bond_cov_list` | Convertible bond codes + names | `ak.bond_zh_cov()` | `bond_cov_list`, `bond_cov_search` |
| `board_industry_list` | Industry board names | `ak.stock_board_industry_name_em()` | `board_industry_list` |
| `board_concept_list` | Concept board names | `ak.stock_board_concept_name_em()` | `board_concept_list` |
| `stock_profile` | Stock→industry+concept map | Built from constituent data | `stock_profile` |

**Why cached:** List endpoints serve paginated data — the full dataset is in memory and sliced at request time (<10ms). Search endpoints scan the cached list in-memory. Without cache, these would call AKShare on every request (seconds of latency).

**`stock_profile` note:** This is the slowest cache to build — it calls `ak.stock_board_industry_cons_em()` and `ak.stock_board_concept_cons_em()` for every board (~500 sequential API calls, 5–15 minutes). It is the last key in `_STATIC_CACHE_MAP`; all list caches are persisted before it starts. Spot caches refresh independently during the build.

**Persist timing:** Written to cache.db right before `stock_profile` begins building (~30s into the first cycle on cold start). A second persist at cycle end adds `stock_profile` when it completes.

---

## Tier 3: On-demand caches (per-query)

Created by `_cached_on_demand()` when a board/concept spot or history endpoint is first called. TTL: 60s.

| Cache key pattern | Example | Serves |
|-------------------|---------|--------|
| `board_industry_spot:{name}` | `board_industry_spot:半导体` | `board_industry_spot` |
| `board_concept_spot:{name}` | `board_concept_spot:元宇宙` | `board_concept_spot` |
| `board_concept_hist:{name}:{start}:{end}` | `board_concept_hist:元宇宙:20200101:20250101` | `board_concept_hist` |
| `board_industry_hist:{name}:{start}:{end}` | `board_industry_hist:元件:20200101:20250101` | `board_industry_hist` |

**Why cached:** These endpoints accept user-supplied symbols. Multiple clients requesting the same board within 60s share the cached result, avoiding redundant AKShare calls. After 60s, the next request triggers a fresh fetch.

**Persist timing:** At cycle boundary (included in the end-of-cycle `_persist_cache_to_db()` call). These caches grow the cache.db file over time as new symbols are requested, but `INSERT OR REPLACE` prevents unbounded growth for repeated queries.

---

## Refresh cycle timeline

```
Cycle start
  │
  ├─ ~2s   Spot: A-share eastmoney ──┐
  ├─ ~2s   Spot: A-share sina        │
  ├─ ~1s   Spot: ETF                 │ Market-hours only (Mon–Fri 9:30–11:30, 13:00–15:00 CST)
  ├─ ~1s   Spot: LOF                 │ Off-hours/weekends: skipped entirely
  ├─ ~2s   Spot: US                  │ 60s between cycles during market hours
  ├─ ~2s   Spot: HK eastmoney        │
  ├─ ~2s   Spot: HK sina             │
  ├─ ~1s   Spot: futures             │
  ├─ ~1s   Spot: index               │
  └─ ~1s   Spot: bond cov ───────────┘
  │
  ├─ 💾 persist spot caches (~2 min since start)
  │
  ├─ ~1s each  Static: list caches (9 keys)  ← every ~1440 cycles
  │
  ├─ 💾 persist list caches (~30s since start)  ← before slow _build_stock_profile
  │
  └─ 5-15 min  Static: stock_profile  ← every ~1440 cycles, slowest
  │
  └─ 💾 persist all caches (cycle end)
```

## Adaptive spot refresh

Spot caches use access-based adaptive refresh to save upstream API calls. Caches not accessed by any client automatically slow down:

| Tier | Condition | Refresh interval |
|------|-----------|-----------------|
| **Warm** | Accessed < 5 min ago | Every cycle (60s) |
| **Slow** | Accessed 5–30 min ago | Every 10 cycles (~10 min) |
| **Cold** | Not accessed > 30 min | Every 60 cycles (~1 hr) |

An access (any spot endpoint request) instantly bumps the cache back to warm. Thresholds are configurable via `AKTOOLS_CACHE_WARM_S` (default 300) and `AKTOOLS_CACHE_COLD_S` (default 1800).

**Controls:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `AKTOOLS_DISABLE_SPOT` | `0` | Set `1` to skip all spot refresh |
| `AKTOOLS_SPOT_ADAPTIVE` | `1` | `0` = fixed 60s intervals, `1` = adaptive |
| `AKTOOLS_CACHE_WARM_S` | `300` | Seconds before warm→slow transition |
| `AKTOOLS_CACHE_COLD_S` | `1800` | Seconds before slow→cold transition |

**Dynamic control (API, auth required):**

```
POST /api/private/v1/cache/adaptive?enabled=0    # disable adaptive
POST /api/private/v1/cache/interval?key=stock_us_spot&interval=60  # per-cache
```

## Restart behavior

On restart, `_load_cache_from_db()` restores all caches from `cache.db` instantly. A `cache_metadata` table stores the last persist timestamp. If caches are still within their TTL:
- Spot caches refresh immediately (cycle 1) — spot data changes every cycle anyway
- Static caches are **skipped** if last refresh < `_STATIC_CACHE_TTL` (86400s) — normal schedule resumes at the next interval boundary

This prevents the slow `_build_stock_profile()` from re-running on every restart when data is still fresh.

## Persistence

All caches are persisted to `$AKTOOLS_DATA_DIR/cache.db` (SQLite, WAL mode, crash-safe). The file contains two tables:

- `persisted_cache` — `(key TEXT PRIMARY KEY, data TEXT, ts REAL)` — cache entries as JSON
- `cache_metadata` — `(key TEXT PRIMARY KEY, value TEXT)` — currently stores `last_persist` timestamp

Serialization uses `orjson.dumps()` with `OPT_SERIALIZE_NUMPY` to handle numpy types from `df.to_dict(orient="records")`. Timestamp objects are sanitized to ISO strings via `_sanitize_records()` before storage.
