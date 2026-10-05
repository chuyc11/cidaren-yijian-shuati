# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
"""Account-scoped, credential-free reports from received server grading."""
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
import time
from threading import RLock

MODE_NAMES = {11: '例句选义', 15: '看词选义', 16: '看词选义', 17: '看义选词', 18: '看义选词',
              21: '听词选义', 22: '听词选义', 31: '配对', 32: '短语填空', 41: '选词填空',
              42: '选词填空', 43: '选词填空', 44: '选词填空', 51: '补全单词', 52: '补全单词',
              53: '补全单词', 54: '补全单词', 73: '多空拼写'}


def report_folder(root, account):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', account):
        raise ValueError('Invalid report account namespace')
    return Path(root) / 'log' / 'task_reports' / account


def reports_for_account(root, account):
    folder = report_folder(root, account)
    return sorted(folder.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True) if folder.exists() else []


def readable_answer(answer, options):
    if isinstance(answer, list):
        return '、'.join(readable_answer(value, options) for value in answer)
    for index, option in enumerate(options or []):
        if option.get('tag', index) == answer:
            return str(option.get('content') or answer)
    return str(answer)


class TaskReport:
    def __init__(self, root, account, task):
        folder = report_folder(root, account)
        release = str(task.get('release_id', 'unknown'))
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', release):
            raise ValueError('Invalid report task identifier')
        self.path = folder / (release + '.json')
        self.lock = RLock()
        self.segment_started = time.monotonic()
        self.previous_elapsed = 0
        self.data = {'version': 1, 'account': account, 'task': {key: task.get(key) for key in
                     ('release_id', 'course_id', 'task_name', 'task_type')}, 'created_at': time.time(),
                     'complete': False, 'records': [], 'score': None, 'counts': {}}
        try:
            previous = json.loads(self.path.read_text(encoding='utf-8'))
            if (previous.get('version') == 1 and previous.get('account') == account and
                previous.get('task') == self.data['task'] and not previous.get('complete') and
                isinstance(previous.get('records'), list) and all(isinstance(row, dict) for row in previous['records'])):
                self.data = previous
                self.previous_elapsed = max(0, float(previous.get('elapsed_seconds') or 0))
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def record(self, exam, answer, verdict, source='local'):
        if not isinstance(exam, dict) or verdict.get('answer_result') not in (1, 2):
            return
        return self._record(exam, answer, verdict, source)

    def record_skip(self, exam):
        if isinstance(exam, dict):
            self._record(exam, None, {'skipped': True}, 'skip')

    def _record(self, exam, answer, verdict, source):
        stem = exam.get('stem') or {}
        options = []
        for index, option in enumerate(exam.get('options') or []):
            if isinstance(option, dict):
                tag = option.get('answer_tag')
                options.append({'content': option.get('content'), 'tag': index if tag is None else tag})
        entry = {'position': exam.get('topic_done_num'), 'mode': exam.get('topic_mode'),
                 'stem': {'content': stem.get('content'), 'remark': stem.get('remark')}, 'options': options,
                 'answer': deepcopy(answer), 'corrects': deepcopy(verdict.get('answer_corrects')),
                 'right': None if verdict.get('skipped') else verdict['answer_result'] == 1,
                 'source': source if source in ('local', 'ai', 'skip') else 'unknown'}
        if verdict.get('skipped'):
            entry['skipped'] = True
            if exam.get('_skip_reason') == 'ambiguous_mean':
                entry['skip_reason'] = 'ambiguous_mean'
        if verdict.get('_event_id'):
            entry['event_id'] = verdict['_event_id']
        with self.lock:
            if entry.get('event_id') and any(row.get('event_id') == entry['event_id'] for row in self.data['records']):
                return False
            self.data['records'].append(entry)
            if len(self.data['records']) % 10 == 0:
                self.save()
        return True

    def finish(self, score, elapsed, info):
        with self.lock:
            self.data.update(complete=True, score=score, elapsed_seconds=round(self.previous_elapsed + elapsed, 2), finished_at=time.time(),
                             counts={key: int(getattr(info, key, 0)) for key in ('right_count', 'wrong_count', 'skip_count')})
            self.save()

    def save(self, elapsed=None):
        with self.lock:
            if not self.data.get('complete'):
                current = time.monotonic() - self.segment_started if elapsed is None else elapsed
                self.data['elapsed_seconds'] = round(self.previous_elapsed + max(0, current), 2)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(self.path)


def format_report(data):
    task = data.get('task') or {}
    score = data.get('score')
    counts = data.get('counts') or {}
    records = data.get('records') or []
    lines = [str(task.get('task_name') or '测试报告'), '',
             '状态：' + ('服务器已确认完成' if data.get('complete') else '执行记录，尚未确认完成'),
             f"服务器得分：{score if score is not None else '—'}"]
    if 'elapsed_seconds' in data:
        lines.append(f"总用时：{float(data['elapsed_seconds']):.2f} 秒")
    if counts:
        lines.append(f"正确 {counts.get('right_count', 0)} / 错误 {counts.get('wrong_count', 0)} / 跳过 {counts.get('skip_count', 0)}")
    grouped = defaultdict(Counter)
    for entry in records:
        kind = 'skip' if entry.get('skipped') else 'right' if entry.get('right') else 'wrong'
        grouped[entry.get('mode')][kind] += 1
    lines.extend(['', '按题型的判分统计：'])
    for mode in sorted(grouped, key=lambda value: int(value or 0)):
        counter = grouped[mode]
        total = counter['right'] + counter['wrong']
        rate = f"{counter['right'] / total:.1%}" if total else '—'
        line = f"{MODE_NAMES.get(mode, str(mode))}：{counter['right']} / {total} 正确，{rate}"
        if counter['skip']:
            line += f"，跳过 {counter['skip']}"
        lines.append(line)
    ai_count = sum(entry.get('source') == 'ai' for entry in records)
    lines.append(f'AI 兜底判分记录：{ai_count}')
    failures = [entry for entry in records if entry.get('right') is False and not entry.get('skipped')]
    lines.extend(['', '错误判分记录：'])
    if not failures:
        lines.append('没有错题记录。')
    for entry in failures:
        stem = entry.get('stem') or {}
        lines.extend(['', f"第 {entry.get('position', '—')} 题：{MODE_NAMES.get(entry.get('mode'), entry.get('mode'))}",
                      str(stem.get('content') or ''), str(stem.get('remark') or ''),
                      '提交答案：' + readable_answer(entry.get('answer'), entry.get('options')),
                      '服务器标准答案：' + readable_answer(entry.get('corrects'), entry.get('options'))])
    skipped = [entry for entry in records if entry.get('skipped')]
    if skipped:
        lines.extend(['', '跳过题目记录：'])
        for entry in skipped:
            stem = entry.get('stem') or {}
            lines.extend([f"第 {entry.get('position', '—')} 题：{MODE_NAMES.get(entry.get('mode'), entry.get('mode'))}",
                          str(stem.get('content') or ''), str(stem.get('remark') or '')])
            if entry.get('skip_reason') == 'ambiguous_mean':
                lines.append('原因：多个选项符合词典释义，题干没有区分信息。')
    return '\n'.join(lines)
