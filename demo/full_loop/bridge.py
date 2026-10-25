"""DEMO-ONLY loopback bridges between the Replit HTTPS proxy and local services.

Replit terminates TLS for https://<dev-domain>:8000 and :3000 and forwards plain
HTTP to the same local ports. This bridge then:

* :8000 -> the company service's private Unix socket. It rewrites Host to the
  exact public origin's host:port (the Replit proxy drops the port), sets
  X-Forwarded-Proto: https (the only forwarded header waitress trusts) and drops
  every client/proxy-supplied forwarding header.
* :3000 -> the LiteLLM proxy on 127.0.0.1:4000, for POST /v1/chat/completions
  only. Streaming responses are piped through unchanged.

One request per connection (Connection: close) keeps the relay simple and makes
interrupted streams surface as interrupted, never as silent retries.

Usage: bridge.py <public-host> <company-socket> [litellm-port]
"""

import asyncio
import sys

HEAD_LIMIT = 65536
DROP = {"host", "connection", "keep-alive", "proxy-connection", "x-forwarded-for", "x-forwarded-proto",
        "x-forwarded-host", "x-forwarded-port", "x-real-ip", "forwarded", "upgrade", "te", "trailer"}


async def _read_head(reader):
    head = await reader.readuntil(b"\r\n\r\n")
    if len(head) > HEAD_LIMIT:
        raise ValueError("head too large")
    lines = head[:-4].decode("latin-1").split("\r\n")
    method, target, version = lines[0].split(" ", 2)
    headers = []
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers.append((name.strip(), value.strip()))
    return method, target, version, headers


def _respond(writer, status, reason):
    body = f"{status} {reason}\n".encode()
    writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n"
                 f"Cache-Control: no-store\r\nConnection: close\r\n\r\n".encode() + body)


async def _pipe(reader, writer):
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass


async def relay(reader, writer, *, connect, host, allowed, body_limit, timeout):
    upstream_writer = None
    try:
        method, target, version, headers = await asyncio.wait_for(_read_head(reader), 30)
        if allowed is not None and (method, target.split("?", 1)[0]) not in allowed:
            _respond(writer, 404, "Not Found")
            return
        names = {name.lower(): value for name, value in headers}
        if "chunked" in names.get("transfer-encoding", "").lower():
            _respond(writer, 411, "Length Required")
            return
        length = int(names.get("content-length", "0") or "0")
        if length < 0 or length > body_limit:
            _respond(writer, 413, "Payload Too Large")
            return
        body = await asyncio.wait_for(reader.readexactly(length), 60) if length else b""
        kept = [(name, value) for name, value in headers
                if name.lower() not in DROP and not name.lower().startswith("x-replit")]
        upstream_reader, upstream_writer = await connect()
        lines = [f"{method} {target} HTTP/1.1", f"Host: {host}", "Connection: close"]
        if host is not None and allowed is None:
            lines.append("X-Forwarded-Proto: https")
        lines += [f"{name}: {value}" for name, value in kept]
        upstream_writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body)
        await upstream_writer.drain()
        await asyncio.wait_for(_pipe(upstream_reader, writer), timeout)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError, ConnectionError, OSError):
        if not writer.is_closing():
            try:
                _respond(writer, 502, "Bad Gateway")
            except Exception:
                pass
    finally:
        for stream in (upstream_writer, writer):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass


async def main():
    public_host, socket_path = sys.argv[1], sys.argv[2]
    litellm_port = int(sys.argv[3]) if len(sys.argv) > 3 else 4000
    company = await asyncio.start_server(
        lambda r, w: relay(r, w, connect=lambda: asyncio.open_unix_connection(socket_path), host=f"{public_host}:8000",
                           allowed=None, body_limit=131072, timeout=60),
        "0.0.0.0", 8000, limit=HEAD_LIMIT)
    gateway = await asyncio.start_server(
        lambda r, w: relay(r, w, connect=lambda: asyncio.open_connection("127.0.0.1", litellm_port), host=f"127.0.0.1:{litellm_port}",
                           allowed={("POST", "/v1/chat/completions")}, body_limit=8 * 1024 * 1024, timeout=600),
        "0.0.0.0", 3000, limit=HEAD_LIMIT)
    print("bridge listening on :8000 (company) and :3000 (gateway)", flush=True)
    async with company, gateway:
        await asyncio.gather(company.serve_forever(), gateway.serve_forever())


if __name__ == "__main__":
    asyncio.run(main())
