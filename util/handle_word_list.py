# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
from decryptencrypt.debase64 import debase64
import json
import os


def get_word_data(public_info):
    result = public_info.get_word_list_result
    data = result.get('data', result)
    if not isinstance(data, dict):
        data = debase64(data, result.get('jv', '0'))
    return data


def get_task_word_map(public_info):
    """只提交服务器给当前任务返回的词表，按实际课程和单元分组。"""
    word_map = {}
    for item in get_word_data(public_info).get('word_list', []):
        course = item.get('course_id') or public_info.course_id
        unit = item.get('list_id') or public_info.now_unit
        if not course or not unit or not item.get('word'):
            raise RuntimeError('任务词表缺少课程、单元或单词，无法选词')
        word_map.setdefault(f'{course}:{unit}', []).append(item['word'])
    if not word_map:
        raise RuntimeError('任务词表为空，无法选词')
    return word_map


def handle_word_result(public_info) -> None:
    words = get_word_data(public_info).get('word_list', [])
    word_list = [word['word'] for word in words]
    word_dict = {word['word_zh']: word['word'] for word in words if word.get('word_zh')}
    # 当前单元词表覆盖 word_list(判词依赖当前单元)
    public_info.word_list = word_list
    # word_dict 跨单元合并(全局词表池: mode 73 前缀单词可能在其他单元词表)
    if not isinstance(getattr(public_info, 'word_dict', None), dict):
        public_info.word_dict = {}
    public_info.word_dict.update(word_dict)
    # 持久化(跨进程累积: 单任务/不同刷题顺序下全局池完整); 词表池自学习关闭时不写入
    if getattr(public_info, '_self_learn_pool', True):
        try:
            with open(os.path.join(public_info.path, "config", "word_pool.json"), 'w', encoding='utf-8') as f:
                json.dump(public_info.word_dict, f, ensure_ascii=False)
        except Exception:
            pass
