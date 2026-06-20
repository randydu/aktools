# AKTools — HTTP API for AKShare
FROM python:3.13-slim-bookworm

# 升级 pip
RUN pip install --upgrade pip

# 安装运行时依赖
RUN pip install --no-cache-dir akshare fastapi uvicorn gunicorn \
    -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com --upgrade

# 复制项目源码
COPY . /app/src/

# 复制预构建的文档站点（由 docker-build.sh 生成）
COPY site/ /app/site/

# 入口脚本
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# 数据目录
RUN mkdir -p /app/data
ENV AKTOOLS_DATA_DIR=/app/data
ENV PYTHONPATH=/app/src

# 默认启动
EXPOSE 8080 8081
CMD ["/app/docker-entrypoint.sh"]
