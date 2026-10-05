"""Progress regressions from observed live 1/160 before answering and final stale counts."""
import logging
from pathlib import Path
import unittest
from unittest.mock import Mock
import main as app
from publicInfo.publicInfo import PublicInfo

ROOT = Path(__file__).resolve().parents[1]


class ProgressTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(ROOT))
        self.worker = app.TaskWorker([], public_info=self.info, logger=Mock())
        self.worker.current_index = 1
        self.worker.current_total = 1
        self.worker.current_task_name = 'Example'
        self.messages = []
        self.worker.task_progress.connect(self.messages.append)

    def test_first_question_shows_zero_completed(self):
        self.info.exam = {'topic_done_num': 1, 'topic_total': 160}
        self.worker.emit_progress()
        self.assertTrue(self.messages[-1].startswith('0/160|0|0|0|'))

    def test_resumed_progress_uses_server_position_not_session_counts(self):
        self.info.exam = {'topic_done_num': 81, 'topic_total': 160}
        self.info.right_count = 4
        self.worker.emit_progress()
        self.assertTrue(self.messages[-1].startswith('80/160|4|0|0|'))

    def test_final_question_updates_all_final_counts(self):
        self.info.exam = {'topic_done_num': 160, 'topic_total': 160}
        self.info.right_count = 157
        self.info.wrong_count = 2
        self.worker.emit_progress()
        self.info.exam = 'complete'
        self.info.right_count = 158
        self.worker._completion_confirmed = True
        self.worker.emit_progress()
        self.assertTrue(self.messages[-1].startswith('160/160|158|2|0|'))

    def test_final_skip_is_included_in_completion_statistics(self):
        self.info.exam = {'topic_done_num': 2, 'topic_total': 2}
        self.info.right_count = 1
        self.worker.emit_progress()
        self.info.skip_count = 1
        self.info.exam = 'complete'
        self.worker._completion_confirmed = True
        self.worker.emit_progress()
        self.assertTrue(self.messages[-1].startswith('2/2|1|0|1|'))

    def test_invalid_large_progress_is_clamped(self):
        self.info.exam = {'topic_done_num': 999, 'topic_total': 160}
        self.worker.emit_progress()
        self.assertTrue(self.messages[-1].startswith('160/160|'))

    def test_complete_state_waits_for_server_confirmation(self):
        self.info.exam = {'topic_done_num': 160, 'topic_total': 160}
        self.worker.emit_progress()
        count = len(self.messages)
        self.info.exam = 'complete'
        self.worker.emit_progress()
        self.assertEqual(len(self.messages), count)

    def test_reading_and_grading_phases_are_distinct(self):
        self.info.exam = {'topic_mode': 0, 'topic_done_num': 11, 'topic_total': 458}
        self.worker.emit_progress()
        self.assertIn('阅读卡片（不计判分）', self.messages[-1])
        self.info.exam['topic_mode'] = 22
        self.worker.emit_progress()
        self.assertTrue(self.messages[-1].endswith('|听词选义'))


if __name__ == '__main__':
    unittest.main()
