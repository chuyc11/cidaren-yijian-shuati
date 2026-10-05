# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
"""Stable local identities, excluding server capability codes and credentials."""
import hashlib
import json


def _options(options):
    return [{'content': item.get('content'), 'tag': index if item.get('answer_tag') is None else item['answer_tag'],
             'children': _options(item.get('sub_options') or [])} for index, item in enumerate(options or [])]


def question_key(info):
    exam = info.exam
    stem = exam.get('stem') or {}
    value = {'scope': [str(getattr(info, name, '')) for name in ('course_id', 'release_id', 'task_id')],
             'position': exam.get('topic_done_num'), 'total': exam.get('topic_total'), 'mode': exam.get('topic_mode'),
             'stem': {name: stem.get(name) for name in ('content', 'remark')},
             'options': _options(exam.get('options')), 'tip': exam.get('w_tip'), 'lengths': exam.get('w_lens')}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def grading_key(info, answer):
    value = [question_key(info), answer]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
