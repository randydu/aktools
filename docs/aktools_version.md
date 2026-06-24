## [AKTools](https://github.com/akfamily/aktools) 版本说明

## 开发目标

1. 提供 AKShare 的 HTTP API 核心功能
2. 提供多线程访问功能
3. 增加接口状态码支持
4. 增加接口用户认证
5. 增加用户自定义数据接口功能
6. 增加主页及增强命令行支持
7. 增加测试支持
8. 增加 SQLite 数据库支持

## 开发进度

0.1.7: fix: kwargs filtering + comprehensive parameter docs audit
    1. 修复 _call_akshare_direct 在 sina 源下传递不支持的参数导致 502 的问题
    2. 交叉审计 25 个 V1 接口参数，对照 AKShare 上游函数签名和文档
    3. 修复 fund_open_hist 缺少 6 个 period 取值
    4. 标注 stock_hk_hist / stock_us_hist / fund_etf_hist 的 source 相关参数限制
    5. 丰富 AGENTS.md 和 api-reference.md 参数表（adjust 可选值、代码获取提示）

0.1.6: add: gzip compression + orjson serialization + RTK integration
    1. 新增 gzip 响应压缩（Accept-Encoding: gzip → 80-90% 体积缩减，向后兼容）
    2. 以 orjson 单次序列化替代 pandas to_json → json.loads → JSONResponse 双重序列化（26 处）
    3. RTK token 节省集成：REASONIX.md 命令规则 + .rtk/filters.toml 项目模板
    4. Dockerfile 增加 orjson 依赖
    5. api-reference.md 和 AGENTS.md 新增压缩文档

0.1.5: fix: Docker non-root user + docs anchor + version sync
    1. Docker 容器以非 root 用户运行（UID 1000），挂载卷文件不再归 root 所有
    2. docker-compose.yml 增加 user 指令支持宿主机 UID 匹配
    3. docker-entrypoint.sh 增加数据目录可写性检查
    4. 修复 api-reference.md 中 #认证 锚点失效（中文被 slugify 过滤）
    5. 同步 aktools_version.md，补齐 0.1.4→0.0.90 共 13 个版本条目

0.1.4: add: fund ETF/LOF minute-level K-line, restore 14 endpoints
    1. 新增 fund_etf_hist_intraday 和 fund_lof_hist_intraday 接口（东方财富源）
    2. 恢复 14 个丢失的接口（港股、期货、指数、可转债，全类别）
    3. 文档全面同步：所有 46 个接口验证代码到文档一致
    4. 更新 AGENTS.md 含完整接口表和数据源可用性矩阵

0.1.3: add: stock_cn_hist_intraday + stock_profile
    1. 新增 A 股分时行情接口（支持 sina/eastmoney 双数据源）
    2. 恢复 stock_profile 接口（行业与概念板块归属）
    3. 修复 Sina 分时源忽略日期范围：历史查询自动回退到 eastmoney

0.1.2: fix: fix Docker build and docs site
    1. 修复 Dockerfile 从本地源码构建（不再从 PyPI 拉取）
    2. 修复 Docs 站点（site/）在 8081 端口提供服务
    3. 新增 .dockerignore 排除构建产物

0.1.1: fix: fix startup logging and cache migration
    1. 修复启动时 cache 恢复阶段的 NameError（logger 未定义）
    2. 修复 A 股缓存键迁移（stock_list → stock_cn_list，stock_spot_* → stock_cn_spot_*）
    3. 改进启动日志：显示 cache.db 状态（缺失 / 为空 / 错误）

0.1.0: 首个稳定版本 — V1 通用 API 层（30+ 接口 / 10 大类）
    1. 智能缓存引擎：交易日感知刷新、按缓存键暂停/恢复、响应陈旧头
    2. SQLite 缓存持久化（WAL 模式），崩溃安全即时恢复
    3. API Token 认证：自动创建 root token、预配置 token 文件、Token CRUD
    4. Docker：构建脚本、compose 文件（命名卷）、部署指南
    5. 可配置数据目录（AKTOOLS_DATA_DIR）、日志级别（AKTOOLS_LOG_LEVEL）、代理（AKSHARE_PROXY）
    6. 10 大类全接口覆盖：A 股、美股、港股、ETF、LOF、场外基金、可转债、期货、指数、板块
    7. 管理接口：缓存状态、默认数据源切换、缓存控制、Token 管理

0.0.97: add: add HK stocks, LOF, funds, futures, indices, bond_cov APIs
    1. 新增港股、LOF、场外基金、期货、指数、可转债通用 API（list/spot/hist/search）
    2. 新增 index、bond_cov、fund_open 模糊搜索接口
    3. 支持按缓存键暂停/恢复（?keys= 参数，如 ?keys=stock_us_spot,stock_us_list）
    4. cache_status 响应增加 paused_keys 数组

0.0.96: add: add SQLite token auth + US stock APIs
    1. 新增 SQLite API Token 认证（替代旧 akhare/akfamily 凭据）
    2. 首次启动自动创建 root token 并打印到日志
    3. 支持预配置 Token 文件（AKTOOLS_TOKENS_FILE 环境变量，JSON 格式）
    4. 新增美股通用 API（list/spot/hist/search）
    5. 变更类接口移至 /api/private/v1/（需认证）：缓存控制、默认源切换、Token CRUD
    6. POST /auth/token 返回 410，引导用户使用 API Token

0.0.95: add: add fund/ETF APIs + smart caching
    1. 新增基金/ETF 通用 API（fund_list、fund_etf_spot、fund_etf_hist）
    2. 新增模糊搜索接口（stock_search、fund_search），<10ms 响应
    3. 新增智能缓存：交易日感知（交易时段 60s / 非交易时段 300s）、周末检测
    4. 新增缓存控制接口（pause/resume/status）
    5. 新增陈旧数据头（X-Cache-Stale、X-Cache-Age）用于实时接口
    6. 新增列表分页（page/page_size）+ X-Total-Count 响应头
    7. 修复缓存列表接口快速失败（不再回退到慢速直接调用）
    8. 修复重复的 stock_spot 刷新循环（从缓存线程中移除）

0.0.94: add: add unified A-share spot API (v1)
    1. 新增统一 A 股实时行情接口（支持 eastmoney/sina 数据源切换）
    2. 新增内存缓存 + 后台刷新（60s TTL），预热后响应 <10ms
    3. 新增缓存回退：冷数据自动从其他可用源获取
    4. 新增预热门控：初始填充期间返回 503 + Retry-After
    5. 新增缓存 A 股列表接口（每日刷新，<10ms 响应）
    6. 修复缓存回退检查所有源后再尝试慢速直接调用
    7. 修复股票名称空格问题（"柳    工" → "柳工"）

0.0.93: add: add Docker build script and docker-compose
    1. 新增 docker-build.sh 构建脚本
    2. 新增 docker-compose.yml 编排文件
    3. 新增 Docker 部署指南（docs/docker-howto.md，含海外用户配置）

0.0.92: add: add unified A-share history API (v1)
    1. 新增统一 A 股历史行情接口（支持 eastmoney/sina/tencent 三源切换）
    2. 新增代理支持（AKSHARE_PROXY 环境变量）
    3. 新增自动重试机制（网络错误重试 3 次，间隔 5 秒）
    4. 新增运行时默认数据源切换（GET/POST /api/v1/default_source）
    5. 新增 API 参考文档（docs/api-reference.md）和 V1 API 文档（docs/v1-api.md）
    6. 新增 REASONIX.md 项目知识库
    7. 修复 AKShare 异常返回 502 而非 500
    8. 修复 V1 路由注册顺序（避免被通用代理路由 /api/public/{item_id} 捕获）

0.0.91: fix: fix update python 3.14

0.0.90: fix: fix get_latest_version

0.0.89: fix: fix docs

0.0.89: fix: fix get_latest_version

0.0.88: fix: fix update typer deps

0.0.87: fix: fix update python 3.13

0.0.86: add: add log function

0.0.85: fix: update python version

0.0.84: fix: fix homepage url

0.0.83: fix: fix Dockerfile

0.0.82: fix: fix connection.py

0.0.81: add: add support for Python 3.11

0.0.80: fix: fix uvicorn run command

0.0.79: fix: fix typos in homepage.html

0.0.78: add: add test_cli.py

    1. 增加测试文件，增加项目的稳健型

0.0.77: add: add cli.py file

0.0.76: fix: fix rename master to main

0.0.75: add: add version interface

0.0.74: add: add typer for CLI

0.0.73: fix: fix tips

0.0.72: add: add type hint for CLI

0.0.71: add: add more info to homepage

0.0.70: add: add homepage

    1. 增加首页，提供更多帮助信息

0.0.69: fix: fix file path in datasets.py

0.0.68: fix: fix cookie in parameter

0.0.67: fix: fix parameter with blank character

0.0.66: fix: fix setup.py

0.0.65: fix: fix favicon.ico path

0.0.64: fix: fix favicon.ico path

0.0.63: fix: fix favicon.ico path

0.0.62: add: add favicon.ico

0.0.61: fix: fix remove dependency from akscript.html

    1. 从 akscript.html 中移除 numpy 和 matplotlib 依赖

0.0.60: add: add css and html to akscript.py

0.0.59: add: add templates

0.0.58: add: add jinja2 to setup.py

0.0.57: fix: fix setup.py

0.0.56: add: add init.py

0.0.55: add: add datasets.py

0.0.54: fix: fix PyScript demo url

0.0.53: fix: fix PyScript demo url

    1. 修复 PyScript demo url 

0.0.52: add: add pyscript support
    
    1. 新增 PyScript Demo 演示

0.0.51: add: add CORS support

    1. 新增跨域的支持

0.0.50: add: add interface docs

    1. 给接口增加描述和简要说明
    2. 修正部分函数的签名

0.0.49: add: add FastAPI docs introduction

    1. 提供文档的标题、描述及版本
    2. 文档的版本与 AKShare 的版本对应，方便查询相关接口

0.0.48: fix: fix docs

    1. 修正 URL 连接
    2. 修正部分表述错误

0.0.47: add: add tips
    
    1. 移除路径输出
    2. 在终端窗口输出：`http://127.0.0.1:8080/docs` 类似的链接，用户可以一键直达接口文档

0.0.46: fix: fix setup.py

    1. 在 setup.py 中增加 `python-multipart` 的依赖

0.0.45: add: add module format support
    
    1. 把核心 API 模块和登录模块拆分开
    2. 把项目结构化，有利于后续开发
    3. 增加 run.py 文件作为项目的主入口

0.0.44: add: add support response status code

    1. 增加用户认证模块，但是该程序目前并没有采用数据库，还是在测试中
    2. 目前用户可以通过 username 为 `akshare` 和 password 为 `akfamily` 来获取 token
    3. 通过在请求头中设置 token 参数来访问接口

0.0.43: add: add support response status code
    
    1. 增加返回状态码，用户可以通过状态码来判断是否获取到数据
    2. 修正一些表述错处