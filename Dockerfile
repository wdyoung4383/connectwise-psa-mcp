FROM python:3.12-slim

WORKDIR /app

# Install the package (non-editable). pyproject's force-include bundles the
# OpenAPI data file into the wheel.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Run as a non-root user (defense-in-depth for a public endpoint).
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# Hosted defaults; PORT is injected by the platform at runtime.
ENV CW_MCP_TRANSPORT=http \
    CW_MCP_HOST=0.0.0.0

# Render injects PORT at runtime; EXPOSE is documentation only.
EXPOSE 8000

CMD ["python", "-m", "connectwise_mcp"]
