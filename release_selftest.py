"""Offline release smoke test, available as ``main.py --self-test``.

Only bundled resources and synthetic data are used. Mutable test data is kept
in a temporary directory; no login or task worker is started.
"""
import json
import os
from contextlib import contextmanager
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import traceback
from unittest.mock import patch


def _report_path():
    for index, argument in enumerate(sys.argv[1:], 1):
        if argument.startswith('--self-test-report='):
            return Path(argument.split('=', 1)[1]).expanduser().resolve()
        if argument == '--self-test-report':
            if index + 1 >= len(sys.argv):
                raise ValueError('--self-test-report requires a file path')
            return Path(sys.argv[index + 1]).expanduser().resolve()
    return None


def _write_report(path, result):
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


@contextmanager
def _working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def run() -> int:
    """Verify the real GUI, local model and persistence without HTTP traffic."""
    result = {'success': False, 'offline': True, 'checks': {
        'qt_offscreen': False,
        'main_window': False,
        'local_word_model': False,
        'config_roundtrip': False,
        'answer_library_roundtrip': False,
        'checkpoint_roundtrip': False,
        'task_report_roundtrip': False,
        'release_config_unchanged': False,
        'no_http_requests': False,
    }}
    report_path = None
    original_cwd = Path.cwd()
    original_qt_platform = os.environ.get('QT_QPA_PLATFORM')
    original_answer_cache = None
    answer_library = None
    window = None
    app = None
    request_attempts = []

    def block_http(*args, **kwargs):
        request_attempts.append(True)
        raise AssertionError('HTTP requests are forbidden during the offline self-test')

    try:
        report_path = _report_path()
        # Write an initial result so an OS-level Qt/plugin crash cannot look
        # like a completed test just because an old report file exists.
        _write_report(report_path, result)
        with patch('requests.sessions.Session.request', side_effect=block_http):
            entry = sys.modules.get('__main__')
            if entry is None or not hasattr(entry, 'TaskWorker'):
                import main as entry
            root = Path(entry.__file__).resolve().parent
            config_source = root / 'config' / 'config.json'
            original_config = config_source.read_bytes()
            from PyQt6.QtWidgets import QApplication
            from util import answer_lib as answer_library
            from util.task_checkpoint import TaskCheckpoint
            from util.task_report import TaskReport, format_report, reports_for_account
            from util.word_revert import get_model, word_revert

            original_answer_cache = answer_library._lib
            os.environ['QT_QPA_PLATFORM'] = 'offscreen'
            app = QApplication.instance() or QApplication(['offline-release-self-test'])
            assert app.platformName() == 'offscreen', 'Qt offscreen platform was not loaded'
            result['checks']['qt_offscreen'] = True

            with TemporaryDirectory(prefix='easy-cidaren-release-selftest-') as temporary, _working_directory(temporary):
                temporary_root = Path(temporary)
                (temporary_root / 'config').mkdir()
                shutil.copyfile(config_source, temporary_root / 'config' / 'config.json')

                # Read the actual bundled configuration, then redirect all
                # subsequent configuration writes into the temporary copy.
                info = entry.PublicInfo(root)
                info.path = str(temporary_root)
                logger = entry.Log('offline-release-self-test')
                window = entry.UiMainWindow(info, str(root), logger, entry.TaskWorker)
                window.show()
                app.processEvents()
                assert window.isVisible(), 'Main window failed to show'
                assert window.token_input.text() == '' and not window._logged_in
                assert window.task_worker is None and window._network_job is None
                assert window.close(), 'Main window refused to close'
                app.processEvents()
                assert not window.isVisible(), 'Main window remained visible after close'
                result['checks']['main_window'] = True

                model = get_model()
                assert model is not None and len(model('running')) == 1
                assert word_revert('running') == 'run', 'Local model lemmatization failed'
                result['checks']['local_word_model'] = True

                info.input_info(3, 4, 7, 9, False, 'gzip, deflate',
                                play_music=False, music_path='', fast_mode=False)
                info.read_seen()
                info.ignore_version('offline-self-test')
                reloaded_info = entry.PublicInfo(temporary_root)
                assert (reloaded_info.min_time, reloaded_info.max_time,
                        reloaded_info.spend_min_time, reloaded_info.spend_max_time) == (3, 4, 7, 9)
                assert not reloaded_info.br_choices and not reloaded_info.fast_mode
                assert not reloaded_info.play_music and reloaded_info.read
                assert reloaded_info.know_version == 'offline-self-test'
                assert reloaded_info.accept_encoding == 'gzip, deflate'
                result['checks']['config_roundtrip'] = True

                assert Path(answer_library._lib_path()).resolve() == temporary_root / 'config' / 'answer_lib.json'
                assert answer_library.load_lib(force=True) == {}, 'Fresh answer library is not empty'
                answer_library.add_answer('offline-self-test-phrase', ['synthetic phrase'])
                answer_library.add_word_answer('offline-self-test-word', ['synthetic'])
                answer_library.load_lib(force=True)
                assert answer_library.lookup('offline-self-test-phrase') == ['synthetic phrase']
                assert answer_library.lookup_word('offline-self-test-word') == ['synthetic']
                assert json.loads(Path(answer_library._lib_path()).read_text(encoding='utf-8')) == {
                    'offline-self-test-phrase': ['synthetic phrase'],
                    '_word_answers': {'offline-self-test-word': ['synthetic']},
                }
                result['checks']['answer_library_roundtrip'] = True

                task = {'release_id': 'offline-self-test-release', 'course_id': 'offline-course',
                        'task_id': 'offline-task', 'task_name': 'Synthetic release smoke test', 'task_type': 1}
                account = 'offline-self-test-account'
                info.right_count, info.wrong_count, info.skip_count = 1, 2, 3
                counts = {'right_count': 1, 'wrong_count': 2, 'skip_count': 3}
                checkpoint = TaskCheckpoint(temporary_root, account)
                checkpoint.save([task], info, batch_mode=True)
                state = TaskCheckpoint(temporary_root, account).load()
                assert state and state['account'] == account and state['pending'] == [task]
                assert state['batch_mode'] is True and state['counts'] == counts
                fresh_task = dict(task, progress=0, over_status=2)
                pending, recovered = checkpoint.reconcile([fresh_task])
                assert pending == [fresh_task] and recovered['counts'] == counts
                result['checks']['checkpoint_roundtrip'] = True

                task_report = TaskReport(temporary_root, account, task)
                exam = {'topic_done_num': 1, 'topic_mode': 15,
                        'stem': {'content': 'synthetic', 'remark': 'Offline fixture'},
                        'options': [{'content': 'synthetic option', 'answer_tag': 0}]}
                task_report.record(exam, 0, {'answer_result': 1, 'answer_corrects': [0]})
                task_report.save(elapsed=0.5)
                resumed_report = TaskReport(temporary_root, account, task)
                assert len(resumed_report.data['records']) == 1
                assert resumed_report.data['records'][0]['right'] is True
                resumed_report.finish(score=100, elapsed=0.5, info=info)
                saved_report = json.loads(resumed_report.path.read_text(encoding='utf-8'))
                assert saved_report['complete'] and saved_report['score'] == 100
                assert saved_report['counts'] == counts and saved_report['account'] == account
                assert reports_for_account(temporary_root, account) == [resumed_report.path]
                assert task['task_name'] in format_report(saved_report)
                result['checks']['task_report_roundtrip'] = True

                assert config_source.read_bytes() == original_config, 'Bundled configuration was modified'
                result['checks']['release_config_unchanged'] = True
                assert not request_attempts, 'Unexpected HTTP request was attempted'
                result['checks']['no_http_requests'] = True

        result['success'] = all(result['checks'].values())
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()
        if answer_library is not None:
            answer_library._lib = original_answer_cache
        os.chdir(original_cwd)
        if original_qt_platform is None:
            os.environ.pop('QT_QPA_PLATFORM', None)
        else:
            os.environ['QT_QPA_PLATFORM'] = original_qt_platform

    try:
        _write_report(report_path, result)
    except Exception:
        result['success'] = False
        result['report_error'] = traceback.format_exc()
    if sys.stdout is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['success'] else 1
