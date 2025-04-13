FROM python:3.7-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "examples.main:app_", "--host", "0.0.0.0", "--port", "8000"] 