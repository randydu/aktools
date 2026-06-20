# Docker 部署指南

## 快速启动

```sh
# 1. 构建镜像
./docker-build.sh

# 2. 启动服务
docker compose up -d

# 3. 验证
curl http://127.0.0.1:8080/version
```

服务启动后访问：
- API 文档 (Swagger)：`http://127.0.0.1:8080/docs`
- 首页：`http://127.0.0.1:8080/`
- 项目文档 (MkDocs)：`http://127.0.0.1:8081`

---

## 环境变量

在 `docker-compose.yml` 中配置，或通过 `docker run -e` 传入。

| 变量 | 必填 | 默认值 | 说明 |
| ----- | :---: | ----- | ----- |
| `AKSHARE_PROXY` | 否 | 空 | HTTP/HTTPS 代理地址，如 `http://host.docker.internal:7890` |
| `AKSHARE_DEFAULT_SOURCE` | 否 | `eastmoney` | 默认数据源：`eastmoney` / `sina` / `tencent` |
`AKTOOLS_TOKENS_FILE` | 否 | 空 | 预配置 Token 的 JSON 文件路径 |
`AKTOOLS_DATA_DIR` | 否 | `./data/` | 持久化数据目录（缓存、日志、Token） |

### 海外用户配置

如果您在海外访问，建议在 `docker-compose.yml` 中设置：

```yaml
environment:
  AKSHARE_PROXY: "http://host.docker.internal:7890"  # 替换为您的代理地址
  AKSHARE_DEFAULT_SOURCE: "sina"                       # 或 tencent
```

其中 `host.docker.internal` 在 Linux 上需 Docker 20.10+，旧版本请替换为主机 IP。

---

## 自定义端口

修改 `docker-compose.yml` 中的端口映射：

```yaml
ports:
  - "9000:8080"   # 主机端口 9000 → 容器端口 8080
```

---

## 无 docker-compose 场景

```sh
# 构建
docker build -t aktools .

# 运行（直连，无代理）
docker run -d -p 8080:8080 --name aktools aktools

# 运行（带代理和默认数据源）
docker run -d -p 8080:8080 --name aktools \
  -e AKSHARE_PROXY=http://192.168.1.100:7890 \
  -e AKSHARE_DEFAULT_SOURCE=sina \
  aktools
```

---

## 常用管理命令

```sh
# 查看日志
docker compose logs -f

# 重启
docker compose restart

# 停止
docker compose down

# 更新镜像后重建
./docker-build.sh && docker compose up -d --force-recreate
```

---

## 运行时切换数据源

无需重启容器，通过 API 即可切换默认数据源：

```sh
# 查看当前默认源
curl http://127.0.0.1:8080/api/public/v1/default_source

# 切换为 Sina
curl -X POST "http://127.0.0.1:8080/api/private/v1/default_source?source=sina"
```

切换后仅当次进程生命周期有效。容器重启后回退为 `AKSHARE_DEFAULT_SOURCE` 环境变量的值。

---

## 验证数据源可用性

```sh
# 测试 Sina 源
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_hist?symbol=600000&source=sina"

# 测试 Tencent 源
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_hist?symbol=000001&source=tencent"

# 测试 East Money 源（默认）
curl "http://127.0.0.1:8080/api/public/v1/stock_zh_a_hist?symbol=600000&source=eastmoney"
```
