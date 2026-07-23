#!/usr/bin/env python3
"""TLS terminating proxy: https://<host>:8443  ->  http://127.0.0.1:8080
Raw TCP forwarding after TLS handshake, so HTTP + WebSockets both work unchanged.
Needed because browsers require a secure context for microphone access off-localhost.
Run: venvs/wlk/bin/python scripts/https_proxy.py  (run_app.sh starts it automatically)
"""
import asyncio
import ssl
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ("127.0.0.1", 8080)
LISTEN = ("0.0.0.0", 8443)


async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, asyncio.IncompleteReadError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_r, client_w):
    try:
        back_r, back_w = await asyncio.open_connection(*BACKEND)
    except OSError:
        client_w.close()
        return
    await asyncio.gather(pipe(client_r, back_w), pipe(back_r, client_w))


async def main():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(ROOT / "certs/dia.crt", ROOT / "certs/dia.key")
    server = await asyncio.start_server(handle, *LISTEN, ssl=ctx)
    print(f"https proxy: {LISTEN[0]}:{LISTEN[1]} -> {BACKEND[0]}:{BACKEND[1]}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
