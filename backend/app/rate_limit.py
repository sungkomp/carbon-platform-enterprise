from __future__ import annotations
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

def build_limiter() -> Limiter:
    per_min = os.getenv("RATE_LIMIT_PER_MINUTE","120")
    return Limiter(key_func=get_remote_address, default_limits=[f"{per_min}/minute"])
