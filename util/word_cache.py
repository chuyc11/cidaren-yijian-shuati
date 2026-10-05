# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
"""Bounded, task-instance dictionary cache; no credentials or session state."""
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
import time


class WordCache:
    def __init__(self, maxsize=512, ttl=1800, clock=time.monotonic):
        self.maxsize, self.ttl, self.clock = maxsize, ttl, clock
        self.entries = OrderedDict()
        self.lock = RLock()
        self.hits = self.misses = 0

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry and self.clock() - entry[0] < self.ttl:
                self.entries.move_to_end(key)
                self.hits += 1
                return deepcopy(entry[1])
            self.entries.pop(key, None)
            self.misses += 1
            return None

    def put(self, key, value):
        with self.lock:
            self.entries[key] = (self.clock(), deepcopy(value))
            self.entries.move_to_end(key)
            while len(self.entries) > self.maxsize:
                self.entries.popitem(last=False)
