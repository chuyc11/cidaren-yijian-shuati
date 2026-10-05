"""Batch-mode terminal errors must flush partial grades before the next task."""
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import main as app
import api.main_api as api
from publicInfo.publicInfo import PublicInfo
from util.task_checkpoint import TaskCheckpoint
from test_class_tasks import TestServer


class PartialBatchReportTests(unittest.TestCase):
    def test_terminal_error_keeps_last_grade_of_failed_task(self):
        logging.disable(logging.CRITICAL)
        for error in (api.SecurityVerifyError('verification'), api.TaskUnavailableError('deadline')):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as root:
                info = PublicInfo(str(Path(app.__file__).parent))
                task = {'release_id': 200, 'course_id': 'BOOK', 'task_type': 2, 'task_name': 'First'}
                tasks = [task, dict(task, release_id=201, task_name='Second')]
                worker = app.TaskWorker(tasks, batch_mode=True, public_info=info, logger=Mock(), checkpoint=TaskCheckpoint(root, 'A'))
                paths = []
                def complete(current):
                    worker._ensure_report(current)
                    paths.append(info._task_report.path)
                    info._task_report.record(TestServer().question(), 0, {'answer_result': 1, 'answer_corrects': [0]})
                    info.right_count += 1
                    if current['release_id'] == 200:
                        raise error
                    info.exam = 'complete'
                with patch.object(worker, 'complete_test', side_effect=complete), \
                     patch.object(app, 'get_class_task_info', return_value={'progress': 100, 'score': 100}):
                    worker.run()
                self.assertTrue(paths[0].exists())
                first = json.loads(paths[0].read_text(encoding='utf-8'))
                self.assertFalse(first['complete'])
                self.assertEqual(len(first['records']), 1)
                self.assertTrue(json.loads(paths[1].read_text(encoding='utf-8'))['complete'])


if __name__ == '__main__':
    unittest.main()
