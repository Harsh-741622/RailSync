from __future__ import annotations

def minute_to_clock(minute: int) -> str:
    total = 9 * 60 + int(minute)
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"

def clock_to_minute(value: str) -> int:
    h, m = value.split(":", 1)
    return int(h) * 60 + int(m) - 9 * 60
