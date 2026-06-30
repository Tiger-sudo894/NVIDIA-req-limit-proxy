# NVIDIA Request Limit Proxy

A small local HTTP proxy for NVIDIA's hosted API. It serializes outbound requests to a configurable requests-per-minute limit and retries transient upstream errors, which helps avoid 429s when multiple tools or agents share one NVIDIA API key.

## What it does

- Proxies requests to `https://integrate.api.nvidia.com` by default.
- Enforces a process-wide RPM delay before every upstream request.
- Retries `429`, `500`, `502`, `503`, and `504` responses.
- Uses `Retry-After` when NVIDIA provides it.
- Accepts a global `NVIDIA_API_KEY` or forwards each request's incoming `Authorization` header.
- Exposes `GET /healthz` for basic status checks.
- Uses only the Python standard library.

## Quick start

```bash
export NVIDIA_API_KEY="your-nvidia-api-key"
export NVIDIA_PROXY_RPM=20
python3 nvidia_rate_limit_proxy.py
```

The proxy listens on:

```text
http://127.0.0.1:18001
```

Point clients at the proxy instead of NVIDIA's upstream base URL. For OpenAI-compatible NVIDIA endpoints, use:

```text
http://127.0.0.1:18001/v1
```

## Example request

```bash
curl http://127.0.0.1:18001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "messages": [{"role": "user", "content": "Say hello"}]
  }'
```

If `NVIDIA_API_KEY` is not set, include your own authorization header:

```bash
curl http://127.0.0.1:18001/v1/models \
  -H "Authorization: Bearer your-nvidia-api-key"
```

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `NVIDIA_API_KEY` | empty | API key used for all upstream requests. If unset, the proxy forwards incoming `Authorization`. |
| `NVIDIA_PROXY_RPM` | `20` | Maximum outbound request rate per minute. |
| `NVIDIA_PROXY_PORT` | `18001` | Local listen port. |
| `NVIDIA_UPSTREAM_BASE` | `https://integrate.api.nvidia.com` | Upstream API base URL. |
| `NVIDIA_PROXY_MAX_RETRIES` | `5` | Retry count for transient upstream failures. |

## Health check

```bash
curl http://127.0.0.1:18001/healthz
```

Example response:

```json
{
  "ok": true,
  "rpm": 20,
  "minIntervalSeconds": 3.0,
  "upstream": "https://integrate.api.nvidia.com"
}
```

## Notes

- The limiter is in-memory and applies only within one proxy process.
- The server binds to `127.0.0.1` intentionally. Put it behind a properly secured reverse proxy if you need remote access.
- Do not commit real API keys. Use environment variables or your process manager's secret handling.
