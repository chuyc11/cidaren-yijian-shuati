# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
"""Read dictionary entries ahead of time without sharing mutable task state."""
from concurrent.futures import CancelledError, ThreadPoolExecutor, TimeoutError
from threading import Event, Lock, local


class WordPrefetch:
    def __init__(self, entries, cache, fetch, session_factory, max_workers=2, fatal_errors=()):
        self.cache, self.fetch = cache, fetch
        self.session_factory, self.fatal_errors = session_factory, fatal_errors
        self.stopped = Event()
        self.lock, self.thread_state = Lock(), local()
        self.sessions, self.futures = [], {}
        self.fatal_error = None
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='dictionary')
        for course, unit, word in entries:
            key = (str(course), str(unit), word.strip().lower())
            if key not in self.futures and cache.get(key) is None:
                self.futures[key] = self.executor.submit(self._load, key, word)

    def _load(self, key, word):
        if self.stopped.is_set():
            return None
        if not hasattr(self.thread_state, 'session'):
            session = self.session_factory()
            self.thread_state.session = session
            with self.lock:
                self.sessions.append(session)
        try:
            data = self.fetch(key[0], key[1], word, self.thread_state.session)
            if not self.stopped.is_set() and isinstance(data, dict) and (data.get('means') or data.get('options')):
                self.cache.put(key, data)
                return data
        except self.fatal_errors as exc:
            with self.lock:
                self.fatal_error = self.fatal_error or exc
            self.stopped.set()
            raise
        return None

    def raise_if_failed(self):
        with self.lock:
            error = self.fatal_error
        if error is not None:
            raise error

    def wait(self, key, timeout=0.25):
        """Use an in-flight result briefly; failed/slow reads get a normal retry."""
        self.raise_if_failed()
        future = self.futures.get(key)
        if future is None or self.stopped.is_set():
            return None
        try:
            future.result(timeout=timeout)
        except self.fatal_errors:
            raise
        except (TimeoutError, CancelledError):
            return None
        except Exception:
            # Never retain a failed dictionary entry in the cache.
            return None
        return self.cache.get(key)

    def close(self):
        """Cancel queued reads; running HTTP calls close their own sessions."""
        self.stopped.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        # A session can be closed only after its thread has finished using it.
        for future in self.futures.values():
            future.add_done_callback(self._close_idle_sessions)
        self._close_idle_sessions()

    def _close_idle_sessions(self, _future=None):
        with self.lock:
            if any(future.running() for future in self.futures.values()):
                return
            sessions, self.sessions = self.sessions, []
        for session in sessions:
            session.close()
