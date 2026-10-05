# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
"""修复版更新通过本仓库 Release 页面手动下载，不在启动时联网。"""
import requests

RELEASES_URL = "https://github.com/chuyc11/cidaren-yijian-shuati/releases"

def get_update() -> str:
    return "0"

def get_update_detail() -> str:
    try:
        response = requests.get("https://api.github.com/repos/chuyc11/cidaren-yijian-shuati/releases/latest", timeout=8)
        response.raise_for_status()
        return response.json().get("body") or RELEASES_URL
    except (requests.RequestException, ValueError):
        return RELEASES_URL
