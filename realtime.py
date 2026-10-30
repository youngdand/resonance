"""Local SSE bridge to slskd SignalR hubs, using its supported long-poll transport.
Credentials stay in Python. Existing HTTP polling remains the recovery path.
"""

from collections import deque
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json, threading, time
import transfer_progress

CLIENT_DISCONNECTS = (
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
    TimeoutError,
)

condition = threading.Condition()
events = deque(maxlen=128)
sequence = 0
started = False


def publish(kind, data):
    global sequence
    with condition:
        sequence += 1
        events.append((sequence, kind, data))
        condition.notify_all()


def frames(data):
    return [json.loads(part) for part in data.decode("utf-8").split("\x1e") if part.strip()]


def bridge(s, hub):
    delay = 1
    while True:
        poll = None
        headers = {}
        try:
            saved = s.settings(True)
            if not saved.get("key"):
                time.sleep(5)
                continue
            base = saved["url"].rstrip("/") + "/hub/" + hub
            headers = {
                "X-API-Key": saved["key"],
                "Content-Type": "text/plain;charset=UTF-8",
            }

            def request(url, method="GET", data=None, timeout=100):
                with urlopen(
                    Request(url, data=data, method=method, headers=headers),
                    timeout=timeout,
                ) as response:
                    raw = response.read(16 * 1024 * 1024 + 1)
                    if len(raw) > 16 * 1024 * 1024:
                        raise ValueError("Hub message exceeded bridge limit")
                    return response.status, raw

            _, raw = request(base + "/negotiate?negotiateVersion=1", "POST", b"")
            negotiated = json.loads(raw)
            if not any(
                t.get("transport") == "LongPolling"
                for t in negotiated.get("availableTransports", [])
            ):
                raise ValueError("Hub does not offer long polling")
            poll = (
                base
                + "?"
                + urlencode(
                    {"id": negotiated.get("connectionToken", negotiated.get("connectionId", ""))}
                )
            )
            request(poll)  # Establish the transport before sending the protocol handshake.
            request(poll, "POST", b'{"protocol":"json","version":1}\x1e')
            delay = 1
            while True:
                status, data = request(poll)
                if status == 204:
                    break
                for message in frames(data):
                    if message.get("type") == 7 or "error" in message:
                        raise ValueError("Hub closed connection")
                    if message.get("type") != 1:
                        continue
                    target = message.get("target")
                    args = message.get("arguments", [])
                    if hub == "application" and target == "STATE" and args:
                        # Never forward OPTIONS or arbitrary state fields containing configuration.
                        state = args[0]
                        publish(
                            "state",
                            {
                                "shares": state.get("shares", {}),
                                "server": {"state": state.get("server", {}).get("state", "")},
                            },
                        )
                    elif hub == "search" and target == "RESPONSE" and len(args) >= 2:
                        response = args[1]
                        if isinstance(response, dict):
                            files = response.get("files", [])
                            if len(files) <= 2000:
                                publish(
                                    "search-response",
                                    {
                                        "id": args[0],
                                        "files": s.annotate(s.flatten([response])),
                                    },
                                )
                    elif hub == "search" and target in ("UPDATE", "DELETE") and args:
                        publish(
                            "search-update",
                            {"id": (args[0].get("id") if isinstance(args[0], dict) else args[0])},
                        )
                current = s.settings(True)
                if current.get("key") != saved["key"] or current.get("url") != saved["url"]:
                    break
        except Exception as e:
            if delay == 1:
                s.diag.event("realtime-reconnect", "INFO", hub=hub, errorType=type(e).__name__)
            # API polling already reports connection errors. Avoid duplicating them for every reconnect.
            time.sleep(delay)
            delay = min(30, delay * 2)
        finally:
            if poll:
                try:
                    with urlopen(Request(poll, method="DELETE", headers=headers), timeout=2):
                        pass
                except Exception:
                    pass


def start(s):
    global started
    with condition:
        if started:
            return
        started = True
        for hub in ("application", "search"):
            threading.Thread(target=bridge, args=(s, hub), daemon=True).start()


def stream(handler, s, direction=""):
    if direction not in ("", "uploads", "downloads"):
        raise ValueError("Invalid transfer direction.")
    start(s)
    with condition:
        cursor = sequence
    next_transfer = 0
    try:
        handler.close_connection = True
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(b": connected\n\n")
        handler.wfile.flush()
        while True:
            with condition:
                if sequence <= cursor:
                    condition.wait(timeout=1 if direction else 15)
                batch = [e for e in events if e[0] > cursor]
            if not batch:
                handler.wfile.write(b": heartbeat\n\n")
            for ident, kind, data in batch:
                handler.wfile.write(
                    (
                        "id: "
                        + str(ident)
                        + "\nevent: "
                        + kind
                        + "\ndata: "
                        + json.dumps(data, separators=(",", ":"))
                        + "\n\n"
                    ).encode()
                )
                cursor = ident
            if direction and time.monotonic() >= next_transfer:
                try:
                    progress = transfer_progress.snapshot(s, direction)
                except Exception as e:
                    handler.wfile.write(
                        (
                            "event: transfer-error\ndata: "
                            + json.dumps({"direction": direction, "error": s.diag.redact(e)})
                            + "\n\n"
                        ).encode()
                    )
                else:
                    handler.wfile.write(
                        (
                            "event: transfers\ndata: "
                            + json.dumps(progress, separators=(",", ":"))
                            + "\n\n"
                        ).encode()
                    )
                next_transfer = time.monotonic() + 1
            handler.wfile.flush()
    except CLIENT_DISCONNECTS:
        pass
