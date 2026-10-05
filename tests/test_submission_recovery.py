"""A confirmed grade is not sent again to recover its subsequent save."""
from contextlib import ExitStack
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from requests.exceptions import ReadTimeout
import main as app
import api.request_header as headers
import answer_questions.answer_questions as solver
from publicInfo.publicInfo import PublicInfo
from util.task_checkpoint import TaskCheckpoint
from test_class_tasks import TestServer, response


class SubmissionRecoveryTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(Path(app.__file__).parent))
        self.info._self_learn_pool = self.info._self_learn_lib = False
        self.task = {'release_id': 200, 'course_id': 'BOOK', 'task_type': 2, 'task_name': 'Save recovery'}

    def test_save_timeout_with_same_current_question_does_not_regrade(self):
        class Server(TestServer):
            saves = 0
            def post(current, url, data=None, **kwargs):
                if url.endswith('SubmitAnswerAndSave'):
                    current.saves += 1
                    if current.saves == 1:
                        raise ReadTimeout('save did not persist')
                return super().post(url, data=data, **kwargs)
        server = Server()
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            for name in ('class_task_request', 'rqs_session', 'rqs2_session', 'rqs3_session'):
                stack.enter_context(patch.object(headers, name, server))
            stack.enter_context(patch.object(app.time, 'sleep'))
            stack.enter_context(patch.object(headers.requests.Session, 'request', side_effect=AssertionError('HTTP blocked')))
            solver = stack.enter_context(patch.object(app, 'answer', return_value=0))
            worker = app.TaskWorker([self.task], public_info=self.info, logger=Mock(), checkpoint=TaskCheckpoint(root, 'A'))
            errors, finished = [], []
            worker.task_error.connect(errors.append)
            worker.task_finished.connect(finished.append)
            worker.run()
            self.assertEqual(errors, [])
            self.assertEqual(len(finished), 1)
            self.assertEqual(len(self.info._task_report.data['records']), 1)
        self.assertEqual(len(server.verifications), 1)
        self.assertEqual(self.info.right_count, 1)
        self.assertEqual(solver.call_count, 1)

    def test_refreshed_topic_code_keeps_same_pending_save(self):
        self.info.course_id, self.info.release_id, self.info.task_id = 'BOOK', 200, 900
        self.info.exam = TestServer().question()
        def verify(info, answer):
            info.topic_code = 'verified-code'
        with patch.object(solver, 'submit_result', side_effect=verify) as verify_mock, \
             patch.object(solver, 'next_exam', side_effect=[ReadTimeout('save'), None]), patch.object(app.time, 'sleep'):
            with self.assertRaises(ReadTimeout):
                app.submit(self.info, 0)
            self.info.exam['topic_code'] = 'fresh-start-code'
            self.assertTrue(app.resume_submission(self.info))
        self.assertEqual(verify_mock.call_count, 1)
        self.assertEqual(self.info.topic_code, 'verified-code')

    def test_partial_pair_submission_resumes_only_remaining_pairs(self):
        self.info.exam = dict(TestServer().question(), topic_mode=31)
        calls = []
        attempts = [0]
        def verify(info, answer):
            attempts[0] += 1
            calls.append(answer)
            if attempts[0] == 2:
                raise ReadTimeout('second pair response unavailable')
            info.topic_code = 'verified-' + str(answer)
        with patch.object(solver, 'submit_result', side_effect=verify), patch.object(solver, 'next_exam'), patch.object(app.time, 'sleep'):
            with self.assertRaises(ReadTimeout):
                app.submit(self.info, {0: '00', 1: '11', 2: '22'})
            self.assertTrue(app.resume_submission(self.info))
        self.assertEqual(calls, ['00', '11', '11', '22'])

    def test_new_task_cannot_reuse_old_pending_submission(self):
        self.info.exam = TestServer().question()
        with patch.object(solver, 'submit_result', side_effect=lambda info, answer: setattr(info, 'topic_code', 'verified')), \
             patch.object(solver, 'next_exam', side_effect=ReadTimeout('save')), patch.object(app.time, 'sleep'):
            with self.assertRaises(ReadTimeout):
                app.submit(self.info, 0)
        self.info.release_id = 201
        self.assertFalse(app.resume_submission(self.info))

    def test_process_restart_keeps_one_grade_record_and_restores_count(self):
        class Server(TestServer):
            saves = 0
            def post(current, url, data=None, **kwargs):
                if url.endswith('SubmitAnswerAndSave'):
                    current.saves += 1
                    if current.saves == 1:
                        raise ReadTimeout('save did not persist')
                return super().post(url, data=data, **kwargs)
        server = Server()
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            checkpoint = TaskCheckpoint(root, 'A')
            for name in ('class_task_request', 'rqs_session', 'rqs2_session', 'rqs3_session'):
                stack.enter_context(patch.object(headers, name, server))
            stack.enter_context(patch.object(app.time, 'sleep'))
            stack.enter_context(patch.object(app, 'answer', return_value=0))
            first = app.TaskWorker([self.task], public_info=self.info, logger=Mock(), checkpoint=checkpoint)
            with self.assertRaises(ReadTimeout):
                first.complete_test(self.task)
            first.flush_report()
            restored = PublicInfo(str(Path(app.__file__).parent))
            restored._self_learn_pool = restored._self_learn_lib = False
            second = app.TaskWorker([self.task], public_info=restored, logger=Mock(), checkpoint=checkpoint)
            second.run()
            self.assertEqual(restored.right_count, 1)
            self.assertEqual(len(restored._task_report.data['records']), 1)
            self.assertTrue(restored._task_report.data['complete'])


class ClassLearningSubmissionRecoveryTests(SubmissionRecoveryTests):
    def setUp(self):
        super().setUp()
        self.task['task_type'] = 1


if __name__ == '__main__':
    unittest.main()
