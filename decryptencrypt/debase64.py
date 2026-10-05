# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
import base64
import json
import re
from log.log import Log, get_file_logger

bs64 = Log("base64")
file_logger = get_file_logger('_base64')

JV_TWO = {
    '2_1254':  [0, 1, 2, 4, 5, 36, 47, 48, 59, 96, 107],
    '2_9214':  [0, 1, 2, 4, 5, 6, 7, 48, 49, 66, 149, 150, 284, 374, 375],
    '2_10232': [0, 1, 2, 5, 6, 7, 8, 46, 65, 66, 199, 270, 328, 329],
    '2_10234': [0, 1, 2, 4, 5, 6, 7, 46, 65, 66, 198, 270, 328, 329],
}

JV_THREE = {
    '3_1021': {
        "uc": [{"s": 0, "n": 1}, {"s": 1, "n": 2}, {"s": 33, "n": 1}, {"s": 57, "n": 1}, {"s": 111, "n": 1}],
        "avg": 5, "loc": [1, 3, 2, 0, 4]
    },
    '3_2265': {
        "uc": [{"s": 0, "n": 2}, {"s": 1, "n": 3}, {"s": 33, "n": 1}, {"s": 57, "n": 1}, {"s": 121, "n": 1}],
        "avg": 5, "loc": [3, 1, 0, 4, 2]
    },
    '3_2277': {
        "uc": [{"s": 0, "n": 3}, {"s": 1, "n": 3}, {"s": 32, "n": 2}, {"s": 50, "n": 1}, {"s": 110, "n": 1}],
        "avg": 5, "loc": [3, 1, 0, 4, 2]
    },
}

DEFAULT_JV_TWO = JV_TWO['2_9214']


def strip_noise(d: str, rules) -> str:
    """
    去除混淆
    :param d: 待去除的乱码数据
    :param rules: 乱码规则
    :return:
    """
    if rules and isinstance(rules[0], int):
        chars = list(d)
        for i in sorted(rules, reverse=True):
            if 0 <= i < len(chars):
                del chars[i]
        return ''.join(chars)
    for r in rules:
        s, n = r["s"], r["n"]
        d = (d[:s] if s else "") + d[s + n:]
    return d


def debase64(data: dict or str, jv: str = 0):
    """
    base64解码
    :param data: 待解码的数据
    :param jv: 乱码版本标识，默认为0
    :return:
    """
    if type(data) is dict:
        data = data["data"]

    jv = str(jv or '')
    file_logger.info(f"开始解码jv:{jv},{data}")
    try:
        bs64_str = base64.b64decode(data.encode("utf-8")).decode("utf-8")
    except:
        if jv.startswith("2_") and jv in JV_TWO:
            clean_data = strip_noise(data, JV_TWO[jv])
        elif jv.startswith("3_") and jv in JV_THREE:
            cfg = JV_THREE[jv]
            d = strip_noise(data, cfg["uc"])
            chunk = len(d) // cfg["avg"]
            pieces = [d[i*chunk:(i+1)*chunk] for i in range(cfg["avg"])]
            out = "".join(pieces[cfg["loc"].index(i)] for i in range(cfg["avg"]))
            if len(d) % chunk:
                out += d[cfg["avg"]*chunk:]
            clean_data = out
        else:
            clean_data = strip_noise(data, DEFAULT_JV_TWO)

        file_logger.info(f"去除混淆后：{clean_data}")
        bs64_str = base64.b64decode(clean_data.encode("utf-8")).decode("utf-8", errors='ignore')
    result = re.findall("{\".*", bs64_str)[0]
    try:
        json.loads(result)
        bs64.logger.info(f"解码成功{result}")
        return json.loads(result)
    except:
        if result.startswith('{'):
            result = result[1:]
            result = re.findall("{\".*", result)[0]
            try:
                json.loads(result)
                bs64.logger.info(f"解码成功{result}")
                return json.loads(result)
            except:
                bs64.logger.error("解码失败！")
                raise
        else:
            bs64.logger.error("解码失败！")
            raise
