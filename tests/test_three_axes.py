"""Reduce stacked waits, preserve server option tags and show learning completion."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import logging
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication, QMessageBox, QRadioButton
import main as app
import util.select_mean as selection
from publicInfo.publicInfo import PublicInfo
from util.lexical_match import choose_mean
from util.task_completion import RecentCompletions
from view.main_window import UiMainWindow

ROOT = Path(__file__).resolve().parents[1]


def dictionary(mean):
    return {'means': [{'mean': [mean], 'usages': []}]}


class PacingTests(unittest.TestCase):
    def worker(self, **fields):
        info = SimpleNamespace(min_time=2, max_time=2, exam={'topic_mode': 11}, **fields)
        return app.TaskWorker([], public_info=info, logger=Mock())

    def test_slow_question_has_no_extra_wait(self):
        worker = self.worker()
        with patch.object(app.time, 'monotonic', return_value=13), patch.object(app.time, 'sleep') as sleep:
            self.assertEqual(worker.pace_question(10), 0)
        sleep.assert_not_called()

    def test_fast_question_waits_only_for_remaining_interval(self):
        worker = self.worker()
        with patch.object(app.time, 'monotonic', return_value=10.6), patch.object(app.time, 'sleep') as sleep:
            self.assertAlmostEqual(worker.pace_question(10), 1.4)
        self.assertAlmostEqual(sleep.call_args.args[0], 1.4)

    def test_longer_user_setting_is_respected(self):
        worker = self.worker()
        worker.public_info.min_time, worker.public_info.max_time = 5, 7
        with patch.object(app.random, 'randint', return_value=6) as random, \
             patch.object(app.time, 'monotonic', return_value=12), patch.object(app.time, 'sleep') as sleep:
            self.assertEqual(worker.pace_question(10), 4)
        random.assert_called_once_with(5, 7)
        sleep.assert_called_once_with(4)

    def test_stop_and_completion_do_not_add_wait(self):
        for stopped, complete in ((True, False), (False, True)):
            worker = self.worker()
            worker._is_running = not stopped
            if complete:
                worker.public_info.exam = 'complete'
            with patch.object(app.time, 'sleep') as sleep:
                self.assertEqual(worker.pace_question(10), 0)
            sleep.assert_not_called()


class WordOptionTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def resolve(self, options, table, mean):
        info = SimpleNamespace(exam={'options': options})
        def query(current, word):
            current.word_query_result = dictionary(table[word])
        with patch.object(selection, 'query_word', side_effect=query):
            return selection.select_match_word(info, mean)

    def test_nonsequential_server_tag_is_used(self):
        options = [{'content': 'sprout', 'answer_tag': 10}, {'content': 'occur', 'answer_tag': 70}]
        self.assertEqual(self.resolve(options, {'sprout': 'v. 生发', 'occur': 'v. 发生'}, 'v. 发生'), 70)

    def test_valid_zero_tag_is_preserved(self):
        self.assertEqual(self.resolve([{'content': 'occur', 'answer_tag': 0}], {'occur': 'verb 发生'}, 'v. 发生'), 0)

    def test_missing_tag_falls_back_to_original_position(self):
        options = [{'content': 'sprout'}, {'content': 'occur'}]
        self.assertEqual(self.resolve(options, {'sprout': 'verb 生发', 'occur': 'verb 发生'}, 'v. 发生'), 1)

    def test_character_anagram_is_not_a_translation_match(self):
        self.assertIsNone(self.resolve([{'content': 'sprout', 'answer_tag': 10}], {'sprout': 'v. 生发'}, 'v. 发生'))

    def test_multiple_matching_choices_defer(self):
        options = [{'content': 'happen', 'answer_tag': 2}, {'content': 'occur', 'answer_tag': 9}]
        self.assertIsNone(self.resolve(options, {'happen': 'verb 发生', 'occur': 'v. 发生'}, 'v. 发生'))

    def test_full_and_abbreviated_part_of_speech_are_distinguished(self):
        options = [{'content': 'record', 'answer_tag': 2}, {'content': 'recording', 'answer_tag': 9}]
        self.assertEqual(self.resolve(options, {'record': 'verb 记录', 'recording': 'noun 记录'}, 'n. 记录'), 9)

    def test_full_part_of_speech_also_works_for_meaning_choices(self):
        exam = {'options': [{'content': 'verb 记录', 'answer_tag': 8}, {'content': 'n. 记录', 'answer_tag': 0}]}
        self.assertEqual(choose_mean(exam, dictionary('noun 记录')), 0)

    def test_real_ad_abbreviation_matches_adv_dictionary_sense(self):
        exam = {'options': [{'content': 'ad. 然而，尽管如此', 'answer_tag': 0}]}
        self.assertEqual(choose_mean(exam, dictionary('adv. 然而，尽管如此')), 0)

    def test_ad_abbreviation_is_not_mistaken_for_a_noun(self):
        exam = {'options': [{'content': 'ad. 然而，尽管如此', 'answer_tag': 0}]}
        self.assertIsNone(choose_mean(exam, dictionary('n. 然而，尽管如此')))


    def test_unreleased_distractor_does_not_trigger_unavailable_dictionary_query(self):
        info = SimpleNamespace(is_self_built=True, word_list=['occur'], exam={'options': [
            {'content': 'outside', 'answer_tag': 5}, {'content': 'occur', 'answer_tag': 70}]})
        def query(current, word):
            self.assertEqual(word, 'occur')
            current.word_query_result = dictionary('verb 发生')
        with patch.object(selection, 'query_word', side_effect=query) as request:
            self.assertEqual(selection.select_match_word(info, 'v. 发生'), 70)
        self.assertEqual(request.call_count, 1)


class LearningCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_learning_snapshot_overlays_only_same_kind_and_course(self):
        task = {'task_type': 1, 'course_id': 'BOOK', 'release_id': 200, 'progress': 100, 'score': 100}
        cache = RecentCompletions()
        cache.remember(task)
        rows = [dict(task, progress=99, score=99), dict(task, task_type=2, progress=50),
                dict(task, course_id='OTHER', progress=50)]
        result = cache.apply(rows)
        self.assertEqual((result[0]['progress'], result[0]['score']), (100, 100))
        self.assertEqual(result[1:], rows[1:])
        self.assertEqual(rows[0]['progress'], 99)

    def test_unknown_task_kind_is_not_cached(self):
        cache = RecentCompletions()
        cache.remember({'task_type': 9, 'progress': 100})
        self.assertFalse(cache.confirmed)

    def test_live_phase_and_fast_mode_are_visible_with_legacy_progress_supported(self):
        with tempfile.TemporaryDirectory() as root:
            ui = UiMainWindow(PublicInfo(str(ROOT)), root, logging.getLogger('phase-test'), app.TaskWorker)
            try:
                ui.update_progress('10/458|0|0|0|1/1|Learning|阅读卡片（不计判分）')
                self.assertIn('阅读卡片（不计判分）', ui.progress_task_label.text())
                self.assertIn('极速', ui.progress_task_label.text())
                self.assertEqual(ui.progress_right_label.text(), '正确 0')
                ui.update_progress('20/458|4|0|0|1/1|Legacy')
                self.assertIn('Legacy', ui.progress_task_label.text())
            finally:
                ui.close()

    def test_completed_learning_is_disabled_and_cannot_launch(self):
        with tempfile.TemporaryDirectory() as root:
            info = PublicInfo(str(ROOT))
            ui = UiMainWindow(info, root, logging.getLogger('completion-test'), app.TaskWorker)
            try:
                info.task_list = [{'task_name': 'Learning done', 'task_type': 1, 'course_id': 'BOOK',
                                   'release_id': 200, 'progress': 100, 'score': 100, 'over_status': 2}]
                ui.learn_task.setChecked(True)
                ui._render_tasks()
                radio = ui.task_list.cellWidget(0, 0).findChild(QRadioButton)
                self.assertFalse(radio.isEnabled())
                item = ui.task_list.item(0, 1)
                ui._on_task_item_clicked(item)
                self.assertFalse(radio.isChecked())
                ui.task_list.setCurrentItem(item)
                with patch.object(QMessageBox, 'question', side_effect=AssertionError('Already complete')), \
                     patch.object(ui, '_launch_tasks') as launch:
                    ui.start()
                launch.assert_not_called()
            finally:
                ui.close()


if __name__ == '__main__':
    unittest.main()
