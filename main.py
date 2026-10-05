# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
import os
import random
import sys
import time
from requests.exceptions import Timeout as NetworkTimeout, ConnectionError as NetworkConnectionError, ChunkedEncodingError

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from answer_questions.answer_questions import *
from api.basic_api import get_all_unit, get_unit_words, get_book_all_words
from api.main_api import get_exam, select_all_word, skip_exam, get_task_score, get_class_task_info, \
    SecurityVerifyError, WordSelectionRequiredError, TaskUnavailableError, UnsupportedResponseEncodingError, begin_word_prefetch
from log.log import Log
from publicInfo.publicInfo import PublicInfo
from util.basic_util import extract_book_word, query_word_unit
from util.ai_fallback import ai_answer
from util.handle_word_list import handle_word_result, get_task_word_map
from api.update import get_update
from decryptencrypt.debase64 import debase64
from view.main_window import UiMainWindow
from util.task_report import TaskReport, MODE_NAMES


class UnresolvedAnswerError(RuntimeError):
    """Keep a graded test on its current question when no reliable answer exists."""


class TaskWorker(QThread):
    task_finished = pyqtSignal(str)
    task_completed = pyqtSignal(object)  # Immutable identity/score snapshot before the next batch task.
    task_error = pyqtSignal(str)
    task_progress = pyqtSignal(str)
    task_notice = pyqtSignal(str)     # 重试/跳过等提示
    batch_finished = pyqtSignal(str)  # 批量模式全部执行结束

    def __init__(self, task_infos, batch_mode=False, public_info=None, logger=None, checkpoint=None):
        super().__init__()
        self.public_info = public_info if public_info is not None else globals()['public_info']
        self.logger = logger if logger is not None else globals()['main'].logger
        self.checkpoint = checkpoint
        self.pending_tasks = list(task_infos)
        self._checkpoint_failed = False
        self.task_infos = list(task_infos)
        self._task_kind = int(self.task_infos[0]['task_type']) if self.task_infos else None
        self.batch_mode = batch_mode
        self._is_running = True
        self.start_time = None
        self.current_task_name = ''
        self.current_index = 0
        self.current_total = 0
        self._furthest_topic = 0
        self._last_topic_total = 0
        self._completion_confirmed = False
        self._active_task_info = None
        self._ambiguous_deferrals = set()
        self._word_prefetch = None
        self.public_info._word_prefetch_started = False

    def run(self):
        self.save_checkpoint()
        total = len(self.task_infos)
        success_count = 0
        failed_tasks = []
        for index, task_info in enumerate(self.task_infos, start=1):
            if not self._is_running:
                break
            task_name = task_info['task_name']
            self._active_task_info = task_info
            if index > 1:
                for key in ('right_count', 'wrong_count', 'skip_count'):
                    setattr(self.public_info, key, 0)
            self.current_task_name = task_name
            self.current_index = index
            self.current_total = total
            self.logger.info(f"开始执行任务[{index}/{total}]：{task_name}")
            attempts = 0
            consecutive_failures = 0
            last_failed_topic = -1
            self._furthest_topic = 0
            self._last_topic_total = 0
            self._completion_confirmed = False
            self._ambiguous_deferrals.clear()
            self.start_time = time.monotonic()
            self.public_info._task_report = None
            self.save_checkpoint()
            while self._is_running:
                attempts += 1
                try:
                    self.complete_test(task_info)
                    if self._is_running:
                        if self.public_info.exam != 'complete':
                            raise RuntimeError('答题流程未到达完成状态')
                        result = get_class_task_info(self.public_info)
                        progress = float(result.get('progress') or 0)
                        if progress < 100:
                            raise RuntimeError(f"服务器任务进度仍为 {progress:g}%，尚未确认完成")
                        score = result.get('score')
                        self._completion_confirmed = True
                        self.emit_progress()
                        elapsed_time = time.monotonic() - self.start_time
                        report = getattr(self.public_info, '_task_report', None)
                        if report is not None:
                            try:
                                report.finish(score, elapsed_time, self.public_info)
                            except Exception as exc:
                                self.logger.warning(f'测试已完成，但报告保存失败：{type(exc).__name__}')
                        message = f"[{index}/{total}] {task_name} 已完成，用时 {elapsed_time:.2f} 秒"
                        if score is not None:
                            message += f"，得分 {float(score):g}"
                        self.pending_tasks = [t for t in self.pending_tasks if t is not task_info]
                        self.save_checkpoint()
                        self.task_completed.emit({key: task_info.get(key) for key in
                                                  ('release_id', 'course_id', 'task_name', 'task_type')} |
                                                 {'progress': 100, 'score': score})
                        self.task_finished.emit(message)
                        success_count += 1
                    break
                except (UnsupportedResponseEncodingError, UnresolvedAnswerError) as e:
                    self.flush_report()
                    self.save_checkpoint()
                    self.logger.error(f'任务 {task_name} 已停止：{e}')
                    self.task_error.emit(f'任务 {task_name} 已停止：{e}')
                    return
                except SecurityVerifyError as e:
                    self.flush_report()
                    self.save_checkpoint()
                    # 服务端风控(11003): 重试无意义(2秒内不可能解除验证), 立即停止当前任务
                    self.logger.error(f"任务 {task_name} 需安全验证: {e}")
                    if self.batch_mode:
                        failed_tasks.append(task_name)
                        self.task_notice.emit(f"[{index}/{total}] 任务 {task_name} 需安全验证已跳过：{e}，请完成验证后重试")
                    else:
                        self.task_error.emit(f"任务 {task_name} 需安全验证：{e}")
                        return
                    break
                except TaskUnavailableError as e:
                    self.flush_report()
                    self.save_checkpoint()
                    self.logger.error(f"任务 {task_name} 无法执行：{e}")
                    if self.batch_mode:
                        failed_tasks.append(task_name)
                        self.task_notice.emit(f"[{index}/{total}] 任务 {task_name} 无法执行，已跳过：{e}")
                    else:
                        self.task_error.emit(f"任务 {task_name} 无法执行：{e}")
                        return
                    break
                except Exception as e:
                    self.flush_report()
                    self.logger.error(f"任务 {task_name} 执行出错（第{attempts}次）: {e}", exc_info=True)
                    consecutive_failures = 1 if self._furthest_topic > last_failed_topic else consecutive_failures + 1
                    last_failed_topic = self._furthest_topic
                    if consecutive_failures >= 3:
                        if self.batch_mode:
                            failed_tasks.append(task_name)
                            self.task_notice.emit(f"[{index}/{total}] 任务 {task_name} 连续失败3次，已跳过，继续下一个")
                        else:
                            self.task_error.emit(f"任务 {task_name} 连续失败3次：{e}")
                            return
                        break
                    if not self._is_running:
                        break
                    reason = '网络请求超时' if isinstance(e, NetworkTimeout) else \
                             '网络连接中断' if isinstance(e, NetworkConnectionError) else str(e)
                    self.task_notice.emit(f"[{index}/{total}] {task_name}：{reason}，2秒后重新读取服务器进度继续（连续失败 {consecutive_failures}/3）")
                    time.sleep(2)

        if self._is_running and self.batch_mode:
            summary = f"一键刷题完成：成功 {success_count} 个，失败 {len(failed_tasks)} 个"
            if failed_tasks:
                summary += f"\n失败任务：{', '.join(failed_tasks)}"
            self.batch_finished.emit(summary)

    def save_checkpoint(self):
        if self.checkpoint is not None:
            try:
                self.checkpoint.save(self.pending_tasks, self.public_info, self.batch_mode,
                                     counts_task=self._active_task_info)
            except OSError as exc:
                self.logger.warning(f'保存恢复记录失败：{exc}')
                if not self._checkpoint_failed:
                    self._checkpoint_failed = True
                    self.task_notice.emit('无法保存恢复记录，请检查目录权限和磁盘空间')

    def stop(self):
        self._is_running = False
        self.close_word_prefetch()
        self.flush_report()

    def close_word_prefetch(self):
        pool, self._word_prefetch = self._word_prefetch, None
        self.public_info._word_prefetch = None
        if pool is not None:
            pool.close()

    def flush_report(self):
        report = getattr(self.public_info, '_task_report', None)
        if report is not None:
            try:
                elapsed = time.monotonic() - self.start_time if self.start_time is not None else None
                report.save(elapsed)
            except Exception as exc:
                self.logger.warning(f'保存判分报告失败：{type(exc).__name__}')

    def _ensure_report(self, task_info):
        if getattr(self.public_info, '_task_report', None) is not None:
            return
        if self.checkpoint is not None and self.checkpoint.account:
            try:
                self.public_info._task_report = TaskReport(self.checkpoint.root,
                                                          self.checkpoint.account, task_info)
                records = self.public_info._task_report.data['records']
                for key, value in {'right_count': sum(row.get('right') is True for row in records),
                                   'wrong_count': sum(row.get('right') is False for row in records),
                                   'skip_count': sum(bool(row.get('skipped')) for row in records)}.items():
                    setattr(self.public_info, key, max(int(getattr(self.public_info, key, 0)), value))
                self.public_info._graded_event_ids = {row['event_id'] for row in records if row.get('event_id')}
            except Exception as exc:
                self.logger.warning(f'初始化测试报告失败：{type(exc).__name__}')

    def complete_test(self, task_info: dict):
        task_name = task_info['task_name']
        task_kind = int(task_info['task_type'])
        self._task_kind = task_kind
        self.public_info._strict_test = task_kind == 2
        if task_kind not in (1, 2):
            raise RuntimeError(f'不支持的班级任务类型：{task_kind}')
        PublicInfo.task_type = 'ClassTask'
        PublicInfo.task_type_int = 2
        self.public_info.course_id = task_info['course_id']
        self.public_info.release_id = task_info['release_id']
        self.public_info.task_id = task_info.get('task_id') or -1
        self.public_info._task_name = task_name
        self.public_info.is_self_built = False
        self.public_info.now_unit = ''
        self.public_info.all_unit_name = []
        self.public_info.all_unit = []
        self.public_info.word_list = []
        self.public_info.get_word_list_result = {}
        self.public_info.get_book_words_data = []
        self.public_info.word_query_result = {}
        self.public_info.source_option = []
        self.public_info.exam = ''
        self.public_info.topic_code = ''
        self.logger.info(f'开始执行任务：{task_name}')
        self.logger.info('初始化班级任务并获取本次发布的词表')
        details = get_class_task_info(self.public_info)
        if float(details.get('progress') or 0) >= 100:
            self.public_info.exam = 'complete'
            self.task_notice.emit(f'{task_name}：服务器确认任务已完成，无需再次作答')
            return
        self._ensure_report(task_info)
        handle_word_result(self.public_info)
        self.public_info.is_self_built = True
        words = details.get('word_list', [])
        if words and all(word.get('list_id') for word in words):
            self.public_info.get_book_words_data = words
        else:
            get_book_all_words(self.public_info)
            extract_book_word(self.public_info)
        try:
            self.class_task_answer()
        finally:
            self.close_word_prefetch()

    def emit_progress(self):
        """
        发送答题进度
        :return:
        """
        self.save_checkpoint()
        if isinstance(self.public_info.exam, dict):
            try:
                current = int(self.public_info.exam.get('topic_done_num') or 0)
                total = int(self.public_info.exam.get('topic_total') or 0)
            except (TypeError, ValueError):
                return
            if total <= 0:
                return
            self._last_topic_total = total
            self._furthest_topic = max(self._furthest_topic, min(total, current))
            # The server field is the position of the question now on screen.
            done = max(0, min(total, current - 1))
        elif self.public_info.exam == 'complete' and self._completion_confirmed:
            total = self._last_topic_total
            done = total
        else:
            return
        if total:
            if self._completion_confirmed:
                phase = '已完成'
            else:
                mode = self.public_info.exam.get('topic_mode')
                phase = '阅读卡片（不计判分）' if mode == 0 else MODE_NAMES.get(mode, '正在答题')
            self.task_progress.emit(f"{done}/{total}|{self.public_info.right_count}|{self.public_info.wrong_count}|{self.public_info.skip_count}|{self.current_index}/{self.current_total}|{self.current_task_name}|{phase}")

    def start_answer(self):
        try:
            get_exam(self.public_info)
        except WordSelectionRequiredError:
            self.logger.info('服务器要求选词，先提交当前任务词表')
            if PublicInfo.task_type == 'ClassTask':
                get_class_task_info(self.public_info)
            else:
                get_unit_words(self.public_info)
            select_all_word(get_task_word_map(self.public_info), self.public_info.task_id)
            get_exam(self.public_info)

    def advance_question(self, operation, *args):
        """Some final saves say 'select words'; confirm task details before retrying."""
        try:
            return operation(self.public_info, *args)
        except WordSelectionRequiredError:
            if PublicInfo.task_type != 'ClassTask':
                raise
            details = get_class_task_info(self.public_info)
            if float(details.get('progress') or 0) < 100:
                raise
            self.public_info.exam = 'complete'
            self.public_info.topic_code = ''
            self.public_info._pending_submission = None
            return True

    def pace_question(self, started):
        """Count solving, verification and saving toward the configured interval."""
        if not self._is_running or self.public_info.exam == 'complete' or getattr(self.public_info, 'fast_mode', False):
            return 0
        target = random.randint(self.public_info.min_time, self.public_info.max_time)
        elapsed = max(0, time.monotonic() - started)
        remaining = max(0, target - elapsed)
        if remaining:
            time.sleep(remaining)
        return remaining

    def class_task_answer(self):
        # 确保单元词表已加载(汉译英术语题依赖词表的 word_zh)
        if not self.public_info.word_list:
            try:
                get_unit_words(self.public_info)
                handle_word_result(self.public_info)
            except Exception as e:
                self.logger.error(f"加载词表失败: {e}", exc_info=True)
        self.start_answer()
        if self.public_info.exam == 'complete':
            self.logger.info('该任务已完成，无法重复作答')
            return
        # Resumed tasks can start on a graded question after all cards are done.
        self._word_prefetch = begin_word_prefetch(self.public_info)
        self.public_info.topic_code = self.public_info.exam['topic_code']
        self.emit_progress()
        self.logger.info("开始答题")
        while self._is_running:
            if self._word_prefetch is not None:
                self._word_prefetch.raise_if_failed()
            self.logger.info("获取题目类型")
            if self.public_info.exam == 'complete':
                break
            mode = self.public_info.exam['topic_mode']
            self.logger.info(f'题目类型{mode}')
            if mode == 0:
                self.advance_question(jump_read)
                self.emit_progress()
                continue
            if self.advance_question(resume_submission):
                self.emit_progress()
                continue
            question_started = time.monotonic()
            try:
                self.public_info._answer_source = 'local'
                option = answer(self.public_info, mode)
            except (SecurityVerifyError, TaskUnavailableError, NetworkTimeout, NetworkConnectionError, ChunkedEncodingError):
                raise
            except Exception as e:
                self.logger.warning(f'本地解题失败，尝试 AI 兜底：{type(e).__name__}: {e}')
                option = None
            if option is None and getattr(self.public_info, '_answer_issue', None) != 'ambiguous_mean':
                option = ai_answer(self.public_info.exam, mode)
                if option is not None:
                    self.public_info._answer_source = 'ai'
                    self.logger.info(f'AI 兜底给出答案: {option}')
            if not self._is_running:
                self.save_checkpoint()
                return
            if option is None:
                if self._task_kind == 2:
                    if getattr(self.public_info, '_answer_issue', None) == 'ambiguous_mean':
                        raise UnresolvedAnswerError('多个选项符合词典释义，但题干无法区分；已保留当前题供确认后恢复')
                    raise UnresolvedAnswerError('当前题没有可靠答案，已保留进度；请检查 AI 配置或在词达人中完成当前题后恢复')
                if getattr(self.public_info, '_answer_issue', None) == 'ambiguous_mean':
                    stem = self.public_info.exam.get('stem') or {}
                    identity = (self.public_info.exam.get('topic_done_num'), mode, stem.get('content'), stem.get('remark'))
                    if identity in self._ambiguous_deferrals:
                        raise UnresolvedAnswerError('服务器重复返回同一道歧义题，已保留进度，避免反复跳过')
                    self._ambiguous_deferrals.add(identity)
                    self.public_info.exam['_skip_reason'] = 'ambiguous_mean'
                    self.task_notice.emit('题干无法区分多个正确词义，练习暂时跳过此题并记录原因')
                self.public_info.topic_code = self.public_info.exam['topic_code']
                self.advance_question(skip_exam)
            else:
                self.advance_question(submit, option)
            self.emit_progress()
            self.pace_question(question_started)

    def complete_practice(self, unit: str, progress: int, task_id=None):
        self.logger.info(f"获取该{unit}单元的单词")
        self.public_info.now_unit = unit
        self.public_info.task_id = task_id
        get_unit_words(self.public_info)
        self.logger.info("处理words")
        handle_word_result(self.public_info)
        self.logger.info("选择该单元所有单词")
        exist_little_task = None
        gwlr = self.public_info.get_word_list_result
        if isinstance(gwlr, dict) and 'data' in gwlr:
            data_field = gwlr['data']
            if isinstance(data_field, dict):
                exist_little_task = data_field.get('exist_little_task')
            else:
                try:
                    if 'jv' in gwlr:
                        decoded = debase64(data_field, gwlr.get('jv'))
                        if isinstance(decoded, dict):
                            exist_little_task = decoded.get('exist_little_task')
                            self.public_info.get_word_list_result = decoded
                except Exception as e:
                    self.logger.error(f"解析 get_word_list_result 失败: {e}", exc_info=True)
        if (progress < 2 and exist_little_task != 1) or exist_little_task == 2:
            try:
                select_all_word({f"{self.public_info.course_id}:{unit}": self.public_info.word_list}, self.public_info.task_id)
            except Exception as e:
                self.logger.info("任务已经开启")
        self.start_answer()
        if self.public_info.exam == 'complete':
            self.logger.info('该任务已完成，无法重复作答')
            return
        self.public_info.topic_code = self.public_info.exam['topic_code']
        self.emit_progress()
        self.logger.info("开始答题")
        while self._is_running:
            self.logger.info("获取题目类型")
            if self.public_info.exam == 'complete':
                self.logger.info('该单元已完成')
                break
            mode = self.public_info.exam['topic_mode']
            if mode == 0:
                self.advance_question(jump_read)
                self.emit_progress()
                continue
            if self.advance_question(resume_submission):
                self.emit_progress()
                continue
            question_started = time.monotonic()
            self.public_info._answer_source = 'local'
            option = answer(self.public_info, mode)
            if option is None and getattr(self.public_info, '_answer_issue', None) != 'ambiguous_mean':
                option = ai_answer(self.public_info.exam, mode)
                if option is not None:
                    self.public_info._answer_source = 'ai'
                    self.logger.info(f'AI 兜底给出答案: {option}')
            if not self._is_running:
                self.save_checkpoint()
                return
            if option is None:
                self.public_info.topic_code = self.public_info.exam['topic_code']
                self.advance_question(skip_exam)
            else:
                self.advance_question(submit, option)
            self.emit_progress()
            self.pace_question(question_started)


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        from release_selftest import run
        sys.exit(run())
    main = Log("main")
    main.logger.info("初始化主页面")
    path = os.path.dirname(__file__)
    main.logger.info("初始化公共组件")
    public_info = PublicInfo(path)
    main.logger.info(f"当前版本号：{public_info.version}")

    app = QApplication(sys.argv)
    if not public_info.read:
        main.logger.info("显示首次使用提示页面")
        import view.first_note

        note = view.first_note.Ui_Form(public_info)
        note.show()
        app.exec()

    try:
        ui = UiMainWindow(public_info, path, main, TaskWorker)
        ui.show()


        class UpdateCheckThread(QThread):
            version_ready = pyqtSignal(str)

            def run(self):
                self.version_ready.emit(get_update())


        update_thread = UpdateCheckThread()


        def on_version_checked(latest_version):
            if public_info.version < latest_version and public_info.know_version < latest_version:
                import view.update
                update = view.update.Ui_Form(public_info)
                update.exec()


        update_thread.version_ready.connect(on_version_checked)
        update_thread.start()

        app.exec()
    except Exception as e:
        main.logger.error(e)
        main.logger.error("程序异常")
        import view.error

        ui = view.error.Ui_Form()
        ui.show()
        app.exec()
