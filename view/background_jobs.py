# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
"""Network-only jobs. Widgets and the live task state stay on the GUI thread."""
from copy import copy, deepcopy
from PyQt6.QtCore import QThread, pyqtSignal
from api.login import verify_token
from api.main_api import get_class_task


class BackgroundJob(QThread):
    result_ready = pyqtSignal(object)
    error_ready = pyqtSignal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result_ready.emit(self.function())
        except Exception as exc:
            self.error_ready.emit(str(exc))


def login_result(token):
    return verify_token(token)


def fetch_tasks(info):
    snapshot = copy(info)
    snapshot.class_task = []
    page = 1
    get_class_task(snapshot, page)
    while int(snapshot.task_total_count) > page * 10:
        page += 1
        get_class_task(snapshot, page)
    tasks = []
    for group in snapshot.class_task:
        tasks.extend(group.get('records') or [])
    return {'groups': deepcopy(snapshot.class_task), 'tasks': deepcopy(tasks)}
