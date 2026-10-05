# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
"""Briefly retain authoritative completion while the task list catches up."""
from copy import deepcopy
import time
from util.task_checkpoint import task_key


class RecentCompletions:
    def __init__(self, ttl=600, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self.confirmed = {}

    def remember(self, task):
        if int(task.get('task_type', 0)) in (1, 2) and float(task.get('progress') or 0) >= 100:
            self.confirmed[task_key(task)] = (self.clock(), deepcopy(task))

    def apply(self, tasks):
        now = self.clock()
        self.confirmed = {key: value for key, value in self.confirmed.items() if now - value[0] < self.ttl}
        result = deepcopy(tasks)
        for task in result:
            key = task_key(task)
            if key not in self.confirmed:
                continue
            if float(task.get('progress') or 0) >= 100:
                self.confirmed.pop(key)
            else:
                task.update(progress=100, score=self.confirmed[key][1].get('score'))
        return result
