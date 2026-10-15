FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY sentinel ./sentinel
EXPOSE 8100
# Seed the graph only if it is empty, then serve the API (which spawns the MCP server over stdio).
# Hosts like Render pass the port in $PORT.
CMD ["sh", "-c", "python -m sentinel.seed --if-empty && uvicorn sentinel.api.main:app --host 0.0.0.0 --port ${PORT:-8100}"]
