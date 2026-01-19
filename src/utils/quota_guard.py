# src/utils/quota_guard.py
class QuotaGuard:
    def __init__(self, limit: int, name: str):
        self.limit = limit
        self.name = name
        self.count = 0

    def tick(self, n: int = 1):
        self.count += n
        if self.count >= self.limit:
            raise RuntimeError(f"[STOP] {self.name} quota guard hit: {self.count}/{self.limit}")
