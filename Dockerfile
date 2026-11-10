FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY setup.py ./setup.py
COPY components/spatialforge/src/spatialforge/scene_design.py ./components/spatialforge/src/spatialforge/scene_design.py
COPY src ./src
RUN pip install --no-cache-dir .
COPY examples ./examples
CMD ["python", "examples/offline_demo.py", "--workspace", "/data/demo"]
