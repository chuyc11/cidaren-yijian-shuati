"""A batch report must contain only this task's statistics, including recovery."""
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import main as app
from publicInfo.publicInfo import PublicInfo
from util.task_checkpoint import TaskCheckpoint


class BatchCountTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(Path(app.__file__).parent))
        self.tasks = [{'task_name': 'W10', 'task_type': 2, 'release_id': 1, 'course_id': 'A'},
                      {'task_name': 'W11', 'task_type': 2, 'release_id': 2, 'course_id': 'A'}]

    def test_recovered_first_counts_are_preserved_but_next_task_starts_at_zero(self):
        self.info.right_count, self.info.wrong_count, self.info.skip_count = 7, 2, 1
        worker = app.TaskWorker(self.tasks, batch_mode=True, public_info=self.info, logger=Mock())
        starts, finishes = [], []
        def complete(task):
            starts.append((self.info.right_count, self.info.wrong_count, self.info.skip_count))
            self.info.right_count += 3
            self.info.exam = 'complete'
            self.info._task_report = Mock()
        worker.task_finished.connect(lambda _: finishes.append(self.info.right_count))
        with patch.object(worker, 'complete_test', side_effect=complete), \
             patch.object(app, 'get_class_task_info', return_value={'progress': 100, 'score': 100}):
            worker.run()
        self.assertEqual(starts, [(7, 2, 1), (0, 0, 0)])
        self.assertEqual(finishes, [10, 3])

    def test_second_task_checkpoint_never_contains_first_task_counts(self):
        with tempfile.TemporaryDirectory() as root:
            checkpoint = TaskCheckpoint(root, 'A')
            worker = app.TaskWorker(self.tasks, batch_mode=True, public_info=self.info, logger=Mock(), checkpoint=checkpoint)
            states = []
            def complete(task):
                states.append(checkpoint.load())
                self.info.right_count = 160
                self.info.exam = 'complete'
            with patch.object(worker, 'complete_test', side_effect=complete), \
                 patch.object(app, 'get_class_task_info', return_value={'progress': 100, 'score': 100}):
                worker.run()
            self.assertEqual(states[1]['counts']['right_count'], 0)
            self.assertEqual(states[1]['pending'][0]['release_id'], 2)

    def test_completed_first_task_counts_do_not_move_to_second_on_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            checkpoint = TaskCheckpoint(root, 'A')
            self.info.right_count = 160
            checkpoint.save(self.tasks, self.info, True)
            available = [dict(self.tasks[0], progress=100), dict(self.tasks[1], progress=0)]
            tasks, state = checkpoint.reconcile(available)
            self.assertEqual([task['release_id'] for task in tasks], [2])
            self.assertEqual(state['counts']['right_count'], 0)

    def test_checkpoint_written_between_tasks_labels_counts_with_completed_task(self):
        with tempfile.TemporaryDirectory() as root:
            checkpoint = TaskCheckpoint(root, 'A')
            self.info.right_count = 160
            checkpoint.save([self.tasks[1]], self.info, True, counts_task=self.tasks[0])
            tasks, state = checkpoint.reconcile([dict(self.tasks[1], progress=0)])
            self.assertEqual(len(tasks), 1)
            self.assertEqual(state['counts']['right_count'], 0)


if __name__ == '__main__':
    unittest.main()
