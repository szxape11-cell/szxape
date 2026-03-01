# ⚔️ 三省六部 · Demo Dashboard
# docker run -p 7891:7891 cft0808/sansheng-demo
# Then open: http://localhost:7891

FROM python:3.11-slim

WORKDIR /app

# 复制看板核心文件
COPY dashboard/ ./dashboard/
COPY scripts/ ./scripts/

# 注入演示数据（data目录由demo_data提供）
COPY docker/demo_data/ ./data/

# 非 root 用户运行
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 7891

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7891/healthz')" || exit 1

CMD ["python3", "dashboard/server.py", "--host", "0.0.0.0", "--port", "7891"]
