"""The observed W8 magnify question has two valid senses but no sense context."""
import logging
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import main as app
import answer_questions.answer_questions as solving
import api.request_header as headers
from publicInfo.publicInfo import PublicInfo
from test_class_tasks import response


class AmbiguousMeanTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(Path(app.__file__).parent))
        self.info.word_list = ['magnify']
        self.info.exam = {'topic_mode': 22, 'topic_done_num': 427, 'topic_total': 458, 'topic_code': 'current',
                          'stem': {'content': 'magnify'}, 'options': [
                              {'content': 'vt. 夸张；夸大', 'answer_tag': 2}, {'content': 'vt. 放大', 'answer_tag': 3}]}
        self.dictionary = {'means': [{'mean': ['vt.', '放大']}, {'mean': ['vt.', '夸张；夸大']}]}

    def query(self, info, word):
        info.word_query_result = self.dictionary

    def test_ambiguous_listening_question_defers_and_marks_missing_sense_context(self):
        with patch.object(solving, 'query_word', side_effect=self.query):
            self.assertIsNone(app.answer(self.info, 22))
        self.assertEqual(self.info._answer_issue, 'ambiguous_mean')

    def test_unique_followup_clears_previous_ambiguity(self):
        self.info._answer_issue = 'ambiguous_mean'
        self.info.exam['options'] = [{'content': 'vt. 放大', 'answer_tag': 0}]
        with patch.object(solving, 'query_word', side_effect=self.query):
            self.assertEqual(app.answer(self.info, 22), 0)
        self.assertIsNone(self.info._answer_issue)

    def test_learning_skips_ambiguity_once_without_ai_or_grading(self):
        worker = app.TaskWorker([{'task_type': 1}], public_info=self.info, logger=Mock())
        self.info._self_learn_pool = self.info._self_learn_lib = False
        PublicInfo.task_type = 'ClassTask'
        session = Mock(post=Mock(return_value=response(code=20004, msg='任务已完成！')))
        with patch.object(worker, 'start_answer'), patch.object(solving, 'query_word', side_effect=self.query), \
             patch.object(headers, 'rqs2_session', session), patch.object(app, 'ai_answer') as ai:
            worker.class_task_answer()
        ai.assert_not_called()
        self.assertTrue(session.post.call_args.args[0].endswith('/SkipAnswer'))
        self.assertEqual(self.info.skip_count, 1)
        self.assertEqual(self.info.right_count + self.info.wrong_count, 0)

    def test_graded_test_retains_question_without_guessing_or_skipping(self):
        worker = app.TaskWorker([{'task_type': 2}], public_info=self.info, logger=Mock())
        with patch.object(worker, 'start_answer'), patch.object(solving, 'query_word', side_effect=self.query), \
             patch.object(app, 'ai_answer') as ai, patch.object(app, 'skip_exam') as skip:
            with self.assertRaises(app.UnresolvedAnswerError):
                worker.class_task_answer()
        ai.assert_not_called()
        skip.assert_not_called()
        self.assertEqual(self.info.exam['topic_done_num'], 427)

    def test_server_returning_same_ambiguous_question_does_not_loop_forever(self):
        worker = app.TaskWorker([{'task_type': 1}], public_info=self.info, logger=Mock())
        PublicInfo.task_type = 'ClassTask'
        session = Mock(post=Mock(return_value=response(self.info.exam)))
        with patch.object(worker, 'start_answer'), patch.object(solving, 'query_word', side_effect=self.query), \
             patch.object(headers, 'rqs2_session', session), patch.object(app, 'ai_answer') as ai:
            with self.assertRaises(app.UnresolvedAnswerError):
                worker.class_task_answer()
        ai.assert_not_called()
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(self.info.skip_count, 1)


if __name__ == '__main__':
    unittest.main()
