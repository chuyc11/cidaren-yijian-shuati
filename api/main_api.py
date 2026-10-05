# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
import json
import random
import time
from functools import wraps
from urllib.parse import quote

import api.request_header as requests
from decryptencrypt.debase64 import debase64, JV_TWO, JV_THREE
from decryptencrypt.encrypt_md5 import encrypt_md5
from log.log import Log, get_file_logger
from publicInfo.publicInfo import PublicInfo
from util.answer_lib import add_answer, add_word_answer
from util.basic_util import create_timestamp
from util.word_cache import WordCache
from util.word_prefetch import WordPrefetch
from util.submission_state import grading_key

# create logger
api = Log('main_api')

basic_url = 'https://app.vocabgo.com/student/api/Student/'

file_logger = get_file_logger('_main_api')


class SecurityVerifyError(Exception):
    """服务端风控: 11003 需安全验证(要求用户在 App/微信端完成验证), 重试无意义, 应立即停止并提示"""


class WordSelectionRequiredError(Exception):
    """任务需要先选词，不能把该状态当作已完成。"""


class TaskUnavailableError(Exception):
    """服务端明确判定任务已截止，自动重试无法继续。"""


class UnsupportedResponseEncodingError(RuntimeError):
    """The server may have accepted a mutation; do not repeat it to decode a reply."""


def _response_data(body):
    data = body.get('data')
    if isinstance(data, dict):
        return data
    if not data:
        raise RuntimeError(f"服务端未返回任务数据：{body.get('msg', '')}")
    return debase64(data, body.get('jv', '0'))


def _update_exam(public_info, response):
    handle_response(response)
    body = response.json()
    message = (body.get('msg') or '').rstrip('！!。 ')
    if message == '需要选词':
        public_info.exam = 'needs_selection'
        raise WordSelectionRequiredError('任务需要先选择单词')
    if message == '任务已完成':
        public_info.exam = 'complete'
        public_info.topic_code = ''
        return
    exam = _response_data(body)
    if 'topic_code' not in exam or 'topic_mode' not in exam:
        raise RuntimeError('服务端返回的题目缺少 topic_code 或 topic_mode')
    public_info.exam = exam
    public_info.topic_code = exam['topic_code']
    if exam.get('task_id') and int(exam['task_id']) > 0:
        public_info.task_id = exam['task_id']


# response is 200
def handle_response(response):
    """
    检查response
    :param response:
    :return:
    """
    response_json = response.json()
    code = response_json['code']
    # error_view.showUI()
    if code == 11003:
        api.logger.error(f"需安全验证: {response.text}")
        raise SecurityVerifyError("服务端需安全验证，请打开词达人 App/微信完成安全验证后重试")
    if code == 20006:
        raise TaskUnavailableError(response_json.get('msg') or '任务已截止')
    if code == 1:
        # 获取成功
        api.logger.info(f"请求成功{response.text}")
    # complete exam
    elif (response_json.get('msg') or '').rstrip('！!。 ') in ('任务已完成', '需要选词'):
        pass
    elif (code == 20001 and response_json.get('data')) or code == 20004:
        pass
    elif code == 0 and response_json['msg'] == '加载单词卡片失败，请重新加载':
        api.logger.error("查找不到单词(第三方库转原型失败),请手动答题")
        raise Exception("查找不到单词,请手动答题")
    else:
        api.logger.error(f"请求有问题{response.text}")
        raise RuntimeError(f"请求失败（code={code}）：{response_json.get('msg', '未知错误')}")


def check_jv_and_retry_post(request_func, url, **kwargs):
    """Send once: decoding a response must never replay a submitted answer."""
    response = request_func(url, **kwargs)
    try:
        body = response.json()
        jv = str(body.get('jv', ''))
    except (ValueError, TypeError, AttributeError):
        return response
    if (not body.get('data') or isinstance(body['data'], dict) or not jv or jv == '0'
            or jv in JV_TWO or jv in JV_THREE):
        return response
    raise UnsupportedResponseEncodingError('服务端返回未知数据编码；提交请求未重复发送，请更新脚本后恢复任务')


def check_jv_and_retry_get(request_func, url, **kwargs):
    """
    检查get请求的jv
    :param request_func:
    :param url:
    :param kwargs:
    :return:
    """
    for _ in range(5):
        response = request_func(url, **kwargs)
        try:
            response_json = response.json()
            jv = str(response_json.get('jv', ''))
            if not jv or jv == '0' or jv in JV_TWO or jv in JV_THREE:
                return response
        except Exception:
            return response
        time.sleep(random.uniform(2, 3))
    api.logger.error("连续5次请求jv均不在已知范围内")
    raise Exception("jv解码失败")


def is_close() -> bool:
    url = 'https://gitee.com/hhhuuuu/cdr/access/add_access_log'
    rsp = requests.requests.get(url)
    if rsp.status_code == 200:
        return True
    else:
        return False


def skip_exam(public_info):
    """
    跳过过不了的题目
    :return:
    """
    api.logger.info("无法完成，跳过题目")
    url = f'{PublicInfo.task_type}/SkipAnswer'
    params = {'it_font_size': 42,
              'it_img_w': 804,
              'opt_font_c': '#000000',
              'opt_font_size': 37,
              'opt_img_w': 684,
              'time_spent': 20000,
              'timestamp': create_timestamp(),
              'topic_code': public_info.topic_code,
              'version': '2.6.2.24031302'}
    sign = encrypt_md5("&".join([f'{key}={value}' for key, value in params.items()]) + 'ajfajfamsnfaflfasakljdlalkflak')
    params.update({'sign': sign})
    previous_exam = public_info.exam
    rsp = check_jv_and_retry_post(requests.rqs2_session.post, basic_url + url, data=json.dumps(params))
    _update_exam(public_info, rsp)
    public_info.skip_count += 1
    report = getattr(public_info, '_task_report', None)
    if report is not None:
        try:
            report.record_skip(previous_exam)
        except Exception as exc:
            api.logger.warning(f'跳过成功，但报告记录失败：{type(exc).__name__}')


# 勾选所有单词 bug
def select_all_word(word_info, task_id: int, ) -> None:
    api.logger.info("勾选全部单词并提交")
    timestamp = create_timestamp()
    url = f'{PublicInfo.task_type}/SubmitChoseWord'
    # 取消键值对的空格(紧密排版)
    word_map = json.dumps(word_info, separators=(',', ':'))
    source_str = f'chose_err_item=2&task_id={task_id}&timestamp={timestamp}&version=2.6.1.231204&word_map={word_map}ajfajfamsnfaflfasakljdlalkflak'
    sign = encrypt_md5(source_str)
    data = {"task_id": task_id, "word_map": word_info, "chose_err_item": 2,
            "timestamp": timestamp, "version": "2.6.1.231204", "sign": sign,
            "app_type": 1}
    rsp = check_jv_and_retry_post(requests.rqs3_session.post, basic_url + url, data=json.dumps(data))
    # 检查请求是否成功
    handle_response(rsp)


# class task
# 获取所有班级任务
def get_class_task(public_info, page_count: int):
    """
    :param public_info:
    :param page_count:  第几页的数据
    :return:
    """
    api.logger.info(f'获取第{page_count}页任务')
    url = 'ClassTask/PageTask'
    timestamp = create_timestamp()
    sign = f"page_count={page_count}&page_size=10&search_type=0&timestamp={timestamp}&version=2.6.1.240122ajfajfamsnfaflfasakljdlalkflak"
    data = {
        'search_type': '0',
        'page_count': page_count,
        'page_size': 10,
        'timestamp': timestamp,
        "version": "2.6.1.231204",
        "sign": encrypt_md5(sign),
        "app_type": 1
    }
    # "task_type": 2 是班级测试任务 1 是班级自学任务
    # PageTask is a read-only query despite using POST. Retry only this query,
    # not answer verification or save operations, when the response is truncated.
    for attempt in range(3):
        try:
            task = requests.class_task_request.post(url=basic_url + url, json=data)
            handle_response(task)
            task_dict = task.json()
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError):
            if attempt == 2:
                raise
            api.logger.warning(f'任务列表读取中断，重试第 {attempt + 1} 次')
            time.sleep(attempt + 1)
    # sava public_info
    public_info.class_task.append(task_dict['data'])
    # number of task
    public_info.task_total_count = task_dict['data']['total']


# start

def get_class_task_info(public_info):
    """按发布编号初始化班级任务，获取服务器分配的任务编号和本次词表。"""
    if not public_info.release_id:
        raise RuntimeError('班级任务缺少 release_id')
    params = {
        'task_id': public_info.task_id or -1,
        'release_id': public_info.release_id,
        'course_id': public_info.course_id,
        'timestamp': create_timestamp(),
        'version': '2.6.1.240122',
        'app_type': 1,
    }
    rsp = check_jv_and_retry_get(requests.class_task_request.get, basic_url + 'ClassTask/Info', params=params)
    handle_response(rsp)
    body = rsp.json()
    data = _response_data(body)
    task_id = data.get('task_id')
    if not task_id or int(task_id) <= 0:
        raise RuntimeError('班级任务详情未返回有效的 task_id')
    public_info.task_id = task_id
    public_info.get_word_list_result = dict(body, data=data)
    return data


def get_exam(public_info):
    api.logger.info("获取第一题")
    url = f'{PublicInfo.task_type}/StartAnswer'
    params = {'task_id': public_info.task_id or -1, 'task_type': PublicInfo.task_type_int,
              'opt_img_w': '684',
              'opt_font_size': '37', 'opt_font_c': '%23000000', 'it_img_w': '804', 'it_font_size': '42',
              'timestamp': create_timestamp(), 'version': '2.6.1.240122', 'app_type': '1'}
    if PublicInfo.task_type_int == 2:
        params.update({'release_id': public_info.release_id})
    else:
        params.update({'course_id': public_info.course_id})
    rsp = check_jv_and_retry_get(requests.class_task_request.get, basic_url + url, params=params)
    # {'task_id': 143960071, 'task_type': 1, 'topic_mode': 0, 'stem': {'content': 'trade', 'remark': None, 'ph_us_url': '/Resource/unitAudio_US/JJ_3_1_0/trade.mp3', 'ph_en_url': '/Resource/unitAudio_EN/JJ_3_1_0/trade.mp3', 'au_addr': None}, 'options': [{'content': 'verb 互相交换', 'remark': None, 'answer': None, 'answer_tag': 0, 'check_code': None, 'sub_options': None, 'ph_info': {'ph_en': 'treɪd', 'ph_en_url': '/Resource/unitAudio_EN/JJ_3_1_0/trade.mp3', 'ph_us': 'treɪd', 'ph_us_url': '/Resource/unitAudio_US/JJ_3_1_0/trade.mp3', 'group': '0'}}, {'content': 'noun 职业；手艺', 'remark': None, 'answer': None, 'answer_tag': 1, 'check_code': None, 'sub_options': None, 'ph_info': {'ph_en': 'treɪd', 'ph_en_url': '/Resource/unitAudio_EN/JJ_3_1_0/trade.mp3', 'ph_us': 'treɪd', 'ph_us_url': '/Resource/unitAudio_US/JJ_3_1_0/trade.mp3', 'group': '0'}}], 'sound_mark': 'treɪd', 'ph_en': 'treɪd', 'ph_us': 'treɪd', 'answer_num': 1, 'chance_num': 1, 'topic_done_num': 1, 'topic_total': 127, 'w_lens': [], 'w_len': 0, 'w_tip': '', 'tips': '', 'word_type': 1, 'enable_i': 2, 'enable_i_i': 2, 'enable_i_o': 2, 'topic_code': 'lFiAe5drW46DfnrEaJVol2hbXlrWqpianVhlZmGZlmKPvo+UkWOTZWdiYm9ubJuXamCVaGpnaGSUj2STZGhob2JybGuWnG5tjZRlZWuVcmxmYW9pZZSSZ2mebmZtcWRsZWiZaWdsZGaW', 'answer_state': 1, 'show_card_type': 1}
    # 检查请求结果
    _update_exam(public_info, rsp)
    api.logger.info("写入成功")


# next exam
def next_exam(public_info):
    # 获取每一题提交的用时，500为一秒
    min_time = public_info.spend_min_time * 500
    max_time = public_info.spend_max_time * 500
    api.logger.info("获取下一题")
    url = f'{PublicInfo.task_type}/SubmitAnswerAndSave'
    params = {'it_font_size': 42,
              'it_img_w': 804,
              'opt_font_c': '#000000',
              'opt_font_size': 37,
              'opt_img_w': 684,
              'time_spent': random.randint(min_time, max_time),
              'timestamp': create_timestamp(),
              'topic_code': public_info.topic_code,
              'version': '2.6.2.24031302'}
    sign = encrypt_md5(
        "&".join([f'{key}={value}' for key, value in params.items()]) + 'ajfajfamsnfaflfasakljdlalkflak')  # 加密
    params.update({'sign': sign})
    data = check_jv_and_retry_post(requests.rqs2_session.post, basic_url + url, data=json.dumps(params))
    # 检查请求是否成功
    _update_exam(public_info, data)


def check_is_self_built(func):
    @wraps(func)
    def is_self_built(public_info, word):
        if public_info.is_self_built:
            # Match actual word metadata; book order need not match released order.
            entries = [entry for entry in public_info.get_book_words_data
                       if entry.get('word', '').lower() == word.lower()]
            if not entries:
                raise ValueError(f'当前任务词表找不到 {word} 的单元')
            public_info.now_unit = entries[0]['list_id']
        return func(public_info, word)

    return is_self_built


def _dictionary_cache(public_info):
    cache = getattr(public_info, '_word_cache', None)
    if cache is None:
        cache = public_info._word_cache = WordCache()
    return cache


def _fetch_word_info(course, unit, word, session):
    url = f'Course/StudyWordInfo?course_id={course}&list_id={unit}&word={quote(word, safe="")}&timestamp={create_timestamp()}&version=2.6.1.231204&app_type=1'
    response = check_jv_and_retry_get(session.get, basic_url + url)
    handle_response(response)
    return _response_data(response.json())


def begin_word_prefetch(public_info):
    """Overlap independent GET reads with cards; all answer submissions stay serial."""
    if not getattr(public_info, 'fast_mode', False):
        return None
    selected = {word.strip().lower() for word in public_info.word_list}
    entries = [(public_info.course_id, row['list_id'], row['word'])
               for row in public_info.get_book_words_data
               if row.get('list_id') and row.get('word', '').strip().lower() in selected]
    if len(entries) < 8:
        return None  # Small tasks do not benefit from starting background workers.
    # Capture login headers once; every thread owns and reuses its own session.
    session_headers = dict(requests.rqs_session.headers)

    def session_factory():
        session = requests.requests.Session()
        session.headers.update(session_headers)
        requests.mount_retries(session)
        return session

    pool = WordPrefetch(entries, _dictionary_cache(public_info), _fetch_word_info, session_factory,
                        max_workers=2, fatal_errors=(SecurityVerifyError, TaskUnavailableError))
    public_info._word_prefetch = pool
    public_info._word_prefetch_started = True
    return pool


# 查询单词
@check_is_self_built
def query_word(public_info, word):
    cache = _dictionary_cache(public_info)
    key = (str(public_info.course_id), str(public_info.now_unit), word.strip().lower())
    cached = cache.get(key)
    prefetch = getattr(public_info, '_word_prefetch', None)
    if prefetch is not None:
        prefetch.raise_if_failed()
        if cached is None:
            cached = prefetch.wait(key)
    if cached is not None:
        public_info.word_query_result = cached
        api.logger.info(f'释义缓存命中：{word}')
        return
    if not getattr(public_info, 'fast_mode', False):
        time.sleep(random.randint(0, 2))
    api.logger.info(f"查询单词{word}")
    public_info.word_query_result = _fetch_word_info(public_info.course_id, public_info.now_unit, word, requests.rqs_session)
    if public_info.word_query_result.get('means') or public_info.word_query_result.get('options'):
        cache.put(key, public_info.word_query_result)
    api.logger.info("查询单词成功")


# submit word
def submit_result(public_info, option):
    api.logger.info("开始提交答案")
    timestamp = create_timestamp()
    topic_code = public_info.topic_code
    sign = encrypt_md5(
        f"answer={option}&timestamp={timestamp}&topic_code={topic_code}&version=2.6.1.231204ajfajfamsnfaflfasakljdlalkflak")
    url = f"{PublicInfo.task_type}/VerifyAnswer"
    data = {"answer": option,
            "topic_code": topic_code,
            "timestamp": timestamp, "version": "2.6.1.231204", "sign": sign,
            "app_type": 1}
    rsp = check_jv_and_retry_post(requests.rqs2_session.post, basic_url + url, data=json.dumps(data))
    # check request is success
    handle_response(rsp)
    result = _response_data(rsp.json())
    if not isinstance(result.get('topic_code'), str) or not result['topic_code']:
        raise UnsupportedResponseEncodingError('判分响应缺少下一步题目码，已停止并保留进度')
    answer_result = result.get('answer_result')
    new_event = True
    if getattr(PublicInfo, 'task_type', None) == 'ClassTask' and answer_result in (1, 2):
        event_id = grading_key(public_info, option)
        known = getattr(public_info, '_graded_event_ids', None)
        if known is None:
            known = public_info._graded_event_ids = set()
        new_event = event_id not in known
        known.add(event_id)
        result = dict(result, _event_id=event_id)
    api.logger.info(f"答题判分: answer_result={answer_result} answer_corrects={result.get('answer_corrects')}")
    report = getattr(public_info, '_task_report', None)
    if report is not None:
        try:
            report.record(public_info.exam, option, result, getattr(public_info, '_answer_source', 'unknown'))
        except Exception as exc:
            api.logger.warning(f'判分成功，但报告记录失败：{type(exc).__name__}')
    # 对错计数(进度条右侧统计)
    if answer_result == 1 and new_event:
        public_info.right_count += 1
    elif answer_result == 2 and new_event:
        public_info.wrong_count += 1
    # 记录标准答案到本地答案库(word_zh -> answer_corrects, 仅短语类题型)
    exam = public_info.exam
    if isinstance(exam, dict):
        mode = exam.get('topic_mode')
        stem = exam.get('stem')
        word_zh = stem.get('remark') if isinstance(stem, dict) else None
        corrects = result.get('answer_corrects')
        if getattr(public_info, '_self_learn_lib', True):
            if mode == 32 and word_zh and corrects:
                # mode 32: answer_corrects 是完整短语, 入短语库
                add_answer(word_zh, corrects)
            elif mode == 73 and word_zh and corrects:
                # mode 73: answer_corrects 是空位单词(非完整短语), 入单词库防污染短语库
                add_word_answer(word_zh, corrects)
            elif mode == 42 and word_zh and corrects:
                # mode 42: answer_corrects 是选项下标数组, 通过 options 取正确答案单词入库
                options = exam.get('options') or []
                words = []
                for idx in corrects:
                    if isinstance(idx, int) and 0 <= idx < len(options):
                        content = options[idx].get('content') if isinstance(options[idx], dict) else None
                        if content:
                            words.append(content)
                if words:
                    add_word_answer(word_zh, words)
    api.logger.info("提取下一题的请求参数")
    # next exam topic_code
    public_info.topic_code = result['topic_code']


def get_task_score(public_info):
    """
    获取任务分数
    """
    try:
        # 根据任务类型获取分数
        if hasattr(public_info, 'release_id') and public_info.release_id:
            # 班级任务
            url = 'https://app.vocabgo.com/student/api/Student/ClassTask/Info'
            params = {
                'task_id': public_info.task_id,
                'release_id': public_info.release_id,
                'timestamp': int(time.time() * 1000),
                'version': '2.6.1.240122',
                'app_type': 1
            }
        else:
            # 自学任务
            url = 'https://app.vocabgo.com/student/api/Student/StudyTask/Info'
            params = {
                'task_id': public_info.task_id,
                'course_id': public_info.course_id,
                'timestamp': int(time.time() * 1000),
                'version': '2.6.1.240122',
                'app_type': 1
            }

        response = requests.class_task_request.get(url, params=params)
        if response.status_code == 200 and response.json().get('code') == 1:
            data = _response_data(response.json())
            # 尝试从不同字段获取分数
            score = next((data[key] for key in ('score', 'task_score', 'grade') if data.get(key) is not None), None)
            if score is not None:
                return float(score)
        return None
    except Exception as e:
        api.logger.error(f"获取任务分数失败: {e}")
        return None


if __name__ == '__main__':
    pass
