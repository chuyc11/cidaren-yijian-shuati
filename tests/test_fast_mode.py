"""Fast mode removes artificial waits without changing the Verify/Save order."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from contextlib import ExitStack
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication
import main as app
import api.main_api as api
import api.request_header as headers
import answer_questions.answer_questions as answering
from publicInfo.publicInfo import PublicInfo
from view.setting import Ui_Form
from test_class_tasks import TestServer, response

ROOT = Path(__file__).resolve().parents[1]


class FastModeTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.info = PublicInfo(str(ROOT))
        self.info._fast_mode = True
        self.info._self_learn_pool = self.info._self_learn_lib = False

    def test_fast_worker_does_not_sleep_between_questions(self):
        worker = app.TaskWorker([], public_info=self.info, logger=Mock())
        self.info.exam = {'topic_mode': 11}
        with patch.object(app.time, 'sleep') as sleep:
            self.assertEqual(worker.pace_question(0), 0)
        sleep.assert_not_called()

    def test_fast_read_card_saves_once_without_waiting(self):
        with patch.object(answering.time, 'sleep') as sleep, patch.object(answering, 'next_exam') as save:
            answering.jump_read(self.info)
        sleep.assert_not_called()
        save.assert_called_once_with(self.info)

    def test_fast_cold_dictionary_request_does_not_sleep(self):
        self.info.is_self_built = False
        self.info.course_id, self.info.now_unit = 'BOOK', 'U4'
        server = Mock(get=Mock(return_value=response({'means': [{'mean': ['v.', '放弃']}]}, encoded=False)))
        with patch.object(headers, 'rqs_session', server), patch.object(api.time, 'sleep') as sleep:
            api.query_word(self.info, 'abandon')
            api.query_word(self.info, 'abandon')
        self.assertEqual(server.get.call_count, 1)
        sleep.assert_not_called()

    def test_fast_real_flow_still_verifies_then_saves_once(self):
        server = TestServer()
        task = {'task_name': 'Fast class test', 'task_type': 2, 'release_id': 200, 'course_id': 'BOOK', 'progress': 0}
        order = []
        original = server.post
        def post(url, **kwargs):
            order.append(url.rsplit('/', 1)[-1])
            return original(url, **kwargs)
        server.post = post
        with ExitStack() as stack:
            for name in ('class_task_request', 'rqs_session', 'rqs2_session', 'rqs3_session'):
                stack.enter_context(patch.object(headers, name, server))
            sleep = stack.enter_context(patch.object(app.time, 'sleep'))
            stack.enter_context(patch.object(app, 'ai_answer', return_value=None))
            worker = app.TaskWorker([task], public_info=self.info, logger=Mock())
            worker.run()
        self.assertEqual(order, ['VerifyAnswer', 'SubmitAnswerAndSave'])
        self.assertEqual(self.info.right_count, 1)
        sleep.assert_not_called()

    def test_regular_read_and_submission_keep_their_waits(self):
        self.info._fast_mode = False
        with patch.object(answering.time, 'sleep') as sleep, patch.object(answering, 'next_exam'):
            answering.jump_read(self.info)
        self.assertEqual(sleep.call_count, 1)
        self.assertIn(sleep.call_args.args[0], (1, 2, 3))

    def test_default_and_preference_roundtrip(self):
        config = {'min_time': 2, 'max_time': 2, 'spend_min_time': 1, 'spend_max_time': 2,
                  'br_choices': True, 'accept_encoding': 'gzip', 'version': 'test', 'know_version': 'test',
                  'read': True, 'extra_setting': 'keep'}
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'config'
            folder.mkdir()
            path = folder / 'config.json'
            path.write_text(json.dumps(config), encoding='utf-8')
            info = PublicInfo(root)
            self.assertTrue(info.fast_mode)
            info.input_info(2, 2, 1, 2, True, 'gzip', fast_mode=False)
            self.assertFalse(PublicInfo(root).fast_mode)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['extra_setting'], 'keep')


class FastModeSettingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_settings_can_toggle_fast_mode_and_apply(self):
        info = PublicInfo(str(ROOT))
        info._fast_mode = True
        form = Ui_Form(info)
        try:
            self.assertTrue(form.fastModeCheckBox.isChecked())
            self.assertFalse(form.min_time.isEnabled())
            form.fastModeCheckBox.setChecked(False)
            self.assertTrue(form.min_time.isEnabled())
            with patch.object(info, 'input_info') as save:
                self.assertTrue(form.input())
            self.assertEqual(save.call_args.kwargs, {'fast_mode': False})
        finally:
            form.close()


if __name__ == '__main__':
    unittest.main()
