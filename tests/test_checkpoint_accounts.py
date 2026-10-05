"""Each account retains its own recovery state, with safe legacy migration."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from util.task_checkpoint import TaskCheckpoint


class CheckpointAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.info = SimpleNamespace(right_count=1, wrong_count=0, skip_count=0)
        self.task = {'release_id': 1, 'course_id': 'BOOK', 'task_id': 900, 'task_type': 2, 'task_name': 'A'}

    def test_saving_second_account_preserves_first_account(self):
        a, b = TaskCheckpoint(self.temp.name, 'A'), TaskCheckpoint(self.temp.name, 'B')
        a.save([self.task], self.info, False)
        b.save([dict(self.task, release_id=2)], self.info, False)
        self.assertNotEqual(a.path, b.path)
        self.assertEqual(a.load()['pending'][0]['release_id'], 1)
        self.assertEqual(b.load()['pending'][0]['release_id'], 2)

    def test_matching_legacy_state_is_read_without_deleting_it(self):
        legacy = Path(self.temp.name) / 'config' / 'task_resume.json'
        legacy.parent.mkdir()
        state = {'version': 1, 'account': 'A', 'pending': [self.task], 'counts': vars(self.info), 'batch_mode': False}
        legacy.write_text(json.dumps(state), encoding='utf-8')
        checkpoint = TaskCheckpoint(self.temp.name, 'A')
        self.assertEqual(checkpoint.load()['pending'], [self.task])
        checkpoint.save([self.task], self.info, False)
        self.assertNotEqual(checkpoint.path, legacy)
        self.assertTrue(checkpoint.path.exists() and legacy.exists())

    def test_other_accounts_legacy_file_is_ignored(self):
        legacy = Path(self.temp.name) / 'config' / 'task_resume.json'
        legacy.parent.mkdir()
        legacy.write_text(json.dumps({'version': 1, 'account': 'A', 'pending': [self.task], 'counts': vars(self.info)}), encoding='utf-8')
        self.assertIsNone(TaskCheckpoint(self.temp.name, 'B').load())

    def test_path_traversal_account_is_rejected(self):
        with self.assertRaises(ValueError):
            TaskCheckpoint(self.temp.name, '../other')


if __name__ == '__main__':
    unittest.main()
