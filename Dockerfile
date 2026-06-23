# AKTools — HTTP API for AKShare
FROM python:3.13-slim-bookworm

# 升级 pip
RUN pip install --upgrade pip

# 安装运行时依赖
RUN pip install --no-cache-dir akshare fastapi uvicorn gunicorn python-multipart jinja2 orjson \
    -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com --upgrade

# 复制项目源码（含预构建的 site/ 目录）
COPY . /app/src/

# 入口脚本
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# 数据目录
RUN mkdir -p /app/data
ENV AKTOOLS_DATA_DIR=/app/data
ENV PYTHONPATH=/app/src

# 创建非 root 用户（UID 1000 匹配大多数宿主机用户，确保卷挂载权限正确）
RUN groupadd -g 1000 aktools && useradd -u 1000 -g 1000 -d /app aktools
RUN chown -R aktools:aktools /app
USER aktools

# 默认启动
EXPOSE 8080 8081
CMD ["/app/docker-entrypoint.sh"]
