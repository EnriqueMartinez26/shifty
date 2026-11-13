"""An in-memory Redis Lua double for SMTP budget unit and mail tests."""

import asyncio
from collections import defaultdict
from typing import Any

from core import mail_budget


class AtomicMailBudgetRedis:
    """Serialize script calls and implement the two mail-budget transitions."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = defaultdict(dict)
        self.lock = asyncio.Lock()

    async def eval(self, script: str, numkeys: int, *args: Any) -> list[int]:
        assert numkeys == 2
        counts_key, messages_key, message_id, *values = args
        async with self.lock:
            counts = self.hashes[counts_key]
            messages = self.hashes[messages_key]
            if script == mail_budget._RESERVE_SCRIPT:
                token, priority, budget, reserve, alert_at, _ttl = values
                state = messages.get(message_id)
                admitted = int(counts.get("admitted", "0"))
                if state and state != "deferred":
                    if state == f"reserved:{token}":
                        return [1, admitted, 0]
                    return [-1 if state == "dropped" else 2, admitted, 0]
                budget = int(budget)
                reserve = int(reserve)
                alert_at = int(alert_at)
                if (
                    budget > 0
                    and priority != "critical"
                    and admitted >= budget - reserve
                ):
                    if priority == "low":
                        messages[message_id] = "dropped"
                        counts["dropped"] = str(int(counts.get("dropped", "0")) + 1)
                        return [-1, admitted, 0]
                    if state != "deferred":
                        counts["deferred"] = str(int(counts.get("deferred", "0")) + 1)
                    messages[message_id] = "deferred"
                    return [0, admitted, 0]
                if budget > 0 and admitted >= budget:
                    messages[message_id] = "dropped"
                    counts["dropped"] = str(int(counts.get("dropped", "0")) + 1)
                    return [-1, admitted, 0]
                messages[message_id] = f"reserved:{token}"
                admitted += 1
                counts["admitted"] = str(admitted)
                priority_key = f"priority:{priority}"
                counts[priority_key] = str(int(counts.get(priority_key, "0")) + 1)
                alert = int(
                    budget > 0 and admitted >= alert_at and counts.get("alerted") != "1"
                )
                if alert:
                    counts["alerted"] = "1"
                return [1, admitted, alert]

            assert script == mail_budget._FINISH_SCRIPT
            token, outcome, _ttl = values
            if messages.get(message_id) != f"reserved:{token}":
                return [0]
            messages[message_id] = outcome
            counts[outcome] = str(int(counts.get(outcome, "0")) + 1)
            return [1]

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes[key])
