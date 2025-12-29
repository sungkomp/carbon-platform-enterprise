from __future__ import annotations
import os
from rq import Worker, Queue, Connection
import redis

listen = ["default"]

def main():
    redis_url = os.getenv("REDIS_URL","redis://localhost:6379/0")
    conn = redis.from_url(redis_url)
    with Connection(conn):
        worker = Worker(map(Queue, listen))
        worker.work()

if __name__ == "__main__":
    main()
