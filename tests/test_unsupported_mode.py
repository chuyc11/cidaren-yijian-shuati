"""Unsupported questions must not be answered using a fixed option number."""
import logging
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import main as app
from publicInfo.publicInfo import PublicInfo


class UnsupportedModeTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(Path(app.__file__).parent))
        self.info.word_list = ['abandon']
        self.info.exam = {'topic_mode': 13, 'topic_code': 'current', 'topic_done_num': 1, 'topic_total': 1,
                          'stem': {'content': 'abandon'}, 'options': [{'content': 'A'}, {'content': 'B'}]}

    def test_mode_13_returns_uncertain_instead_of_fixed_option_3(self):
        self.assertIsNone(app.answer(self.info, 13))

    def test_unknown_mode_does_not_default_to_first_option(self):
        self.assertIsNone(app.answer(self.info, 999))
        self.assertEqual(self.info._answer_issue, 'unsupported_mode')

    def test_unknown_mode_without_reliable_fallback_never_submits_or_skips_test(self):
        self.info.exam['topic_mode'] = 999
        worker = app.TaskWorker([{'task_type': 2}], public_info=self.info, logger=Mock())
        with patch.object(worker, 'start_answer'), patch.object(app, 'ai_answer', return_value=None), \
             patch.object(app, 'submit') as submit, patch.object(app, 'skip_exam') as skip:
            with self.assertRaises(app.UnresolvedAnswerError):
                worker.class_task_answer()
        submit.assert_not_called()
        skip.assert_not_called()

    def test_class_test_preserves_question_when_mode_13_has_no_solver(self):
        worker = app.TaskWorker([{'task_type': 2}], public_info=self.info, logger=Mock())
        with patch.object(worker, 'start_answer'), patch.object(app, 'ai_answer', return_value=None), \
             patch.object(app, 'submit', side_effect=AssertionError('No arbitrary answer may be sent')) as submit, \
             patch.object(app, 'skip_exam') as skip:
            with self.assertRaises(app.UnresolvedAnswerError):
                worker.class_task_answer()
        submit.assert_not_called()
        skip.assert_not_called()
        self.assertEqual(self.info.exam['topic_code'], 'current')


if __name__ == '__main__':
    unittest.main()
