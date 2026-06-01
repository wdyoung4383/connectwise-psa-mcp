FROM python:3.12-slim

WORKDIR /app

# Install the package (non-editable). pyproject's force-include bundles the
# OpenAPI data file into the wheel.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Hosted defaults; PORT is injected by the platform at runtime.
ENV CW_MCP_TRANSPORT=http \
    CW_MCP_HOST=0.0.0.0

EXPOSE 8000

CMD ["python", "-m", "connectwise_mcp"]
