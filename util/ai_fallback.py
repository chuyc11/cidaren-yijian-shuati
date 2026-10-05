# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
import json
import os
import re

import requests

from log.log import Log

ai_logger = Log("ai_fallback")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_ROOT, 'config', 'ai_config.json')

MODE_DESC = {
    11: '词形变化选义（英译汉选择）',
    15: '英译汉选择', 16: '英译汉选择', 21: '英译汉选择', 22: '英译汉选择',
    17: '汉译英选择', 18: '汉译英选择',
    32: '看句选义（选择短语/句子释义）',
    41: '选词填空', 42: '选词填空', 43: '选词填空', 44: '选词填空',
    51: '补全单词', 52: '补全单词', 53: '补全单词', 54: '补全单词',
    73: '看义写词（拼写）',
}
CHOICE_MODES = {11, 15, 16, 17, 18, 21, 22, 41, 42, 43, 44}
SPELLING_MODES = {51, 52, 53, 54, 73}
PHRASE_MODES = {32}


def _choice_candidates(exam):
    candidates = []
    for index, option in enumerate(exam.get('options') or []):
        tag = option.get('answer_tag')
        tag = index if tag is None else tag
        children = option.get('sub_options') or []
        if children:
            for child_index, child in enumerate(children):
                child_tag = child.get('answer_tag')
                child_tag = child_index if child_tag is None else child_tag
                candidates.append((str(tag) + str(child_tag), child.get('content', '')))
        else:
            candidates.append((tag + '0' if isinstance(tag, str) else tag, option.get('content', '')))
    return candidates


def load_config():
    """读取 config/ai_config.json；未配置或格式不对时返回 None（自动跳过 AI 兜底）"""
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg = json.load(f)
        if cfg.get('base_url') and cfg.get('api_key') and cfg.get('model'):
            return cfg
        ai_logger.logger.warning('ai_config.json 缺少 base_url/api_key/model 字段，跳过 AI 兜底')
    except Exception as e:
        ai_logger.logger.warning(f'ai_config.json 读取失败: {e}')
    return None


def _build_prompt(exam, mode):
    stem = exam.get('stem') or {}
    options = exam.get('options') or []
    lines = [f"题型：{MODE_DESC.get(mode, f'编号{mode}')}"]
    lines.append(f"题干：{stem.get('content', '')}")
    if stem.get('remark'):
        lines.append(f"题干中文：{stem['remark']}")
    if mode in CHOICE_MODES and options:
        lines.append('选项：')
        candidates = _choice_candidates(exam)
        for i, (_, content) in enumerate(candidates, 1):
            lines.append(f'{i}. {content}')
        lines.append(f'请只输出正确选项的编号数字（1-{len(candidates)}），不要输出其他内容。')
    elif mode == 32:
        lines.append('请只输出完整英文短语，按题干中文翻译，不要输出编号或解释。')
    elif mode == 73:
        tips = re.findall(r'\{([A-Za-z]+)\}', stem.get('content', '')) or exam.get('tips', '')
        lines.append(f"首字母提示：{tips}；空位长度：{exam.get('w_lens', [])}")
        lines.append('请只输出按空位顺序排列的英文单词 JSON 数组，例如 ["first", "second"]。')
    else:
        lines.append(f"首字母提示：{exam.get('w_tip', '')}；单词长度：{exam.get('w_lens', [])}")
        lines.append('请只输出一个英文单词作为答案，不要输出其他内容。')
    return '\n'.join(lines)


def _parse_choice(text, n_options):
    value = (text or '').strip()
    if not re.fullmatch(r'\d+', value):
        return None
    idx = int(value)
    return idx - 1 if 1 <= idx <= n_options else None


def _parse_word(text):
    m = re.fullmatch(r'[A-Za-z][A-Za-z\-]*', (text or '').strip().strip('"\''))
    return m.group(0).lower() if m else None


def _parse_answer(text, exam, mode):
    if mode in CHOICE_MODES:
        candidates = _choice_candidates(exam)
        index = _parse_choice(text, len(candidates))
        return candidates[index][0] if index is not None else None
    if mode == 32:
        from types import SimpleNamespace
        from answer_questions.answer_questions import _build_phrase_answer
        phrase = (text or '').strip().strip('"\'')
        if not re.fullmatch(r'[A-Za-z][A-Za-z\s\-]*', phrase):
            return None
        return _build_phrase_answer(SimpleNamespace(exam=exam), phrase)
    if mode == 73:
        try:
            words = json.loads(text)
            lengths = exam.get('w_lens') or []
            tips = re.findall(r'\{([A-Za-z]+)\}', (exam.get('stem') or {}).get('content', '')) or exam.get('tips') or []
            if isinstance(tips, str):
                tips = tips.split(',') if ',' in tips else tips.split()
            if not isinstance(words, list) or len(words) != len(lengths):
                return None
            parsed = [_parse_word(word) if isinstance(word, str) else None for word in words]
            if any(not word or len(word) != int(lengths[i]) or
                   (i < len(tips) and not word.startswith(tips[i].lower())) for i, word in enumerate(parsed)):
                return None
            return json.dumps(parsed, ensure_ascii=False, separators=(',', ':'))
        except (ValueError, TypeError):
            return None
    if mode in SPELLING_MODES:
        word = _parse_word(text)
        lengths = exam.get('w_lens') or []
        tip = str(exam.get('w_tip') or '').strip().lower()
        if word and len(lengths) == 1 and len(word) == int(lengths[0]) and word.startswith(tip):
            return word
    return None


def ai_answer(exam, mode):
    """
    LLM 兜底答题：本地词表匹配失败（option 为 None）时调用。
    返回服务器的 answer_tag（缺省为 0 起的索引），拼写题先校验格式、长度和前缀。
    未配置或调用失败返回 None（由调用方继续走跳题逻辑）。
    """
    if mode not in CHOICE_MODES | SPELLING_MODES | PHRASE_MODES:
        return None
    cfg = load_config()
    if cfg is None:
        return None
    options = exam.get('options') or []
    prompt = _build_prompt(exam, mode)
    try:
        rsp = requests.post(
            cfg['base_url'].rstrip('/') + '/chat/completions',
            headers={'Authorization': f"Bearer {cfg['api_key']}"},
            json={
                'model': cfg['model'],
                'temperature': 0,
                'messages': [
                    {'role': 'system', 'content': '你是英语词汇题答题助手，只输出答案本身，不要解释。'},
                    {'role': 'user', 'content': prompt},
                ],
            },
            timeout=int(cfg.get('timeout', 30)),
        )
        rsp.raise_for_status()
        content = rsp.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        ai_logger.logger.warning(f'AI 兜底请求失败: {type(e).__name__}')
        return None
    ai_logger.logger.info(f'AI 兜底原始回复: {content}')
    return _parse_answer(content, exam, mode)
