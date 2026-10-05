"""Retry read-only task listing after truncated responses, without replaying answers."""
import logging
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from requests.exceptions import ChunkedEncodingError, ReadTimeout
import api.main_api as api
import api.request_header as headers
from publicInfo.publicInfo import PublicInfo
from test_class_tasks import response


class TaskListRetryTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(Path(__file__).resolve().parents[1]))
        self.info.class_task = []
        PublicInfo.task_type, PublicInfo.task_type_int = 'ClassTask', 2

    def test_truncated_readonly_response_is_retried_once_without_duplicate_page(self):
        session = Mock(post=Mock(side_effect=[ChunkedEncodingError('Response ended prematurely'),
                                             response({'records': [], 'total': 0}, encoded=False)]))
        with patch.object(headers, 'class_task_request', session), patch.object(api.time, 'sleep'):
            api.get_class_task(self.info, 1)
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(len(self.info.class_task), 1)
        self.assertEqual(self.info.task_total_count, 0)

    def test_persistent_read_failure_stops_after_three_attempts(self):
        session = Mock(post=Mock(side_effect=ReadTimeout('temporary')))
        with patch.object(headers, 'class_task_request', session), patch.object(api.time, 'sleep'):
            with self.assertRaises(ReadTimeout):
                api.get_class_task(self.info, 1)
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual(self.info.class_task, [])

    def test_security_verification_does_not_retry_listing(self):
        session = Mock(post=Mock(return_value=response(code=11003, msg='需安全验证')))
        with patch.object(headers, 'class_task_request', session):
            with self.assertRaises(api.SecurityVerifyError):
                api.get_class_task(self.info, 1)
        self.assertEqual(session.post.call_count, 1)

    def test_answer_verification_is_not_replayed_by_read_query_retry(self):
        session = Mock(post=Mock(side_effect=ReadTimeout('temporary')))
        self.info.topic_code = 'current-question'
        with patch.object(headers, 'rqs2_session', session):
            with self.assertRaises(ReadTimeout):
                api.submit_result(self.info, 0)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(self.info.right_count, 0)


if __name__ == '__main__':
    unittest.main()
