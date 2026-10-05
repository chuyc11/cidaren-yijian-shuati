# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
import hashlib


def encrypt_md5(data: str) -> str:
    """
    MD5加密
    :param data:
    :return:
    """
    md5 = hashlib.md5()
    md5.update(data.encode("utf-8"))
    return md5.hexdigest()
