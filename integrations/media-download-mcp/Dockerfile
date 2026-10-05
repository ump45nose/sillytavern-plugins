# Reuse the already-verified, immutable NAS runtime image; no credentials in the build.
ARG PLATFORM_RUNTIME_IMAGE=local/personal-crm:refresh-policy-0.1.3
FROM ${PLATFORM_RUNTIME_IMAGE}
COPY gateway.py /opt/mcp-platform-gateway/gateway.py
CMD ["python3", "/opt/mcp-platform-gateway/gateway.py"]
