FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY examples ./examples
CMD ["python", "examples/offline_demo.py", "--workspace", "/data/demo"]
