"""Temporary failures must not permanently skip a graded class-test question."""
import logging
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from requests.exceptions import ReadTimeout, ChunkedEncodingError
import main as app
import api.request_header as headers
from publicInfo.publicInfo import PublicInfo
from test_class_tasks import TestServer


class AnswerRecoveryTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(Path(app.__file__).parent))
        self.info._self_learn_pool = self.info._self_learn_lib = False
        self.info.word_list = ['abandon']
        self.info.exam = TestServer().question()
        self.task = {'task_type': 2, 'task_name': 'Recoverable test', 'release_id': 200, 'course_id': 'BOOK'}
        self.worker = app.TaskWorker([self.task], public_info=self.info, logger=Mock())

    def test_dictionary_network_errors_propagate_without_ai_or_skip(self):
        for error in (ReadTimeout('dictionary timeout'), ChunkedEncodingError('truncated dictionary')):
            with self.subTest(error=type(error).__name__), patch.object(self.worker, 'start_answer'), \
                 patch.object(app, 'answer', side_effect=error), patch.object(app, 'ai_answer', return_value=None) as ai, \
                 patch.object(app, 'skip_exam', side_effect=AssertionError('Skip must not be called')) as skip:
                with self.assertRaises(type(error)):
                    self.worker.class_task_answer()
                ai.assert_not_called()
                skip.assert_not_called()

    def test_no_reliable_answer_in_test_stops_without_skipping(self):
        with patch.object(self.worker, 'start_answer'), patch.object(app, 'answer', return_value=None), \
             patch.object(app, 'ai_answer', return_value=None), patch.object(app, 'skip_exam') as skip:
            with self.assertRaises(app.UnresolvedAnswerError):
                self.worker.class_task_answer()
            skip.assert_not_called()
        self.assertEqual(self.info.skip_count, 0)

    def test_dictionary_timeout_recovers_then_grades_only_once(self):
        server = TestServer()
        finished, errors = [], []
        self.worker.task_finished.connect(finished.append)
        self.worker.task_error.connect(errors.append)
        with patch.object(headers, 'class_task_request', server), patch.object(headers, 'rqs_session', server), \
             patch.object(headers, 'rqs2_session', server), patch.object(headers, 'rqs3_session', server), \
             patch.object(app, 'answer', side_effect=[ReadTimeout('dictionary timeout'), 0]), \
             patch.object(app, 'ai_answer', return_value=None) as ai, \
             patch.object(app, 'skip_exam', side_effect=AssertionError('Skip must not be called')) as skip, \
             patch.object(app.time, 'sleep'), patch.object(headers.requests.Session, 'request', side_effect=AssertionError('HTTP blocked')):
            self.worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(finished), 1)
        self.assertEqual(len(server.verifications), 1)
        self.assertEqual(self.info.right_count, 1)
        ai.assert_not_called()
        skip.assert_not_called()


if __name__ == '__main__':
    unittest.main()
