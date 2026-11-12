"""Small public sensor caches; no native sources, GT or machine paths."""
from pathlib import Path
from collections import OrderedDict
from threading import RLock


class _BoundedCache:
    """Small process-local LRU; callers supply real file-version keys, no hashes."""
    def __init__(self, entries, max_bytes=None):
        self.limit, self.max_bytes = entries, max_bytes
        self.values = OrderedDict()
        self.bytes = self.hits = self.misses = 0
        self.lock = RLock()

    @staticmethod
    def _weight(value):
        if isinstance(value, (tuple, list)):
            return sum(_BoundedCache._weight(v) for v in value)
        return int(getattr(value, 'nbytes', 0))

    def get(self, key):
        with self.lock:
            if key not in self.values:
                self.misses += 1
                return None
            self.hits += 1
            self.values.move_to_end(key)
            return self.values[key][0]

    def remember(self, key, value):
        weight = self._weight(value)
        with self.lock:
            if key in self.values:
                self.bytes -= self.values.pop(key)[1]
            if self.max_bytes is not None and weight > self.max_bytes:
                return value
            self.values[key] = (value, weight)
            self.bytes += weight
            while len(self.values) > self.limit or (self.max_bytes is not None and self.bytes > self.max_bytes):
                _, (_, removed) = self.values.popitem(last=False)
                self.bytes -= removed
        return value

    def load(self, key, loader):
        with self.lock:
            value = self.get(key)
            if value is not None:
                return value
            return self.remember(key, loader())

    def stats(self):
        with self.lock:
            return {'entries': len(self.values), 'bytes': self.bytes,
                    'hits': self.hits, 'misses': self.misses,
                    'max_entries': self.limit, 'max_bytes': self.max_bytes}


def _file_version(path):
    file = Path(path).resolve(strict=True)
    stat = file.stat()
    return str(file), stat.st_size, stat.st_mtime_ns
