"""Teacher-released learning tasks must use ClassTask IDs and completion details."""
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import main as app
import api.request_header as headers
from publicInfo.publicInfo import PublicInfo
from util.task_checkpoint import TaskCheckpoint
from test_class_tasks import TestServer, response
from api.main_api import WordSelectionRequiredError


class LearningServer(TestServer):
    def details(self):
        data = super().details()
        data.update(task_type=1, task_name='Class learning')
        return data


class ClassLearningTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(Path(__file__).resolve().parents[1]))
        self.info._self_learn_pool = self.info._self_learn_lib = False
        self.server = LearningServer(selection=True)
        self.task = {'task_name': 'Class learning', 'task_type': 1, 'task_id': -1,
                     'release_id': 200, 'course_id': 'BOOK', 'progress': 0}
        for session in ('class_task_request', 'rqs_session', 'rqs2_session', 'rqs3_session'):
            self.enter(patch.object(headers, session, self.server))
        self.enter(patch.object(app.time, 'sleep'))
        self.enter(patch.object(headers.requests.Session, 'request',
                                side_effect=AssertionError('External HTTP disabled')))
        self.units = self.enter(patch.object(app, 'get_all_unit',
                                            side_effect=AssertionError('Must use ClassTask/Info')))
        self.study_info = self.enter(patch.object(app, 'get_unit_words',
                                                 side_effect=AssertionError('Must not use StudyTask/Info')))
        self.book = self.enter(patch.object(app, 'get_book_all_words',
                                           side_effect=AssertionError('Released words already have units')))
        self.ai = self.enter(patch.object(app, 'ai_answer', return_value=None))

    def enter(self, context):
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def worker(self, checkpoint=None):
        return app.TaskWorker([self.task], public_info=self.info, logger=Mock(), checkpoint=checkpoint)

    def test_learning_initialization_replaces_unallocated_task_id(self):
        self.worker().complete_test(self.task)
        self.assertEqual(self.server.starts[0]['task_id'], 900)
        self.assertEqual(self.server.starts[0]['release_id'], 200)
        self.assertEqual(self.info.exam, 'complete')
        self.units.assert_not_called()
        self.study_info.assert_not_called()

    def test_learning_selection_uses_only_released_word_map(self):
        self.worker().complete_test(self.task)
        self.assertEqual(self.server.word_maps, [{'BOOK:U4': ['abandon']}])
        self.book.assert_not_called()
        self.assertEqual(len(self.server.verifications), 1)

    def test_zero_progress_cannot_be_reported_as_completed(self):
        self.server.persisted = False
        worker = self.worker()
        finished, errors = [], []
        worker.task_finished.connect(finished.append)
        worker.task_error.connect(errors.append)
        worker.run()
        self.assertEqual(finished, [])
        self.assertEqual(len(errors), 1)
        self.assertIn('0%', errors[0])

    def test_success_requires_detail_progress_and_emits_learning_snapshot(self):
        worker = self.worker()
        finished, snapshots, errors = [], [], []
        worker.task_finished.connect(finished.append)
        worker.task_completed.connect(snapshots.append)
        worker.task_error.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(finished), 1)
        self.assertEqual(snapshots, [{'release_id': 200, 'course_id': 'BOOK', 'task_name': 'Class learning',
                                     'task_type': 1, 'progress': 100, 'score': 0.0}])
        self.assertGreaterEqual(self.server.details_calls, 2)

    def test_already_completed_learning_never_regrades_or_erases_report(self):
        self.server.finished = True
        with tempfile.TemporaryDirectory() as root:
            from util.task_report import TaskReport
            checkpoint = TaskCheckpoint(root, 'account-A')
            report = TaskReport(root, checkpoint.account, self.task)
            report.record({'topic_done_num': 1, 'topic_mode': 15}, 0, {'answer_result': 1})
            report.finish(99, 10, self.info)
            before = report.path.read_bytes()
            worker = self.worker(checkpoint)
            worker.run()
            worker.flush_report()
            self.assertEqual(report.path.read_bytes(), before)
            self.assertEqual(self.server.starts, [])
            self.assertEqual(self.server.verifications, [])

    def selection_after_final_save(self):
        original = self.server.post
        def post(url, **kwargs):
            result = original(url, **kwargs)
            if url.endswith('SubmitAnswerAndSave') and self.server.finished:
                return response(code=20001, msg='需要选词！')
            return result
        self.server.post = post

    def test_final_save_selection_message_confirms_details_without_restarting(self):
        self.selection_after_final_save()
        worker = self.worker()
        notices, finished, errors = [], [], []
        worker.task_notice.connect(notices.append)
        worker.task_finished.connect(finished.append)
        worker.task_error.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(finished), 1)
        self.assertEqual(notices, [])
        self.assertEqual(len(self.server.verifications), 1)
        self.assertEqual(self.server.saved_codes, ['verified'])
        self.assertIsNone(self.info._pending_submission)

    def test_selection_message_with_zero_progress_is_not_completion(self):
        self.selection_after_final_save()
        self.server.persisted = False
        with self.assertRaises(WordSelectionRequiredError):
            self.worker().complete_test(self.task)
        self.assertNotEqual(self.info.exam, 'complete')

    def test_final_read_card_selection_message_uses_same_completion_gate(self):
        self.selection_after_final_save()
        self.server.final_card = True
        worker = self.worker()
        notices, finished = [], []
        worker.task_notice.connect(notices.append)
        worker.task_finished.connect(finished.append)
        worker.run()
        self.assertEqual(len(finished), 1)
        self.assertEqual(notices, [])
        self.assertEqual(self.server.saved_codes, ['verified', 'card'])


if __name__ == '__main__':
    unittest.main()
