"""One-second, shared transfer snapshots for SSE and automatic reconnect fallback."""

import math, threading, time
import features, album_jobs

locks = {d: threading.Lock() for d in ("downloads", "uploads")}
caches = {}
samples = {}
failures = {}


def number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, value) if math.isfinite(value) else 0


def add_speeds(direction, rows, now):
    current = {}
    for f in rows:
        key = (str(f.get("username", "")), str(f.get("id") or f.get("filename", "")))
        count = number(f.get("bytesTransferred"))
        previous = samples.get(direction, {}).get(key)
        state = str(f.get("state", "")).lower()
        active = ("transferring" in state or "inprogress" in state) and not any(
            x in state for x in ("completed", "succeeded", "errored", "cancelled", "rejected")
        )
        speed = number(f.get("averageSpeed")) if active else 0
        if active and previous:
            elapsed = now - previous[0]
            delta = count - previous[1]
            if 0 < elapsed <= 10 and delta >= 0:
                speed = delta / elapsed
        f["currentSpeed"] = speed
        current[key] = (now, count)
    samples[direction] = current
    return rows


def snapshot(s, direction):
    if direction not in locks:
        raise ValueError("Invalid transfer direction.")
    with locks[direction]:
        now = time.monotonic()
        cached = caches.get(direction)
        if cached and now - cached[0] < 1:
            return cached[1]
        failed = failures.get(direction)
        if failed and now < failed["retryAt"]:
            raise ValueError(failed["message"])
        try:
            remote = s.slsk("transfers/" + direction)
            if not isinstance(remote, list):
                raise ValueError(
                    "slskd returned an invalid transfer list. Previous progress has been kept."
                )
            rows = add_speeds(direction, features.transfer_rows(remote), time.monotonic())
            if direction == "downloads":
                # sync_downloads expects the native nested response; enrich those same row objects by key.
                speed = {
                    (f["username"], f.get("id") or f["filename"]): f["currentSpeed"] for f in rows
                }
                for user in remote:
                    for directory in user.get("directories", []):
                        for f in directory.get("files", []):
                            f["currentSpeed"] = speed.get(
                                (user["username"], f.get("id") or f["filename"]), 0
                            )
                requests = s.sync_downloads(remote)
                data = {
                    "direction": direction,
                    "requests": requests,
                    "albumJobs": album_jobs.list_jobs(s),
                }
            else:
                data = {"direction": direction, "uploads": rows}
            data["sampledAt"] = time.time()
            caches[direction] = (time.monotonic(), data)
            failures.pop(direction, None)
            return data
        except Exception as e:
            delay = min(8, failed["delay"] * 2 if failed else 1)
            failures[direction] = {
                "message": str(e),
                "delay": delay,
                "retryAt": time.monotonic() + delay,
            }
            raise
