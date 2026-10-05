"""An unknown response encoding must not repeat an already accepted submission."""
import logging
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import api.main_api as api
import main as app
from publicInfo.publicInfo import PublicInfo


class PostEncodingTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def test_unknown_encoded_post_response_is_sent_once(self):
        response = Mock()
        response.json.return_value = {'code': 1, 'data': 'encoded-body', 'jv': 'unsupported-version'}
        request = Mock(return_value=response)
        with patch.object(api.time, 'sleep'):
            with self.assertRaises(api.UnsupportedResponseEncodingError):
                api.check_jv_and_retry_post(request, 'https://example.invalid/VerifyAnswer', data='payload')
        self.assertEqual(request.call_count, 1)

    def test_plain_dictionary_response_does_not_need_encoding_version(self):
        response = Mock()
        response.json.return_value = {'code': 1, 'data': {'answer_result': 1}, 'jv': 'unsupported-version'}
        request = Mock(return_value=response)
        self.assertIs(api.check_jv_and_retry_post(request, 'https://example.invalid/VerifyAnswer'), response)
        self.assertEqual(request.call_count, 1)

    def test_completion_and_error_messages_are_returned_without_replay(self):
        for code in (11003, 20004):
            with self.subTest(code=code):
                response = Mock()
                response.json.return_value = {'code': code, 'data': None, 'msg': 'message', 'jv': 'unsupported-version'}
                request = Mock(return_value=response)
                self.assertIs(api.check_jv_and_retry_post(request, 'https://example.invalid/SubmitAnswerAndSave'), response)
                self.assertEqual(request.call_count, 1)

    def test_encoding_failure_stops_worker_without_automatic_retry(self):
        info = PublicInfo(str(Path(app.__file__).parent))
        task = {'task_name': 'Unsupported protocol', 'task_type': 2}
        worker = app.TaskWorker([task], public_info=info, logger=Mock())
        errors = []
        worker.task_error.connect(errors.append)
        with patch.object(worker, 'complete_test', side_effect=api.UnsupportedResponseEncodingError('unknown encoding')) as execute, \
             patch.object(app.time, 'sleep'):
            worker.run()
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(worker.pending_tasks, [task])


if __name__ == '__main__':
    unittest.main()
