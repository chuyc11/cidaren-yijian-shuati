# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
"""Atomic recovery metadata. Always fetch the current question from the server."""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
import threading
import time

TASK_FIELDS = ('release_id', 'course_id', 'task_id', 'task_name', 'task_type')
COUNT_FIELDS = ('right_count', 'wrong_count', 'skip_count')


def account_key(user):
    # Stable across token renewal, different for different schools/accounts.
    identity = [str(user.get(k) or '') for k in ('student_id', 'student_code', 'school_id', 'school_name')]
    if not any(identity[:2]):
        return ''
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def task_key(task):
    return str(task.get('release_id')), str(task.get('course_id')), str(task.get('task_type'))


class TaskCheckpoint:
    def __init__(self, root, account):
        if account and (not isinstance(account, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', account)):
            raise ValueError('Invalid checkpoint account namespace')
        self.root = Path(root)
        self.path = self.root / 'config' / 'task_resume' / ((account or '_anonymous') + '.json')
        self.legacy_path = self.root / 'config' / 'task_resume.json'
        self.account = account
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            try:
                source = self.path if self.path.exists() else self.legacy_path
                state = json.loads(source.read_text(encoding='utf-8'))
                if state.get('version') != 1 or state.get('account') != self.account or not self.account:
                    return None
                if not isinstance(state.get('pending'), list) or not isinstance(state.get('counts'), dict):
                    return None
                if any(not isinstance(t, dict) or not all(k in t for k in TASK_FIELDS) for t in state['pending']):
                    return None
                if any(not isinstance(state['counts'].get(k), int) or state['counts'][k] < 0 for k in COUNT_FIELDS):
                    return None
                return state
            except (OSError, ValueError, TypeError, AttributeError):
                return None

    def save(self, tasks, info, batch_mode, counts_task=None):
        if not self.account:
            return
        state = {'version': 1, 'account': self.account, 'updated_at': time.time(),
                 'batch_mode': bool(batch_mode),
                 'pending': [{k: t.get(k, -1 if k == 'task_id' else '') for k in TASK_FIELDS} for t in tasks],
                 'counts': {k: int(getattr(info, k, 0)) for k in COUNT_FIELDS}}
        owner = counts_task if counts_task is not None else tasks[0] if tasks else None
        state['counts_task'] = list(task_key(owner)) if owner is not None else None
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(self.path)

    def reconcile(self, available):
        state = self.load()
        if not state:
            return [], None
        current = {task_key(t): t for t in available if float(t.get('progress') or 0) < 100
                   and int(t.get('over_status', 2)) == 2}
        # Fresh IDs and progress only; never replay a saved topic code or answer.
        tasks = [deepcopy(current[task_key(t)]) for t in state['pending'] if task_key(t) in current]
        # Older checkpoints count the original first pending task. Never move its
        # counts to another task when completion/expiry removes it from the queue.
        owner = state.get('counts_task')
        if owner is None and state['pending']:
            owner = task_key(state['pending'][0])
        if tasks and (not isinstance(owner, (list, tuple)) or tuple(owner) != task_key(tasks[0])):
            state['counts'] = {key: 0 for key in COUNT_FIELDS}
        return tasks, state
