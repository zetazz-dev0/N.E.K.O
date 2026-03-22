# N.E.K.O. — Local Development Startup Guide

> Source location: `/Users/zeta/Projects/zetazz-dev0/N.E.K.O`

## Prerequisites

- Python 3.11+ (current: 3.11.7 via anaconda)
- uv (current: 0.9.26)

## First-Time Setup

```bash
cd /Users/zeta/Projects/zetazz-dev0/N.E.K.O
uv sync
```

This creates `.venv/` and installs all 354 dependencies.

## Start Services

Two servers must run. Order matters — memory server first.

If you just generated local TLS certs, keep the memory server on local HTTP and enable HTTPS on the main server only. The main server talks to memory over `http://127.0.0.1:48912`, so putting TLS directly on the memory port will break startup.

```bash
cd /Users/zeta/Projects/zetazz-dev0/N.E.K.O

# Terminal 1: Memory Server (port 48912)
uv run python memory_server.py

# Terminal 2: Main Server with local TLS (port 48911)
NEKO_SSL_CERTFILE=/Users/zeta/Projects/zetazz-dev0/N.E.K.O/192.168.2.6+2.pem \
NEKO_SSL_KEYFILE=/Users/zeta/Projects/zetazz-dev0/N.E.K.O/192.168.2.6+2-key.pem \
uv run python main_server.py
```

Or run both in background:

```bash
cd /Users/zeta/Projects/zetazz-dev0/N.E.K.O
uv run python memory_server.py > /dev/null 2>&1 &
sleep 3
NEKO_SSL_CERTFILE=/Users/zeta/Projects/zetazz-dev0/N.E.K.O/192.168.2.6+2.pem \
NEKO_SSL_KEYFILE=/Users/zeta/Projects/zetazz-dev0/N.E.K.O/192.168.2.6+2-key.pem \
uv run python main_server.py > /dev/null 2>&1 &
```

Wait ~10 seconds for full startup.

## Access

- **Web UI**: https://localhost:48911
- **API Key Settings**: https://localhost:48911/api_key
- **Character Manager**: https://localhost:48911/chara_manager
- The current mkcert cert also covers `127.0.0.1` and `192.168.2.6`

## Stop Services

```bash
pkill -f memory_server.py && pkill -f main_server.py
```

If graceful kill fails:

```bash
pkill -9 -f memory_server.py; pkill -9 -f main_server.py
```

## Verify

```bash
# Check if servers are running
curl -sk -o /dev/null -w "%{http_code}" https://localhost:48911/
# Should return: 200

# Memory server stays on HTTP for internal calls
curl -s -o /dev/null -w "%{http_code}" http://localhost:48912/health
# Should return: 200

# Check processes
ps aux | grep -E "(memory_server|main_server)" | grep -v grep
```

## Notes

- Config data is stored in `~/Documents/N.E.K.O/config/`
- Logs are in `~/Documents/N.E.K.O/logs/`
- The memory server must be running before the main server starts
- Local TLS on the main server is enabled by `NEKO_SSL_CERTFILE` + `NEKO_SSL_KEYFILE`
- If you have a proxy (Clash/Surge), the launcher auto-sets `NO_PROXY` for localhost, but running servers directly may not — check if connections fail
