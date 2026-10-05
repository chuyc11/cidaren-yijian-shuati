"""Regressions derived from the W6 live timeouts and total elapsed time."""
import logging
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from requests.exceptions import ReadTimeout
import main as app
from publicInfo.publicInfo import PublicInfo


class LiveRecoveryTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(Path(__file__).resolve().parents[1]))
        self.task = {'task_name': 'Timeout recovery', 'task_type': 2}
        self.worker = app.TaskWorker([self.task], public_info=self.info, logger=Mock())
        self.finished, self.errors = [], []
        self.worker.task_finished.connect(self.finished.append)
        self.worker.task_error.connect(self.errors.append)

    def test_three_separated_timeouts_do_not_exhaust_consecutive_failure_limit(self):
        positions = iter([20, 80, 140, None])
        def complete(task):
            position = next(positions)
            if position is None:
                self.info.exam = 'complete'
                return
            self.info.exam = {'topic_done_num': position, 'topic_total': 160}
            self.worker.emit_progress()
            raise ReadTimeout('temporary network timeout')
        with patch.object(self.worker, 'complete_test', side_effect=complete) as run, \
             patch.object(app, 'get_class_task_info', return_value={'progress': 100, 'score': 100}), \
             patch.object(app.time, 'sleep'):
            self.worker.run()
        self.assertEqual(run.call_count, 4)
        self.assertEqual(len(self.finished), 1)
        self.assertEqual(self.errors, [])

    def test_no_progress_still_stops_after_three_consecutive_failures(self):
        def complete(task):
            self.info.exam = {'topic_done_num': 20, 'topic_total': 160}
            self.worker.emit_progress()
            raise ReadTimeout('temporary network timeout')
        with patch.object(self.worker, 'complete_test', side_effect=complete) as run, patch.object(app.time, 'sleep'):
            self.worker.run()
        self.assertEqual(run.call_count, 3)
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(self.finished, [])

    def test_total_time_includes_successful_work_and_retry_wait(self):
        clock = [100.0]
        attempts = [0]
        def complete(task):
            attempts[0] += 1
            clock[0] += 5
            if attempts[0] == 1:
                raise ReadTimeout('temporary network timeout')
            self.info.exam = 'complete'
        def sleep(seconds):
            clock[0] += seconds
        with patch.object(self.worker, 'complete_test', side_effect=complete), \
             patch.object(app, 'get_class_task_info', return_value={'progress': 100, 'score': 100}), \
             patch.object(app.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(app.time, 'time', side_effect=lambda: clock[0]), patch.object(app.time, 'sleep', side_effect=sleep):
            self.worker.run()
        self.assertEqual(len(self.finished), 1)
        self.assertIn('12.00 秒', self.finished[0])


if __name__ == '__main__':
    unittest.main()
