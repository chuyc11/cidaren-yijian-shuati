"""Offline regression tests for class-test initialization and completion.

Run with: .venv/Scripts/python.exe -m unittest discover -s tests -v
All HTTP sessions and the optional AI fallback are replaced locally.
"""
import base64
import json
import logging
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import main as app
import api.main_api as api
import api.request_header as headers
from publicInfo.publicInfo import PublicInfo


def response(data=None, code=1, msg="处理成功！", encoded=True):
    if data is not None and encoded:
        data = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    body = {"code": code, "msg": msg, "data": data, "jv": "0"}
    result = Mock(status_code=200, text=json.dumps(body, ensure_ascii=False))
    result.json.return_value = body
    return result


class TestServer:
    """Replay the real API lifecycle without network access or account writes."""
    def __init__(self, selection=False, final_card=False, persisted=True):
        self.selection = selection
        self.final_card = final_card
        self.persisted = persisted
        self.selected = False
        self.finished = False
        self.card_sent = False
        self.starts = []
        self.verifications = []
        self.saved_codes = []
        self.word_maps = []
        self.details_calls = 0

    def details(self):
        return {
            "task_id": 900, "task_type": 2, "course_id": "BOOK",
            "task_name": "Class test", "progress": 100 if self.finished and self.persisted else 0,
            "score": 0.0, "exist_little_task": 1,
            "word_list": [{"word": "abandon", "word_zh": "放弃", "course_id": "BOOK", "list_id": "U4"}],
        }

    def question(self, card=False):
        return {
            "task_id": 900, "topic_mode": 0 if card else 15,
            "topic_code": "card" if card else "question",
            "topic_done_num": 1, "topic_total": 1,
            "stem": {"content": "abandon", "remark": ""},
            "options": [{"content": "v 放弃"}, {"content": "v 接受"}],
        }

    def get(self, url, params=None, **kwargs):
        params = params or {}
        if url.endswith("ClassTask/Info"):
            self.details_calls += 1
            return response(self.details())
        if url.endswith("StartAnswer"):
            self.starts.append(dict(params))
            # A stale ID reproduces the original immediate false completion.
            if params.get("task_id") != 900 or self.finished:
                return response(code=20004, msg="任务已完成！")
            if self.selection and not self.selected:
                return response(code=20001, msg="需要选词！")
            return response(self.question())
        if "Course/StudyWordInfo" in url:
            return response({"means": [{"mean": ["v 放弃"], "usages": []}]})
        raise AssertionError(f"Unexpected GET: {url}")

    def post(self, url, data=None, **kwargs):
        payload = json.loads(data) if isinstance(data, str) else data
        if url.endswith("SubmitChoseWord"):
            self.word_maps.append(payload["word_map"])
            self.selected = True
            return response(encoded=False)
        if url.endswith("VerifyAnswer"):
            self.verifications.append(payload)
            if payload["answer"] != 0 or payload["topic_code"] != "question":
                raise AssertionError("The solver submitted the wrong answer or topic code")
            return response({"answer_result": 1, "answer_corrects": [0], "topic_code": "verified"})
        if url.endswith("SubmitAnswerAndSave"):
            self.saved_codes.append(payload["topic_code"])
            if self.final_card and not self.card_sent:
                self.card_sent = True
                return response(self.question(card=True))
            self.finished = True
            return response(code=20004, msg="任务已完成！")
        raise AssertionError(f"Unexpected POST: {url}")


class ClassTaskTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        app.public_info = PublicInfo(str(Path(__file__).resolve().parents[1]))
        app.public_info._self_learn_pool = False
        app.public_info._self_learn_lib = False
        app.public_info.task_id = 777  # previous learning task
        app.public_info.release_id = 100
        app.public_info.is_self_built = True
        app.public_info.now_unit = "STALE"
        app.public_info.word_list = ["stale"]
        app.public_info.get_book_words_data = [{"word": "stale", "list_id": "STALE"}]
        app.public_info.all_unit_name = ["STALE"]
        app.main = Mock()
        PublicInfo.task_type = "ClassTask"
        PublicInfo.task_type_int = 2
        self.server = TestServer()
        self.enter(patch.object(headers, "class_task_request", self.server))
        self.enter(patch.object(headers, "rqs_session", self.server))
        self.enter(patch.object(headers, "rqs2_session", self.server))
        self.enter(patch.object(headers, "rqs3_session", self.server))
        self.enter(patch.object(app.time, "sleep"))
        self.ai = self.enter(patch.object(app, "ai_answer", return_value=None))
        self.enter(patch.object(headers.requests.Session, "request", side_effect=AssertionError("External HTTP disabled")))
        self.units = self.enter(patch.object(app, "get_all_unit", side_effect=self.load_units))
        self.enter(patch.object(app, "get_book_all_words", side_effect=self.load_book))
        self.task = {"task_name": "Class test", "task_type": 2, "task_id": -1,
                     "release_id": 200, "course_id": "BOOK", "progress": 0}

    def enter(self, context):
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def load_units(self, info):
        info.all_unit = {"task_list": [{"task_name": "Study unit", "list_id": "U4", "task_id": 777}]}

    def load_book(self, info):
        info.get_book_words_data = self.server.details()["word_list"]

    def worker(self):
        return app.TaskWorker([self.task])

    def test_self_built_test_uses_server_allocated_id(self):
        self.worker().complete_test(self.task)
        self.assertEqual(self.server.starts[0]["task_id"], 900)
        self.assertEqual(self.server.starts[0]["release_id"], 200)
        self.assertEqual(len(self.server.verifications), 1)
        self.assertEqual(app.public_info.exam, "complete")
        self.assertEqual(app.public_info.now_unit, "U4")
        self.assertNotIn("STALE", app.public_info.all_unit_name)
        self.ai.assert_not_called()

    def test_test_named_like_study_unit_uses_class_detail(self):
        self.task["task_name"] = "Study unit"
        self.worker().complete_test(self.task)
        self.assertEqual(self.server.starts[0]["task_id"], 900)
        self.units.assert_not_called()

    def test_need_selection_is_not_completion(self):
        self.server.selection = True
        app.public_info.task_id = 900
        with self.assertRaises(api.WordSelectionRequiredError):
            api.get_exam(app.public_info)
        self.assertNotEqual(app.public_info.exam, "complete")

    def test_selection_uses_only_released_test_words(self):
        self.server.selection = True
        self.worker().complete_test(self.task)
        self.assertEqual(self.server.word_maps, [{"BOOK:U4": ["abandon"]}])
        self.assertEqual(len(self.server.verifications), 1)
        self.assertEqual(app.public_info.exam, "complete")

    def test_final_read_card_completes_without_string_index_error(self):
        self.server.final_card = True
        self.worker().complete_test(self.task)
        self.assertEqual(self.server.saved_codes, ["verified", "card"])
        self.assertEqual(app.public_info.exam, "complete")

    def test_completed_task_emits_only_after_server_verifies_progress(self):
        worker = self.worker()
        finished, errors = [], []
        worker.task_finished.connect(finished.append)
        worker.task_error.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(finished), 1)
        self.assertGreaterEqual(self.server.details_calls, 2)
        self.assertIn("0", finished[0])

    def test_false_complete_with_zero_server_progress_is_not_success(self):
        self.server.persisted = False
        worker = self.worker()
        finished, errors = [], []
        worker.task_finished.connect(finished.append)
        worker.task_error.connect(errors.append)
        worker.run()
        self.assertEqual(finished, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("0", errors[0])

    def test_plain_json_exam_is_supported_and_topic_code_is_updated(self):
        self.server.get = Mock(return_value=response(self.server.question(), encoded=False))
        api.get_exam(app.public_info)
        self.assertEqual(app.public_info.task_id, 900)
        self.assertEqual(app.public_info.topic_code, "question")

    def test_security_verification_is_reported(self):
        self.server.get = Mock(return_value=response(code=11003, msg="需安全验证"))
        with self.assertRaises(api.SecurityVerifyError):
            api.get_exam(app.public_info)

    def test_error_includes_server_reason(self):
        self.server.get = Mock(return_value=response(code=10001, msg="缺少 release_id"))
        with self.assertRaisesRegex(Exception, "release_id"):
            api.get_exam(app.public_info)

    def test_zero_score_is_preserved(self):
        self.assertEqual(api.get_task_score(app.public_info), 0.0)

    def test_expired_task_stops_without_retries_or_success(self):
        self.server.get = Mock(return_value=response(code=20006, msg="任务已截止！"))
        worker = self.worker()
        finished, errors = [], []
        worker.task_finished.connect(finished.append)
        worker.task_error.connect(errors.append)
        worker.run()
        self.assertEqual(finished, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("截止", errors[0])
        self.assertEqual(self.server.get.call_count, 1)

    def test_batch_task_preparation_discards_previous_task_context(self):
        starts = []
        info = app.public_info
        def details(current):
            current.task_id = current.release_id + 1000
            data = self.server.details()
            data['word_list'] = [{"word": str(current.release_id), "word_zh": "", "list_id": "U4"}]
            current.get_word_list_result = {"data": data}
            return data
        def start():
            starts.append((info.task_id, info.release_id, info.word_list[:], info.topic_code, info.all_unit_name[:]))
            info.exam = 'complete'
        with patch.object(app, 'get_class_task_info', side_effect=details), patch.object(app.TaskWorker, 'class_task_answer', side_effect=start):
            worker = self.worker()
            worker.complete_test(self.task)
            info.topic_code = 'STALE'
            info.all_unit_name = ['STALE']
            worker.complete_test(dict(self.task, release_id=201))
        self.assertEqual(starts, [(1200, 200, ['200'], '', []), (1201, 201, ['201'], '', [])])

    def test_solver_error_uses_ai_for_same_question(self):
        with patch.object(app, 'answer', side_effect=ValueError('not in vocabulary')), patch.object(app, 'ai_answer', return_value=0) as ai:
            self.worker().complete_test(self.task)
        ai.assert_called_once()
        self.assertEqual(len(self.server.verifications), 1)
        self.assertEqual(app.public_info.right_count, 1)

    def test_solver_security_error_does_not_trigger_ai(self):
        with patch.object(app, 'answer', side_effect=api.SecurityVerifyError('需安全验证')):
            with self.assertRaises(api.SecurityVerifyError):
                self.worker().complete_test(self.task)
        self.ai.assert_not_called()


if __name__ == "__main__":
    unittest.main()
