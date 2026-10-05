"""Offline behavioral checks for sense selection, caching, UI jobs and recovery."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import ExitStack
import json
import logging
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox
import main as app
import api.main_api as api
import api.request_header as headers
from publicInfo.publicInfo import PublicInfo
from util.lexical_match import base_word, choose_mean, complete_word
from util.word_cache import WordCache
import util.word_revert as lemma
from util.ai_fallback import _parse_answer, _build_prompt, ai_answer
from util.task_checkpoint import TaskCheckpoint, account_key, task_key
import view.background_jobs as jobs
from view.main_window import UiMainWindow
from test_class_tasks import TestServer, response

ROOT = Path(__file__).resolve().parents[1]


def dictionary(*rows):
    return {'means': [{'mean': [mean], 'usages': [{'examples': examples}]} for mean, examples in rows]}


class LexicalTests(unittest.TestCase):
    def test_sentence_selects_its_own_sense_and_server_tag(self):
        data = dictionary(('n. 银行', [{'sen_content': 'She works at the {bank}.', 'sen_mean_cn': '她在银行工作。'}]),
                          ('n. 河岸', [{'sen_content': 'We sat on the {bank}.', 'sen_mean_cn': '我们坐在河岸上。'}]))
        exam = {'stem': {'content': 'We  sat on the {bank}.', 'remark': '我们坐在河岸上。'},
                'options': [{'content': 'n. 银行', 'answer_tag': 9}, {'content': 'n. 河岸', 'answer_tag': 0}]}
        self.assertEqual(choose_mean(exam, data, True), 0)

    def test_unknown_context_with_multiple_senses_defers(self):
        data = dictionary(('n. 银行', []), ('n. 河岸', []))
        exam = {'stem': {'content': '{bank}', 'remark': '另一个未收录的句子'},
                'options': [{'content': 'n. 银行'}, {'content': 'n. 河岸'}]}
        self.assertIsNone(choose_mean(exam, data, True))

    def test_part_of_speech_distinguishes_same_translation(self):
        data = dictionary(('n. 记录', [{'sen_content': 'Keep a {record}.', 'sen_mean_cn': '保留记录。'}]),
                          ('v. 记录', []))
        exam = {'stem': {'content': 'Keep a {record}.'},
                'options': [{'content': 'v. 记录'}, {'content': 'n. 记录'}]}
        self.assertEqual(choose_mean(exam, data, True), 1)

    def test_synonym_order_and_usage_qualifier(self):
        exam = {'options': [{'content': 'n. 神职人员；牧师', 'answer_tag': 3}]}
        self.assertEqual(choose_mean(exam, dictionary(('n. （常用作复数）牧师；神职人员', []))), 3)

    def test_does_not_match_character_anagrams(self):
        self.assertIsNone(choose_mean({'options': [{'content': '出租'}]}, dictionary(('租出', []))))

    def test_inflected_words_resolve_to_released_lexeme(self):
        fallback = Mock(side_effect=AssertionError('Model unnecessary for regular forms'))
        for word, base in [('studied', 'study'), ('running', 'run'), ('conceded', 'concede'), ('antonyms', 'antonym')]:
            self.assertEqual(base_word(word, [base], fallback), base)

    def test_spelling_checks_meaning_before_first_prefix_match(self):
        info = Mock(word_list=['deduce', 'deduct'], exam={'w_tip': 'de', 'w_lens': [6],
                    'stem': {'content': '{} from ...', 'remark': '从……中扣除……'}})
        table = {'deduce': dictionary(('v. 推断', [])), 'deduct': dictionary(('v. 扣除', [
            {'sen_content': '{deduct} from ...', 'sen_mean_cn': '从……中扣除……'}]))}
        def query(current, word):
            current.word_query_result = table[word]
        self.assertEqual(complete_word(info, query), 'deduct')

    def test_spelling_ambiguous_candidates_are_not_guessed(self):
        info = Mock(word_list=['deduce', 'deduct'], exam={'w_tip': 'de', 'w_lens': [6], 'stem': {}})
        def query(current, word):
            current.word_query_result = dictionary(('未知', []))
        self.assertIsNone(complete_word(info, query))

    def test_observed_inflection_obeys_length_and_prefix(self):
        info = Mock(word_list=['study'], exam={'w_tip': 'st', 'w_lens': [7],
                    'stem': {'remark': '她昨天学习了。'}})
        def query(current, word):
            current.word_query_result = dictionary(('v. 学习', [{'sen_content': 'She {studied} yesterday.',
                                                               'sen_mean_cn': '她昨天学习了。'}]))
        self.assertEqual(complete_word(info, query), 'studied')
        info.exam['w_lens'] = [9]
        self.assertIsNone(complete_word(info, query))


class AIFallbackTests(unittest.TestCase):
    def test_choice_maps_number_to_actual_tag_including_zero(self):
        exam = {'options': [{'content': 'a', 'answer_tag': 4}, {'content': 'b', 'answer_tag': 0}]}
        self.assertEqual(_parse_answer('2', exam, 11), 0)
        self.assertEqual(_parse_answer('1', {'options': [{'content': 'a'}]}, 15), 0)

    def test_nested_choice_maps_to_server_combined_tag(self):
        exam = {'options': [{'answer_tag': '2#', 'sub_options': [{'content': 'ran', 'answer_tag': 3}]}]}
        self.assertEqual(_parse_answer('1', exam, 42), '2#3')

    def test_ambiguous_or_out_of_range_reply_is_rejected(self):
        exam = {'options': [{'content': 'a'}, {'content': 'b'}]}
        for text in ('3', '0', '1 or 2', 'the answer is 1', ''):
            self.assertIsNone(_parse_answer(text, exam, 15))

    def test_spelling_with_options_still_requests_a_word(self):
        exam = {'stem': {}, 'options': [{'content': 'ignore'}], 'w_tip': 'de', 'w_lens': [6]}
        self.assertIn('一个英文单词', _build_prompt(exam, 51))
        self.assertEqual(_parse_answer('deduct', exam, 51), 'deduct')
        for text in ('1', 'wrong', 'deduction', 'Answer: deduct'):
            self.assertIsNone(_parse_answer(text, exam, 51))

    def test_phrase_fallback_formats_blank_words_instead_of_choice_number(self):
        exam = {'stem': {'content': '_ _ of _', 'remark': '充分利用'},
                'options': [{'content': word} for word in ('make', 'full', 'use')]}
        self.assertEqual(_parse_answer('make full use of', exam, 32), 'make,full,use')
        self.assertIsNone(_parse_answer('2', exam, 32))

    def test_multi_blank_json_checks_order_length_and_prefix(self):
        exam = {'stem': {'content': '{gr} {st}'}, 'w_lens': [5, 5]}
        self.assertEqual(json.loads(_parse_answer('["green","study"]', exam, 73)), ['green', 'study'])
        for text in ('["study","green"]', '["green"]', '["green","wrong"]', 'green,study'):
            self.assertIsNone(_parse_answer(text, exam, 73))

    def test_real_ai_entry_uses_tag_and_does_not_make_another_request(self):
        cfg = {'base_url': 'https://example.invalid', 'api_key': 'test-only', 'model': 'fake'}
        rsp = Mock()
        rsp.json.return_value = {'choices': [{'message': {'content': '1'}}]}
        with patch('util.ai_fallback.load_config', return_value=cfg), patch('util.ai_fallback.requests.post', return_value=rsp) as post:
            self.assertEqual(ai_answer({'stem': {}, 'options': [{'answer_tag': 0, 'content': 'x'}]}, 15), 0)
        self.assertEqual(post.call_count, 1)


class CacheTests(unittest.TestCase):
    def test_cache_expiration_and_mutation_isolation(self):
        clock = Mock(return_value=0)
        cache = WordCache(ttl=10, clock=clock)
        data = {'means': [{'mean': ['one']} ]}
        cache.put('key', data)
        data['means'].clear()
        cached = cache.get('key')
        cached['means'].clear()
        self.assertEqual(len(cache.get('key')['means']), 1)
        clock.return_value = 10
        self.assertIsNone(cache.get('key'))

    def test_bounded_cache_evicts_least_recent_entry(self):
        cache = WordCache(maxsize=2)
        cache.put('a', {})
        cache.put('b', {})
        cache.get('a')
        cache.put('c', {})
        self.assertIsNone(cache.get('b'))
        self.assertIsNotNone(cache.get('a'))

    def test_dictionary_requests_are_scoped_by_course_and_unit(self):
        info = PublicInfo(str(ROOT))
        info.course_id, info.now_unit = 'A', 'one'
        rsp = response(dictionary(('v. 放弃', [])), encoded=False)
        session = Mock(get=Mock(return_value=rsp))
        with patch.object(headers, 'rqs_session', session), patch.object(api.time, 'sleep'):
            api.query_word(info, 'abandon')
            info.word_query_result['means'].clear()
            api.query_word(info, 'abandon')
            self.assertEqual(len(info.word_query_result['means']), 1)
            info.now_unit = 'two'
            api.query_word(info, 'abandon')
            info.course_id = 'B'
            api.query_word(info, 'abandon')
        self.assertEqual(session.get.call_count, 3)

    def test_failed_query_is_not_cached(self):
        info = PublicInfo(str(ROOT))
        info.course_id, info.now_unit = 'A', 'one'
        session = Mock(get=Mock(side_effect=[response(code=10001, msg='temporary'), response(dictionary(('v. 放弃', [])), encoded=False)]))
        with patch.object(headers, 'rqs_session', session), patch.object(api.time, 'sleep'):
            with self.assertRaises(Exception):
                api.query_word(info, 'abandon')
            api.query_word(info, 'abandon')
        self.assertEqual(session.get.call_count, 2)

    def test_book_metadata_order_does_not_change_unit(self):
        info = PublicInfo(str(ROOT))
        info.course_id, info.is_self_built = 'A', True
        info.word_list = ['abandon', 'hello']
        info.get_book_words_data = [{'word': 'hello', 'list_id': 'two'}, {'word': 'abandon', 'list_id': 'one'}]
        session = Mock(get=Mock(return_value=response(dictionary(('v. 放弃', [])), encoded=False)))
        with patch.object(headers, 'rqs_session', session), patch.object(api.time, 'sleep'):
            api.query_word(info, 'abandon')
        self.assertEqual(info.now_unit, 'one')

    def test_model_loads_once_under_parallel_calls_and_reuses_lemmas(self):
        old = lemma._model
        lemma._model = None
        lemma._local_lemma.cache_clear()
        model = Mock(return_value=[Mock(lemma_='go')])
        try:
            with patch.object(lemma.spacy, 'load', return_value=model) as load:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    self.assertEqual(list(pool.map(lemma.word_revert, ['went', 'gone', 'going', 'go'])), ['go'] * 4)
                lemma.word_revert('went')
                self.assertEqual(load.call_count, 1)
                self.assertEqual(model.call_count, 4)
        finally:
            lemma._model = old
            lemma._local_lemma.cache_clear()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.checkpoint = TaskCheckpoint(self.temp.name, 'account-A')
        self.task = {'release_id': 200, 'course_id': 'BOOK', 'task_type': 2, 'task_name': 'Test', 'task_id': -1, 'progress': 0, 'over_status': 2}
        self.info = PublicInfo(str(ROOT))
        self.info.right_count = 7

    def test_resume_uses_fresh_task_id_and_filters_unavailable_tasks(self):
        other = dict(self.task, release_id=201)
        self.checkpoint.save([self.task, other], self.info, True)
        tasks, state = self.checkpoint.reconcile([dict(self.task, task_id=900, progress=25), dict(other, progress=100)])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['task_id'], 900)
        self.assertEqual(state['counts']['right_count'], 7)
        for status in (1, 3):
            self.assertEqual(self.checkpoint.reconcile([dict(self.task, over_status=status)])[0], [])

    def test_account_identity_survives_token_change_but_isolates_accounts(self):
        user = {'student_code': 'A', 'school_name': 'School'}
        self.assertEqual(account_key(dict(user, token='old')), account_key(dict(user, token='new')))
        self.assertNotEqual(account_key(user), account_key(dict(user, student_code='B')))
        self.assertEqual(account_key({}), '')
        self.checkpoint.save([self.task], self.info, False)
        self.assertIsNone(TaskCheckpoint(self.temp.name, 'account-B').load())

    def test_corrupted_or_bad_counts_record_does_not_crash(self):
        self.checkpoint.path.parent.mkdir(parents=True)
        self.checkpoint.path.write_text('{broken', encoding='utf-8')
        self.assertIsNone(self.checkpoint.load())
        self.checkpoint.save([self.task], self.info, False)
        state = self.checkpoint.load()
        state['counts']['right_count'] = -1
        self.checkpoint.path.write_text(json.dumps(state), encoding='utf-8')
        self.assertIsNone(self.checkpoint.load())

    def test_checkpoint_whitelist_excludes_credentials_and_topic_codes(self):
        task = dict(self.task, token='private', api_key='private', topic_code='old-code', answer=1)
        self.info.exam = {'topic_code': 'live-code'}
        self.checkpoint.save([task], self.info, False)
        text = self.checkpoint.path.read_text(encoding='utf-8')
        for value in ('private', 'topic_code', 'live-code', 'api_key', '"answer"', 'token'):
            self.assertNotIn(value, text)
        self.assertFalse(self.checkpoint.path.with_suffix('.tmp').exists())

    def test_interrupted_worker_resumes_next_server_question_without_replay(self):
        server = TestServer()
        server.step = 0
        verified = []
        original_get = server.get
        original_question = server.question
        def question(card=False):
            data = original_question(card)
            data.update(topic_done_num=server.step + 1, topic_total=2,
                        topic_code='question' if server.step == 0 else 'question2')
            return data
        server.question = question
        def post(url, data=None, **kwargs):
            payload = json.loads(data) if isinstance(data, str) else data
            if url.endswith('VerifyAnswer'):
                self.assertEqual(payload['answer'], 0)
                verified.append(payload['topic_code'])
                return response({'answer_result': 1, 'answer_corrects': [0], 'topic_code': 'verified'})
            if url.endswith('SubmitAnswerAndSave'):
                server.step += 1
                if server.step == 2:
                    server.finished = True
                    return response(code=20004, msg='任务已完成！')
                return response(question())
            raise AssertionError(url)
        server.post = post
        self.info.right_count = 0
        self.info._self_learn_pool = self.info._self_learn_lib = False
        with ExitStack() as stack:
            for name in ('class_task_request', 'rqs_session', 'rqs2_session', 'rqs3_session'):
                stack.enter_context(patch.object(headers, name, server))
            stack.enter_context(patch.object(app.time, 'sleep'))
            stack.enter_context(patch.object(app, 'ai_answer', return_value=None))
            first = app.TaskWorker([self.task], public_info=self.info, logger=Mock(), checkpoint=self.checkpoint)
            first.task_progress.connect(lambda text: first.stop() if text.startswith('1/') else None)
            first.run()
            saved = self.checkpoint.load()
            self.assertEqual(verified, ['question'])
            self.assertEqual(saved['counts']['right_count'], 1)
            new_info = PublicInfo(str(ROOT))
            new_info._self_learn_pool = new_info._self_learn_lib = False
            new_info.right_count = saved['counts']['right_count']
            tasks, _ = self.checkpoint.reconcile([dict(self.task, task_id=900, progress=50)])
            second = app.TaskWorker(tasks, public_info=new_info, logger=Mock(), checkpoint=self.checkpoint)
            finished = []
            second.task_finished.connect(finished.append)
            second.run()
        self.assertEqual(verified, ['question', 'question2'])
        self.assertEqual(new_info.right_count, 2)
        self.assertEqual(len(finished), 1)
        self.assertEqual(self.checkpoint.load()['pending'], [])
        self.assertEqual(len(server.starts), 2)

    def test_stop_during_solving_does_not_submit_computed_answer(self):
        server = TestServer()
        self.info._self_learn_pool = self.info._self_learn_lib = False
        with ExitStack() as stack:
            for name in ('class_task_request', 'rqs_session', 'rqs2_session', 'rqs3_session'):
                stack.enter_context(patch.object(headers, name, server))
            stack.enter_context(patch.object(app.time, 'sleep'))
            worker = app.TaskWorker([self.task], public_info=self.info, logger=Mock(), checkpoint=self.checkpoint)
            def solve(*args):
                worker.stop()
                return 0
            stack.enter_context(patch.object(app, 'answer', side_effect=solve))
            worker.run()
        self.assertEqual(server.verifications, [])
        self.assertEqual(len(self.checkpoint.load()['pending']), 1)


class BackgroundUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.info = PublicInfo(str(ROOT))
        self.ui = UiMainWindow(self.info, self.temp.name, logging.getLogger('ui-test'), app.TaskWorker)
        self.ui.show()
        self.addCleanup(self.ui.close)

    def spin(self, condition, timeout=2):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.qt.processEvents()
            threading.Event().wait(.005)
        self.qt.processEvents()
        self.assertTrue(condition(), 'Background work did not finish')

    def test_login_and_task_list_leave_gui_timer_running(self):
        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        def login(token):
            time.sleep(.12)
            return {'data': {'user_info': {'student_code': 'A', 'school_name': 'S'}}}
        def tasks(info):
            time.sleep(.12)
            return {'groups': [], 'tasks': [{'task_name': 'Task', 'task_type': 1, 'over_status': 2, 'progress': 0}]}
        self.ui.token_input.setText('test-only')
        with patch('view.main_window.login_result', side_effect=login), patch('view.main_window.fetch_tasks', side_effect=tasks):
            before = time.monotonic()
            self.ui.token_login()
            self.assertLess(time.monotonic() - before, .08)
            self.assertFalse(self.ui.login.isEnabled())
            self.spin(lambda: self.ui._network_job is None and self.ui.task_list.rowCount() == 1)
        timer.stop()
        self.assertGreaterEqual(len(ticks), 10)
        self.assertTrue(self.ui.login.isEnabled())
        self.assertTrue(self.ui.refresh_tasks.isEnabled())

    def test_failed_job_restores_controls_without_stale_login(self):
        self.ui.token_input.setText('test-only')
        with patch('view.main_window.login_result', side_effect=RuntimeError('offline')):
            self.ui.token_login()
            self.spin(lambda: self.ui._network_job is None)
        self.assertTrue(self.ui.login.isEnabled())
        self.assertFalse(self.ui.start_task.isEnabled())
        self.assertIn('网络操作失败', self.ui.warn_info.text())

    def test_task_fetch_does_not_mutate_active_task_state(self):
        self.info.exam = {'topic_code': 'current'}
        self.info.class_task = [{'records': [{'task_name': 'old'}]}]
        def page(info, page):
            info.class_task.append({'records': [{'task_name': 'new'}]})
            info.task_total_count = 1
        with patch.object(jobs, 'get_class_task', side_effect=page):
            result = jobs.fetch_tasks(self.info)
        self.assertEqual(self.info.exam['topic_code'], 'current')
        self.assertEqual(self.info.class_task[0]['records'][0]['task_name'], 'old')
        self.assertEqual(result['tasks'][0]['task_name'], 'new')

    def test_resume_button_launches_only_fresh_available_tasks(self):
        task = {'release_id': 8, 'course_id': 'A', 'task_type': 2, 'task_name': 'Pending', 'task_id': -1, 'progress': 0, 'over_status': 2}
        done = dict(task, release_id=9, task_name='Done')
        self.ui._checkpoint = TaskCheckpoint(self.temp.name, 'A')
        self.info.right_count = 7
        self.ui._checkpoint.save([task, done], self.info, True)
        self.ui._logged_in = True
        self.ui._on_tasks_ready({'groups': [], 'tasks': [dict(task, task_id=900, progress=50), dict(done, progress=100)]})
        self.ui._sync_controls()
        self.assertTrue(self.ui.resume_task.isEnabled())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), patch.object(self.ui, '_launch_tasks') as launch:
            self.ui.resume_tasks()
        called_tasks, batch, counts = launch.call_args.args
        self.assertEqual([t['task_id'] for t in called_tasks], [900])
        self.assertTrue(batch)
        self.assertEqual(counts['right_count'], 7)

    def test_stop_is_nonblocking_and_waits_for_thread_finished(self):
        worker = Mock()
        self.ui.task_worker = worker
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.ui.stop_current_task()
        worker.stop.assert_called_once()
        worker.wait.assert_not_called()
        self.assertIs(self.ui.task_worker, worker)
        self.assertFalse(self.ui.stop_task.isEnabled())
        self.ui.task_worker = None


if __name__ == '__main__':
    unittest.main()
