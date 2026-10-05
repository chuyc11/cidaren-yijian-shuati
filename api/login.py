# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
import json

import api.request_header as requests
import brotli
from decryptencrypt.encrypt_md5 import encrypt_md5
from log.log import Log
from util.basic_util import create_timestamp

# 基础url
basic_url = 'https://app.vocabgo.com/student/api/'
# 初始化log
login = Log("login")


def verify_token(token):
    requests.set_token(token)
    timestamp = create_timestamp()
    url = f'Student/Main?timestamp={timestamp}&version=2.6.1.231204&app_type=1'
    try:
        response = requests.rqs_session.get(basic_url + url)
        login.logger.info(f"压缩编码格式：{response.headers.get('Content-Encoding')}")
        response.raise_for_status()  # 检查HTTP状态码
        result = response.json()

        # 判断是否过期 code = 1 为未过期
        if result['code'] != 1:
            code, message = result['code'], str(result.get('msg') or '')
            login.logger.error(f'登录失败（code={code}）：{message}')
            if code == 11003:
                return 8
            if any(value in message for value in ('过期', '未登录', '登录失效')):
                return 1
            return 9
        else:
            return result
    except requests.exceptions.HTTPError as e:
        login.logger.error(f"【HTTP请求错误】: {e}")
        return 2
    except requests.exceptions.Timeout as e:
        login.logger.error(f"【连接超时，请检查网络连接】: {e}")
        return 3
    except json.JSONDecodeError as e:
        login.logger.error(f"【响应内容不是有效的JSON格式】: {e}")
        login.logger.error(f"响应内容: {response.text}")
        return 4
    except requests.exceptions.SSLError as e:
        login.logger.error(f"【SSL错误】：{e}")
        return 5
    except requests.exceptions.ProxyError as e:
        login.logger.error(f"【代理服务器异常】：{e}")
        return 6
    except requests.exceptions.ConnectionError as e:
        login.logger.error(f"【连接错误】: {e}")
        return 7
