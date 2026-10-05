"""Reports are based on server grading, survive recovery, and exclude capabilities."""
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import api.main_api as api
import api.request_header as headers
from publicInfo.publicInfo import PublicInfo
from util.task_report import TaskReport, format_report, reports_for_account
from test_class_tasks import response


class ReportTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.task = {'release_id': 12, 'course_id': 'BOOK', 'task_name': 'Example test', 'task_type': 2}
        self.exam = {'topic_done_num': 1, 'topic_mode': 15, 'topic_code': 'secret-question-code',
                     'stem': {'content': 'abandon', 'remark': None},
                     'options': [{'content': 'v. 放弃', 'answer_tag': 0, 'check_code': 'secret-option-code'},
                                 {'content': 'v. 接受', 'answer_tag': 1}]}
        self.report = TaskReport(self.temp.name, 'account-A', self.task)

    def test_question_and_standard_answer_are_recorded_without_capabilities(self):
        exam = dict(self.exam, token='private-token', api_key='private-key')
        self.report.record(exam, 1, {'answer_result': 2, 'answer_corrects': [0], 'topic_code': 'secret-result-code'}, 'local')
        self.report.save()
        text = self.report.path.read_text(encoding='utf-8')
        for value in ('secret-question-code', 'secret-option-code', 'secret-result-code', 'private-token', 'private-key', 'topic_code', 'api_key', 'check_code'):
            self.assertNotIn(value, text)
        data = json.loads(text)
        self.assertEqual(data['records'][0]['answer'], 1)
        self.assertEqual(data['records'][0]['corrects'], [0])

    def test_formatter_resolves_choice_tags_and_keeps_plain_text(self):
        exam = dict(self.exam, stem={'content': '<word & sentence>', 'remark': '示例'})
        self.report.record(exam, 1, {'answer_result': 2, 'answer_corrects': [0]}, 'ai')
        formatted = format_report(self.report.data)
        self.assertIn('<word & sentence>', formatted)
        self.assertIn('提交答案：v. 接受', formatted)
        self.assertIn('服务器标准答案：v. 放弃', formatted)
        self.assertIn('AI 兜底判分记录：1', formatted)
        self.assertIn('尚未确认完成', formatted)

    def test_account_scope_does_not_return_another_users_report(self):
        self.report.save()
        self.assertEqual(len(reports_for_account(self.temp.name, 'account-A')), 1)
        self.assertEqual(reports_for_account(self.temp.name, 'account-B'), [])

    def test_path_traversal_namespace_is_rejected(self):
        with self.assertRaises(ValueError):
            TaskReport(self.temp.name, '../../outside', self.task)
        with self.assertRaises(ValueError):
            TaskReport(self.temp.name, 'account-A', dict(self.task, release_id='../outside'))

    def test_resume_preserves_grades_and_accumulates_active_execution_time(self):
        self.report.record(self.exam, 0, {'answer_result': 1, 'answer_corrects': [0]})
        self.report.save(elapsed=5)
        restored = TaskReport(self.temp.name, 'account-A', self.task)
        restored.record(dict(self.exam, topic_done_num=2), 0, {'answer_result': 1, 'answer_corrects': [0]})
        restored.finish(100, 7, Mock(right_count=2, wrong_count=0, skip_count=0))
        data = json.loads(restored.path.read_text(encoding='utf-8'))
        self.assertEqual(len(data['records']), 2)
        self.assertEqual(data['elapsed_seconds'], 12)
        self.assertTrue(data['complete'])
        self.assertEqual(data['score'], 100)
        self.assertFalse(restored.path.with_suffix('.tmp').exists())

    def test_completed_previous_run_is_not_added_to_new_run(self):
        self.report.record(self.exam, 0, {'answer_result': 1, 'answer_corrects': [0]})
        self.report.finish(100, 5, Mock(right_count=1, wrong_count=0, skip_count=0))
        new = TaskReport(self.temp.name, 'account-A', self.task)
        self.assertEqual(new.data['records'], [])
        self.assertEqual(new.previous_elapsed, 0)

    def test_corrupted_previous_report_starts_cleanly(self):
        self.report.path.parent.mkdir(parents=True)
        self.report.path.write_text('{broken', encoding='utf-8')
        new = TaskReport(self.temp.name, 'account-A', self.task)
        self.assertEqual(new.data['records'], [])

    def test_non_grading_payload_does_not_create_a_grade(self):
        self.report.record(self.exam, 0, {'topic_mode': 15})
        self.assertEqual(self.report.data['records'], [])

    def test_zero_server_score_is_displayed(self):
        self.report.finish(0, 5, Mock(right_count=0, wrong_count=1, skip_count=0))
        self.assertIn('服务器得分：0', format_report(self.report.data))

    def test_report_write_error_does_not_repeat_or_lose_server_grade(self):
        info = PublicInfo(str(Path(__file__).resolve().parents[1]))
        info.exam = self.exam
        info.topic_code = 'current'
        info._task_report = Mock(record=Mock(side_effect=OSError('disk unavailable')))
        info._self_learn_lib = False
        PublicInfo.task_type, PublicInfo.task_type_int = 'ClassTask', 2
        session = Mock(post=Mock(return_value=response({'answer_result': 1, 'answer_corrects': [0], 'topic_code': 'verified'})))
        with patch.object(headers, 'rqs2_session', session):
            api.submit_result(info, 0)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(info.right_count, 1)
        self.assertEqual(info.topic_code, 'verified')


if __name__ == '__main__':
    unittest.main()
