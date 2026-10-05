# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
import json
import os
import re
import time

import api.request_header as requests
from api.main_api import SecurityVerifyError
from log.log import Log, get_file_logger
from util.basic_util import create_timestamp

# init log
basic_api = Log("basic_api")
basic_url = 'https://app.vocabgo.com/student/api/Student/'

file_log = get_file_logger("_basic_api")


def handle_response(response):
    """
    判断请求是否成功
    response is 200
    """
    if response.json()['code'] == 1:
        basic_api.logger.info(f"请求成功{response.text}")
    elif response.json()['code'] == 11003:
        basic_api.logger.error(f"需安全验证: {response.text}")
        raise SecurityVerifyError("服务端需安全验证，请打开词达人 App/微信完成安全验证后重试")
    else:
        basic_api.logger.error(f"请求有问题{response.text}退出程序")
        raise Exception("请求有问题，中止程序")


def use_api_get_prototype(word: str) -> str:
    """
    利用api获取单词原型
    :param word: 目标单词
    :return: 原型
    """
    basic_api.logger.info(f"单词{word}走api转原型")
    url = f'https://app.vocabgo.com/student/api/Student/Course/SearchWord?word={word}&timestamp=1710396115786&version=2.6.2.24031302&app_type=1'
    prototype = requests.rqs_session.get(url=url)
    prototype.encoding = 'utf-8'  # 设置编码
    handle_response(prototype)

    # 提取并解码数据
    meaning_str = prototype.json()['data']['word_mean']['meaning']
    # 处理转义字符
    decoded_meaning = bytes(meaning_str, 'utf-8').decode('unicode_escape')
    # 正则匹配
    result = re.findall(r'<span>(.+?)</span>', decoded_meaning)
    return None if not result else result[0]


def get_select_course(public_info):
    url = 'Main?timestamp=1704182548197&version=2.6.1.231204&app_type=1'
    rsp = requests.rqs_session.get(basic_url + url)
    # check request is success
    handle_response(rsp)
    # course id
    public_info.course_id = rsp.json()['data']['user_info']['course_id']


def get_all_unit(public_info):
    """
    获取课程所有单元
    """
    timestamp = create_timestamp()
    url = f'StudyTask/List?course_id={public_info.course_id}&timestamp={timestamp}&version=2.6.1.231204&app_type=1'
    user_data = requests.rqs_session.get(basic_url + url)
    # 检查请求是否成功
    handle_response(user_data)
    public_info.all_unit = user_data.json()['data']


# 获取单元所有单词
def get_unit_words(public_info):
    timestamp = create_timestamp()
    url_params = {'task_id': public_info.task_id or -1, "course_id": public_info.course_id, 'timestamp': timestamp,
                  'version': '2.6.1.240305', 'app_type': '1'}
    if public_info.is_self_built:
        # 自建任务
        url_params.update({'release_id': public_info.release_id})
    else:
        # 测试任务
        url_params.update({'list_id': public_info.now_unit})
    word_data = requests.rqs_session.get(basic_url + 'StudyTask/Info', params=url_params)
    # 检查请求是否成功
    handle_response(word_data)
    word_data_json = word_data.json()
    basic_api.logger.info(word_data_json)
    public_info.get_word_list_result = word_data_json


def get_book_all_words(public_info):
    basic_api.logger.info('获取该本书的所有单词')
    url = f'https://resource.vocabgo.com/Resource/CoursePage/{public_info.course_id}.json'
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f'{public_info.course_id}.json')
    last_err = None
    for attempt in range(1, 4):
        try:
            rsp = requests.rsq_self_built.get(url, timeout=30)
            data = rsp.json()
            # all the words in the book
            public_info.get_book_words_data = data
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
                basic_api.logger.info(f'词书已缓存: {cache_file}')
            except Exception as e:
                basic_api.logger.warning(f'词书缓存写入失败: {e}')
            return
        except Exception as e:
            last_err = e
            basic_api.logger.warning(f'获取词书失败（第{attempt}次）: {e}，5秒后重试')
            time.sleep(5)
    if os.path.exists(cache_file):
        basic_api.logger.warning(f'网络获取词书失败，改用本地缓存: {cache_file}')
        with open(cache_file, encoding='utf-8') as f:
            public_info.get_book_words_data = json.load(f)
        return
    raise last_err
