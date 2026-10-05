"""W9: Info is complete before PageTask updates; never regrade or erase the report."""
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import main as app
from publicInfo.publicInfo import PublicInfo
from util.task_checkpoint import TaskCheckpoint
from util.task_completion import RecentCompletions
from util.task_report import TaskReport


class CompletionSyncTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.task = {'release_id': 1, 'course_id': 'A', 'task_type': 2, 'task_name': 'W9', 'progress': 99}

    def test_stale_list_is_overlaid_without_mutating_input(self):
        cache = RecentCompletions()
        snapshot = dict(self.task, progress=100, score=100)
        cache.remember(snapshot)
        snapshot['score'] = 0
        original = [dict(self.task, score=99.3)]
        refreshed = cache.apply(original)
        self.assertEqual((refreshed[0]['progress'], refreshed[0]['score']), (100, 100))
        self.assertEqual(original[0]['progress'], 99)

    def test_other_course_and_learning_task_are_not_overlaid(self):
        cache = RecentCompletions()
        cache.remember(dict(self.task, progress=100, score=100))
        tasks = [dict(self.task, course_id='B'), dict(self.task, task_type=1)]
        self.assertEqual(cache.apply(tasks), tasks)

    def test_overlay_expires_and_is_removed_when_list_catches_up(self):
        clock = [0]
        cache = RecentCompletions(ttl=10, clock=lambda: clock[0])
        cache.remember(dict(self.task, progress=100, score=100))
        cache.apply([dict(self.task, progress=100)])
        self.assertFalse(cache.confirmed)
        cache.remember(dict(self.task, progress=100, score=100))
        clock[0] = 10
        self.assertEqual(cache.apply([self.task]), [self.task])

    def test_completed_preflight_never_answers_or_overwrites_report(self):
        with tempfile.TemporaryDirectory() as root:
            info = PublicInfo(str(Path(__file__).resolve().parents[1]))
            checkpoint = TaskCheckpoint(root, 'account-A')
            report = TaskReport(root, checkpoint.account, self.task)
            report.record({'topic_done_num': 1, 'topic_mode': 15}, 0, {'answer_result': 1})
            report.finish(100, 10, info)
            before = report.path.read_bytes()
            worker = app.TaskWorker([self.task], public_info=info, logger=Mock(), checkpoint=checkpoint)
            notices, finished, snapshots = [], [], []
            worker.task_notice.connect(notices.append)
            worker.task_finished.connect(finished.append)
            worker.task_completed.connect(snapshots.append)
            with patch.object(app, 'get_class_task_info', return_value={'progress': 100, 'score': 100}), \
                 patch.object(worker, 'class_task_answer', side_effect=AssertionError('Must not answer')), \
                 patch.object(app, 'get_book_all_words', side_effect=AssertionError('Must not load words')):
                worker.run()
                worker.flush_report()
            self.assertEqual(report.path.read_bytes(), before)
            self.assertEqual(len(finished), 1)
            self.assertTrue(any('已完成' in notice for notice in notices))
            self.assertEqual(snapshots[0]['release_id'], 1)
            self.assertEqual(snapshots[0]['progress'], 100)

    def test_batch_completion_snapshots_retain_each_task_identity(self):
        tasks = [self.task, dict(self.task, release_id=2, task_name='W10')]
        worker = app.TaskWorker(tasks, batch_mode=True, public_info=PublicInfo(str(Path(__file__).parents[1])), logger=Mock())
        snapshots = []
        worker.task_completed.connect(snapshots.append)
        def complete(task):
            worker.public_info.exam = 'complete'
        with patch.object(worker, 'complete_test', side_effect=complete), \
             patch.object(app, 'get_class_task_info', return_value={'progress': 100, 'score': 100}):
            worker.run()
        self.assertEqual([task['release_id'] for task in snapshots], [1, 2])


if __name__ == '__main__':
    unittest.main()
