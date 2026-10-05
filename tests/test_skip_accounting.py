"""A skipped question is counted only after a successful server transition."""
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from requests.exceptions import ReadTimeout
import main as app
import api.main_api as api
import api.request_header as headers
from publicInfo.publicInfo import PublicInfo
from util.task_report import TaskReport, format_report
from test_class_tasks import response


class SkipAccountingTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(Path(app.__file__).parent))
        self.info.word_list = ['abandon']
        self.exam = {'topic_mode': 15, 'topic_code': 'current', 'topic_done_num': 1, 'topic_total': 1,
                     'stem': {'content': 'unknown', 'remark': None}, 'options': []}
        self.info.exam = dict(self.exam)
        self.info.topic_code = 'current'
        PublicInfo.task_type, PublicInfo.task_type_int = 'ClassTask', 2

    def test_successful_final_skip_increments_once_and_records_previous_question(self):
        self.info._task_report = Mock()
        session = Mock(post=Mock(return_value=response(code=20004, msg='任务已完成！')))
        with patch.object(headers, 'rqs2_session', session):
            api.skip_exam(self.info)
        self.assertEqual(self.info.skip_count, 1)
        self.assertEqual(self.info.exam, 'complete')
        self.info._task_report.record_skip.assert_called_once_with(self.exam)
        self.assertEqual(session.post.call_count, 1)

    def test_skip_response_timeout_does_not_increment_count(self):
        session = Mock(post=Mock(side_effect=ReadTimeout('temporary')))
        with patch.object(headers, 'rqs2_session', session):
            with self.assertRaises(ReadTimeout):
                api.skip_exam(self.info)
        self.assertEqual(self.info.skip_count, 0)

    def test_worker_skip_timeout_does_not_create_a_phantom_skip(self):
        worker = app.TaskWorker([], public_info=self.info, logger=Mock())
        session = Mock(post=Mock(side_effect=ReadTimeout('temporary')))
        with patch.object(worker, 'start_answer'), patch.object(app, 'answer', return_value=None), \
             patch.object(app, 'ai_answer', return_value=None), patch.object(headers, 'rqs2_session', session):
            with self.assertRaises(ReadTimeout):
                worker.class_task_answer()
        self.assertEqual(self.info.skip_count, 0)

    def test_successful_worker_skip_is_not_double_counted(self):
        worker = app.TaskWorker([], public_info=self.info, logger=Mock())
        session = Mock(post=Mock(return_value=response(code=20004, msg='任务已完成！')))
        with patch.object(worker, 'start_answer'), patch.object(app, 'answer', return_value=None), \
             patch.object(app, 'ai_answer', return_value=None), patch.object(headers, 'rqs2_session', session), \
             patch.object(app.time, 'sleep'):
            worker.class_task_answer()
        self.assertEqual(self.info.skip_count, 1)

    def test_skip_report_separates_skips_from_incorrect_answers(self):
        with tempfile.TemporaryDirectory() as root:
            report = TaskReport(root, 'A', {'release_id': 1, 'task_name': 'Skip test'})
            report.record_skip(self.exam)
            report.finish(0, 1, Mock(right_count=0, wrong_count=0, skip_count=1))
            text = format_report(report.data)
        self.assertIn('跳过 1', text)
        self.assertIn('没有错题记录', text)
        self.assertIsNone(report.data['records'][0]['right'])


if __name__ == '__main__':
    unittest.main()
