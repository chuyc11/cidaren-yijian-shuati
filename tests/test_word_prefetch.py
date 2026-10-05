"""Verify dictionary concurrency, failure recovery and task-worker shutdown offline."""
from contextlib import ExitStack
from copy import deepcopy
import logging
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from threading import Event, Lock, get_ident
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from PyQt6.QtWidgets import QApplication

import main as app
import api.main_api as api
import api.request_header as headers
from publicInfo.publicInfo import PublicInfo
from util.word_cache import WordCache
from util.word_prefetch import WordPrefetch
from test_class_tasks import TestServer, response

ROOT = Path(__file__).resolve().parents[1]


class OwnedSession:
    def __init__(self, read):
        self.owner, self.read = get_ident(), read
        self.headers, self.closed = {}, False

    def mount(self, *_args):
        pass

    def get(self, url, **kwargs):
        if get_ident() != self.owner or self.closed:
            raise AssertionError('A dictionary session was shared or closed during a read')
        if 'Course/StudyWordInfo?' not in url:
            raise AssertionError('Only independent dictionary reads may run in the pool')
        return self.read(url)

    def close(self):
        self.closed = True


class PrefetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        logging.disable(logging.CRITICAL)
        block = patch.object(headers.requests.Session, 'request', side_effect=AssertionError('External HTTP disabled'))
        block.start()
        self.addCleanup(block.stop)

    def pool(self, entries, fetch, **kwargs):
        pool = WordPrefetch(entries, WordCache(), fetch, lambda: OwnedSession(lambda _: None), **kwargs)
        self.addCleanup(pool.close)
        return pool

    def drain(self, pool):
        for future in pool.futures.values():
            future.result(timeout=2)

    def test_card_submission_overlaps_isolated_dictionary_reads_and_closes_sessions(self):
        self.exercise_worker(cards=True)

    def test_resume_on_graded_question_still_preloads_dictionary_and_closes_sessions(self):
        self.exercise_worker(cards=False)

    def exercise_worker(self, cards):
        entered, release, lock = Event(), Event(), Lock()
        sessions, seen = [], []

        class CardServer(TestServer):
            def details(self):
                data = super().details()
                data['word_list'] = [dict(data['word_list'][0], word=word) for word in
                                     ['abandon'] + [f'word{index}' for index in range(7)]]
                return data

            def get(self, url, params=None, **kwargs):
                if url.endswith('StartAnswer'):
                    return response(self.question(card=cards))
                return super().get(url, params, **kwargs)

            def post(self, url, data=None, **kwargs):
                if cards and url.endswith('SubmitAnswerAndSave') and not self.card_sent:
                    self.card_sent = True
                    if not entered.wait(2):
                        raise AssertionError('Dictionary reads did not start during cards')
                    if info.now_unit != '' or info.word_query_result:
                        raise AssertionError('A background read changed foreground task state')
                    release.set()
                    return response(self.question())
                return super().post(url, data, **kwargs)

        def read(url):
            query = parse_qs(urlparse(url).query)
            with lock:
                seen.append(query['word'][0])
                if len(seen) == 2:
                    entered.set()
            if not release.wait(2):
                raise AssertionError('Card submission did not overlap dictionary reads')
            return response({'means': [{'mean': ['v 放弃'], 'usages': []}]})

        def factory():
            session = OwnedSession(read)
            sessions.append(session)
            return session

        server = CardServer()
        server.headers = {'Usertoken': 'offline-placeholder'}
        info = PublicInfo(str(ROOT))
        info._fast_mode = True
        info._self_learn_pool = info._self_learn_lib = False
        task = {'task_name': 'Offline cards', 'task_type': 1, 'task_id': -1, 'release_id': 200, 'course_id': 'BOOK'}
        worker = app.TaskWorker([task], public_info=info, logger=Mock())
        finished, errors = [], []
        worker.task_finished.connect(finished.append)
        worker.task_error.connect(errors.append)
        try:
            if not cards:
                release.set()
            with ExitStack() as stack:
                for name in ('class_task_request', 'rqs_session', 'rqs2_session', 'rqs3_session'):
                    stack.enter_context(patch.object(headers, name, server))
                stack.enter_context(patch.object(headers.requests, 'Session', side_effect=factory))
                stack.enter_context(patch.object(app, 'ai_answer', side_effect=AssertionError('AI unnecessary')))
                worker.start()
                deadline = time.monotonic() + 5
                while worker.isRunning() and time.monotonic() < deadline:
                    self.qt.processEvents()
                self.assertTrue(worker.wait(2000), 'Task QThread did not stop')
                self.qt.processEvents()
                deadline = time.monotonic() + 2
                while any(not session.closed for session in sessions) and time.monotonic() < deadline:
                    self.qt.processEvents()
            self.assertEqual(errors, [])
            self.assertEqual(len(finished), 1)
            self.assertEqual(info.right_count, 1)
            self.assertEqual(len(server.verifications), 1)
            self.assertTrue(info._word_prefetch_started)
            self.assertIsNone(info._word_prefetch)
            self.assertGreater(len(sessions), 0)
            self.assertLessEqual(len(sessions), 2)
            self.assertTrue(all(session.closed for session in sessions))
        finally:
            release.set()
            worker.close_word_prefetch()

    def test_duplicate_reads_are_coalesced_and_cache_keeps_course_and_unit_scope(self):
        reads = []
        def fetch(course, unit, word, session):
            reads.append((course, unit, word))
            return {'means': [{'mean': [f'{course}:{unit}']} ]}
        pool = self.pool([('A', 'U', 'word'), ('A', 'U', 'WORD'), ('A', 'V', 'word'), ('B', 'U', 'word')], fetch)
        self.drain(pool)
        self.assertEqual(len(reads), 3)
        self.assertEqual(pool.wait(('A', 'V', 'word'))['means'][0]['mean'], ['A:V'])
        self.assertEqual(pool.wait(('B', 'U', 'word'))['means'][0]['mean'], ['B:U'])

    def test_failed_prefetch_is_retried_by_foreground_without_poisoning_cache(self):
        def fail(*args):
            raise headers.exceptions.ReadTimeout('Offline transient timeout')
        pool = self.pool([('BOOK', 'U', 'abandon')], fail)
        with self.assertRaises(headers.exceptions.ReadTimeout):
            self.drain(pool)
        info = SimpleNamespace(course_id='BOOK', now_unit='U', is_self_built=False, fast_mode=True,
                               _word_cache=pool.cache, _word_prefetch=pool)
        session = SimpleNamespace(get=Mock(return_value=response({'means': [{'mean': ['v 放弃']}]})))
        with patch.object(headers, 'rqs_session', session):
            api.query_word(info, 'abandon')
        session.get.assert_called_once()
        self.assertEqual(info.word_query_result['means'][0]['mean'], ['v 放弃'])

    def test_security_failure_surfaces_even_if_requested_word_is_already_cached(self):
        def fail(*args):
            raise api.SecurityVerifyError('Offline validation required')
        pool = self.pool([('BOOK', 'U', 'abandon')], fail, fatal_errors=(api.SecurityVerifyError,))
        with self.assertRaises(api.SecurityVerifyError):
            self.drain(pool)
        pool.cache.put(('BOOK', 'U', 'abandon'), {'means': [{'mean': ['v 放弃']}]})
        info = SimpleNamespace(course_id='BOOK', now_unit='U', is_self_built=False, fast_mode=True,
                               _word_cache=pool.cache, _word_prefetch=pool)
        with self.assertRaises(api.SecurityVerifyError):
            api.query_word(info, 'abandon')

    def test_stop_cancels_queued_reads_and_waits_to_close_active_sessions(self):
        release, both_started, lock = Event(), Event(), Lock()
        reads = []
        def fetch(course, unit, word, session):
            with lock:
                reads.append(word)
                if len(reads) == 2:
                    both_started.set()
            if not release.wait(2):
                raise AssertionError('Test failed to release active read')
            self.assertFalse(session.closed)
            return {'means': [{'mean': ['v 放弃']}]}
        pool = self.pool([('BOOK', 'U', f'word{index}') for index in range(12)], fetch)
        try:
            self.assertTrue(both_started.wait(2))
            active = [future for future in pool.futures.values() if future.running()]
            info = SimpleNamespace(_word_prefetch=pool)
            worker = app.TaskWorker([], public_info=info, logger=Mock())
            worker._word_prefetch = pool
            started = time.monotonic()
            worker.stop()
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertIsNone(info._word_prefetch)
            self.assertEqual(sum(future.cancelled() for future in pool.futures.values()), 10)
            self.assertTrue(all(not session.closed for session in pool.sessions))
            release.set()
            for future in active:
                future.result(timeout=2)
            # Completion callbacks close sessions after the last active read.
            pool.close()
            self.assertEqual(len(reads), 2)
            self.assertIsNone(pool.cache.get(('BOOK', 'U', reads[0])))
            self.assertEqual(pool.sessions, [])
        finally:
            release.set()

    def test_only_current_released_words_are_prefetched(self):
        selected = [f'word{index}' for index in range(8)]
        info = SimpleNamespace(fast_mode=True, course_id='BOOK', word_list=selected,
                               get_book_words_data=[{'word': word, 'list_id': 'U'} for word in selected + ['outside']])
        before = deepcopy(info.__dict__)
        read = Mock(return_value={'means': [{'mean': ['v 放弃']}]})
        with patch.object(headers, 'rqs_session', SimpleNamespace(headers={})), \
             patch.object(headers.requests, 'Session', side_effect=lambda: OwnedSession(lambda _: None)), \
             patch.object(api, '_fetch_word_info', read):
            pool = api.begin_word_prefetch(info)
            try:
                self.drain(pool)
                self.assertEqual({call.args[2] for call in read.call_args_list}, set(selected))
                self.assertEqual(info.word_list, before['word_list'])
                self.assertEqual(info.get_book_words_data, before['get_book_words_data'])
            finally:
                pool.close()

    def test_normal_mode_never_starts_background_requests(self):
        with patch.object(headers.requests, 'Session', side_effect=AssertionError('Prefetch disabled')):
            self.assertIsNone(api.begin_word_prefetch(SimpleNamespace(fast_mode=False)))

    def test_invalid_empty_dictionary_is_not_cached(self):
        pool = self.pool([('BOOK', 'U', 'word')], lambda *args: {'means': []})
        self.drain(pool)
        self.assertIsNone(pool.wait(('BOOK', 'U', 'word')))


if __name__ == '__main__':
    unittest.main()
