FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY setup.py MANIFEST.in ./
COPY src/benchforge_core ./src/benchforge_core
COPY src/backend/benchforge_backend/scene_design.py ./src/backend/benchforge_backend/scene_design.py
RUN pip install --no-cache-dir .
ENTRYPOINT ["benchforge"]
CMD ["--help"]
