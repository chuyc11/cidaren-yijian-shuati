# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
import os
import subprocess
import threading
import time

import winsound
from playsound import playsound

from PyQt6.QtGui import QAction, QIcon
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWidgets import QMainWindow, QApplication, QMessageBox

import api.request_header as requests
import view.setting, view.introduce, view.error
from api.login import verify_token
from api.main_api import get_class_task
from util.basic_util import get_all_task
from publicInfo.publicInfo import PublicInfo
from api.geuuid import get_uuid
from view.background_jobs import BackgroundJob, login_result, fetch_tasks
from util.task_checkpoint import TaskCheckpoint, account_key
from util.task_report import reports_for_account, format_report
from util.task_completion import RecentCompletions
import json


class UiMainWindow(QMainWindow):
    output = "软件初始化成功！"

    def __init__(self, public_info, root_path, main_logger, task_worker_class):
        super(UiMainWindow, self).__init__()
        self.public_info = public_info
        self.root_path = root_path
        self.main_logger = getattr(main_logger, 'logger', main_logger)
        self.task_worker_class = task_worker_class
        self.token = ''
        self.task_worker = None
        self._batch_mode = False
        self._network_job = None
        self._logged_in = False
        self._all_tasks = []
        self._recent_completions = RecentCompletions()
        self._resume_tasks = []
        self._resume_state = None
        self._resume_announced = False
        self._checkpoint = None
        self._refresh_pending = False
        self._close_pending = False
        self.setupUi(self)
        self._sync_controls()

    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.setFixedSize(720, 400)
        icon_path = os.path.join(self.root_path, 'assets', 'icon.ico')
        if os.path.exists(icon_path):
            MainWindow.setWindowIcon(QIcon(icon_path))
        self.centralwidget = QtWidgets.QWidget(parent=MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        self.output_info = QtWidgets.QTextBrowser(parent=self.centralwidget)
        self.output_info.setGeometry(QtCore.QRect(460, 40, 256, 181))
        self.output_info.setObjectName("textBrowser")
        self.label = QtWidgets.QLabel(parent=self.centralwidget)
        self.label.setGeometry(QtCore.QRect(20, 20, 71, 16))
        self.label.setObjectName("label")
        self.token_input = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.token_input.setGeometry(QtCore.QRect(20, 40, 301, 20))
        self.token_input.setObjectName("token")
        self.login = QtWidgets.QPushButton(parent=self.centralwidget)
        self.login.setGeometry(QtCore.QRect(330, 40, 61, 24))
        self.login.setObjectName("login")
        self.login.clicked.connect(self.token_login)
        self.warn_info = QtWidgets.QLabel(parent=self.centralwidget)
        self.warn_info.setGeometry(QtCore.QRect(20, 60, 441, 16))
        self.warn_info.setStyleSheet("")
        self.warn_info.setObjectName("warn_info")
        self.label_3 = QtWidgets.QLabel(parent=self.centralwidget)
        self.label_3.setGeometry(QtCore.QRect(460, 20, 61, 16))
        self.label_3.setObjectName("label_3")
        self.label_4 = QtWidgets.QLabel(parent=self.centralwidget)
        self.label_4.setGeometry(QtCore.QRect(20, 90, 61, 16))
        self.label_4.setObjectName("label_4")
        self.user_info = QtWidgets.QLabel(parent=self.centralwidget)
        self.user_info.setGeometry(QtCore.QRect(20, 110, 441, 16))
        self.user_info.setObjectName("user_info")
        self.label_6 = QtWidgets.QLabel(parent=self.centralwidget)
        self.label_6.setGeometry(QtCore.QRect(20, 140, 71, 16))
        self.label_6.setObjectName("label_6")
        self.formLayoutWidget = QtWidgets.QWidget(parent=self.centralwidget)
        self.formLayoutWidget.setGeometry(QtCore.QRect(100, 140, 211, 22))
        self.formLayoutWidget.setObjectName("formLayoutWidget")
        self.formLayout = QtWidgets.QFormLayout(self.formLayoutWidget)
        self.formLayout.setContentsMargins(0, 0, 0, 0)
        self.formLayout.setObjectName("formLayout")
        self.learn_task = QtWidgets.QRadioButton(parent=self.formLayoutWidget)
        self.learn_task.setObjectName("learn_task")
        self.learn_task.setChecked(True)
        self.learn_task.clicked.connect(self.get_task_list)
        self.formLayout.setWidget(0, QtWidgets.QFormLayout.ItemRole.LabelRole, self.learn_task)
        self.test_task = QtWidgets.QRadioButton(parent=self.formLayoutWidget)
        self.test_task.setObjectName("test_task")
        self.test_task.clicked.connect(self.get_task_list)
        self.formLayout.setWidget(0, QtWidgets.QFormLayout.ItemRole.FieldRole, self.test_task)
        self.task_list = QtWidgets.QTableWidget(parent=self.centralwidget)
        self.task_list.setGeometry(QtCore.QRect(20, 170, 291, 80))
        self.task_list.setObjectName("task_list")
        # 四列：单选框 | 任务名 | 进度 | 得分，每列左对齐
        self.task_list.setColumnCount(4)
        self.task_list.verticalHeader().setVisible(False)
        self.task_list.horizontalHeader().setVisible(False)
        self.task_list.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.task_list.setShowGrid(False)
        self.task_list.setWordWrap(False)
        self.task_list.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.task_list.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.task_list.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.task_list.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.task_list.setColumnWidth(0, 30)
        self.task_list.setColumnWidth(2, 55)
        self.task_list.setColumnWidth(3, 75)
        # 目标任务选择：互斥单选框，勾选时同步选中表格行
        self.task_radio_group = QtWidgets.QButtonGroup(self)
        self.task_radio_group.setExclusive(True)
        self.task_list.itemClicked.connect(self._on_task_item_clicked)
        self.start_task = QtWidgets.QPushButton(parent=self.centralwidget)
        self.start_task.setGeometry(QtCore.QRect(20, 260, 85, 24))
        self.start_task.setObjectName("start_task")
        self.start_task.clicked.connect(self.start)
        self.batch_start = QtWidgets.QPushButton(parent=self.centralwidget)
        self.batch_start.setGeometry(QtCore.QRect(115, 260, 85, 24))
        self.batch_start.setObjectName("batch_start")
        self.batch_start.setText("一键刷题")
        self.batch_start.clicked.connect(self.start_batch)
        self.stop_task = QtWidgets.QPushButton(parent=self.centralwidget)
        self.stop_task.setGeometry(QtCore.QRect(210, 260, 85, 24))
        self.stop_task.setObjectName("stop_task")
        self.stop_task.clicked.connect(self.stop_current_task)
        self.resume_task = QtWidgets.QPushButton('恢复中断任务', self.centralwidget)
        self.resume_task.setGeometry(QtCore.QRect(320, 260, 125, 24))
        self.resume_task.clicked.connect(self.resume_tasks)
        self.refresh_tasks = QtWidgets.QPushButton('刷新任务', self.centralwidget)
        self.refresh_tasks.setGeometry(QtCore.QRect(320, 170, 100, 24))
        self.refresh_tasks.clicked.connect(self.get_task_list)
        self.report_button = QtWidgets.QPushButton('测试报告', self.centralwidget)
        self.report_button.setGeometry(QtCore.QRect(320, 200, 100, 24))
        self.report_button.clicked.connect(self.show_task_reports)
        # 当前任务名(一键刷题时显示正在执行的任务, 如 [2/6] 第五部分)
        self.progress_task_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.progress_task_label.setGeometry(QtCore.QRect(20, 312, 432, 18))
        self.progress_task_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.progress_task_label.setStyleSheet("color: #404040; font-weight: bold;")
        self.progress_task_label.setText("")
        # 答题进度条
        self.progress_bar = QtWidgets.QProgressBar(parent=self.centralwidget)
        self.progress_bar.setGeometry(QtCore.QRect(20, 290, 291, 20))
        self.progress_bar.setObjectName("progress_bar")
        self.progress_bar.setValue(0)
        # 进度文字（已完成数/总数）
        self.progress_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.progress_label.setGeometry(QtCore.QRect(320, 290, 50, 20))
        self.progress_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        # 答题对错统计(正确/错误)
        self.progress_right_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.progress_right_label.setGeometry(QtCore.QRect(372, 290, 62, 20))
        self.progress_right_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.progress_right_label.setStyleSheet("color: #2e9e44; font-weight: bold;")
        self.progress_right_label.setText("")
        self.progress_wrong_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.progress_wrong_label.setGeometry(QtCore.QRect(434, 290, 62, 20))
        self.progress_wrong_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.progress_wrong_label.setStyleSheet("color: #d0342c; font-weight: bold;")
        self.progress_wrong_label.setText("")
        self.progress_skip_label = QtWidgets.QLabel(parent=self.centralwidget)
        self.progress_skip_label.setGeometry(QtCore.QRect(496, 290, 62, 20))
        self.progress_skip_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.progress_skip_label.setStyleSheet("color: #808080; font-weight: bold;")
        self.progress_skip_label.setText("")
        self.follow_output = QtWidgets.QRadioButton(parent=self.centralwidget)
        self.follow_output.setGeometry(QtCore.QRect(607, 19, 101, 16))
        self.follow_output.setObjectName("follow_output")
        self.follow_output.setChecked(True)
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QtWidgets.QMenuBar(parent=MainWindow)
        self.menubar.setEnabled(True)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 720, 33))
        self.menubar.setObjectName("menubar")
        self.menubar.setStyleSheet("""
            QMenuBar {
                background-color: palette(menu);
                color: palette(text);
                border: none;
            }
            QMenuBar::item {
                background: transparent;
                color: palette(text);
            }
            QMenuBar::item:selected {
                background: palette(highlight);
            }
            QMenuBar::item:pressed {
                background: palette(highlight);
            }
            QMenu {
                background-color: palette(menu);
                color: palette(text);
            }
            QMenu::item {
                color: palette(text);
            }
            QMenu::item:selected {
                background-color: palette(highlight);
            }
        """)

        self.menu_separator = QtWidgets.QFrame(parent=MainWindow)
        self.menu_separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.menu_separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.menu_separator.setObjectName("menu_separator")

        self.menu = QtWidgets.QMenu(parent=self.menubar)
        self.menu.setObjectName("menu")
        self.menu_2 = QtWidgets.QMenu(parent=self.menubar)
        self.menu_2.setObjectName("menu_2")
        MainWindow.setMenuBar(self.menubar)

        self.menu_separator.setGeometry(QtCore.QRect(0, 33, 720, 3))

        self.statusbar = QtWidgets.QStatusBar(parent=MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)
        self.action = QtGui.QAction(parent=MainWindow)
        self.action.setObjectName("action")
        self.action_3 = QtGui.QAction(parent=MainWindow)
        self.action_3.setObjectName("action_3")
        self.action_4 = QtGui.QAction(parent=MainWindow)
        self.action_4.setObjectName("action_4")
        self.action_6 = QtGui.QAction(parent=MainWindow)
        self.action_6.setObjectName("action_6")
        self.action_7 = QtGui.QAction(parent=MainWindow)
        self.action_7.setObjectName("action_7")
        self.menu_get_token = QtWidgets.QMenu(parent=self.menubar)
        self.menu_get_token.setObjectName("menu_get_token")
        self.action_builtin = QtGui.QAction(parent=MainWindow)
        self.action_builtin.setObjectName("action_builtin")
        self.action_third_party = QtGui.QAction(parent=MainWindow)
        self.action_third_party.setObjectName("action_third_party")
        self.action_8 = QtGui.QAction(parent=MainWindow)
        self.action_8.setObjectName("action_8")
        self.action_open_logs = QtGui.QAction(parent=MainWindow)
        self.action_open_logs.setObjectName("action_open_logs")
        self.action_about = QtGui.QAction(parent=MainWindow)
        self.action_about.setObjectName("action_about")
        self.menu.addAction(self.action)
        self.menu.triggered[QAction].connect((self.open_settings))
        self.menu_2.addAction(self.action_4)
        self.menu_2.addSeparator()
        self.menu_2.addAction(self.action_6)
        self.menu_2.addAction(self.action_7)
        self.menu_2.addAction(self.action_about)
        self.menu_2.addSeparator()
        self.menu_2.addMenu(self.menu_get_token)
        self.menu_get_token.addAction(self.action_builtin)
        self.menu_get_token.addAction(self.action_third_party)
        self.action_open_logs.setText("导出日志文件")
        self.menu_2.addAction(self.action_open_logs)
        self.menu_2.triggered[QAction].connect((self.open_helper))
        self.menubar.addAction(self.menu.menuAction())
        self.menubar.addAction(self.menu_2.menuAction())
        self.retranslate_ui(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslate_ui(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(
            _translate("MainWindow", f"EasyCidaren_v{self.public_info.version}（github免费开源，严禁倒卖，作者ularch）"))
        self.output_info.setHtml(_translate("MainWindow", f"<pre>{UiMainWindow.output}</pre>"))
        self.label.setText(_translate("MainWindow", "用户token："))
        self.login.setText(_translate("MainWindow", "登录"))
        self.label_3.setText(_translate("MainWindow", "输出信息："))
        self.label_4.setText(_translate("MainWindow", "用户信息："))
        self.user_info.setText(_translate("MainWindow", "未获取"))
        self.label_6.setText(_translate("MainWindow", "待完成任务："))
        self.learn_task.setText(_translate("MainWindow", "班级自学任务"))
        self.test_task.setText(_translate("MainWindow", "班级测试任务"))
        self.start_task.setText(_translate("MainWindow", "开始任务"))
        self.stop_task.setText(_translate("MainWindow", "中止任务"))
        self.follow_output.setText(_translate("MainWindow", "随新消息滚动"))
        self.menu.setTitle(_translate("MainWindow", "设置"))
        self.menu_2.setTitle(_translate("MainWindow", "帮助"))
        self.action.setText(_translate("MainWindow", "首选项..."))
        self.action_4.setText(_translate("MainWindow", "使用教程"))
        self.action_6.setText(_translate("MainWindow", "项目首页"))
        self.action_7.setText(_translate("MainWindow", "作者首页"))
        self.menu_get_token.setTitle(_translate("MainWindow", "获取 token"))
        self.action_builtin.setText(_translate("MainWindow", "内置"))
        self.action_third_party.setText(_translate("MainWindow", "第三方"))
        self.action_open_logs.setText(_translate("MainWindow", "导出日志文件"))
        self.action_about.setText(_translate("MainWindow", "关于"))

    def update_output_info(self, info):
        """
        刷新前端输出信息
        :param info:
        :return:
        """
        self.output = self.output + f"\n{info}"
        self.output_info.setHtml(f"<pre style='white-space:pre-wrap;word-wrap:break-word;'>{self.output}</pre>")
        if self.follow_output.isChecked():
            scrollbar = self.output_info.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())


    def _sync_controls(self):
        running = self.task_worker is not None
        busy = running or self._network_job is not None or self._close_pending
        self.set_ui_enabled(not busy)
        self.start_task.setEnabled(self._logged_in and not busy and bool(self.public_info.task_list))
        self.batch_start.setEnabled(self.start_task.isEnabled())
        self.refresh_tasks.setEnabled(self._logged_in and not busy)
        self.resume_task.setEnabled(self._logged_in and not busy and bool(self._resume_tasks))
        self.stop_task.setEnabled(running and not self._close_pending)
        reports = reports_for_account(self.root_path, self._checkpoint.account) if self._checkpoint is not None and self._checkpoint.account else []
        self.report_button.setEnabled(self._logged_in and bool(reports))

    def show_task_reports(self):
        if self._checkpoint is None or not self._checkpoint.account:
            return
        paths = reports_for_account(self.root_path, self._checkpoint.account)
        if not paths:
            self.update_output_info('尚无本地测试报告')
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('测试报告')
        dialog.resize(680, 460)
        layout = QtWidgets.QVBoxLayout(dialog)
        selector = QtWidgets.QComboBox(dialog)
        viewer = QtWidgets.QTextBrowser(dialog)
        layout.addWidget(selector)
        layout.addWidget(viewer)
        def show_report(index):
            try:
                data = json.loads(paths[index].read_text(encoding='utf-8'))
                viewer.setPlainText(format_report(data))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                viewer.setPlainText('报告读取失败，请稍后重试。')
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                selector.addItem(str((data.get('task') or {}).get('task_name') or path.stem))
            except (OSError, ValueError, AttributeError):
                selector.addItem(path.stem)
        selector.currentIndexChanged.connect(show_report)
        show_report(0)
        dialog.exec()

    def _start_network_job(self, function, receiver):
        if self._network_job is not None:
            return
        job = BackgroundJob(function, self)
        self._network_job = job
        job.result_ready.connect(receiver)
        job.error_ready.connect(self._on_network_error)
        job.finished.connect(lambda: self._on_network_finished(job))
        self._sync_controls()
        job.start()

    def _on_network_error(self, message):
        self.warn_info.setStyleSheet('color: red;')
        self.warn_info.setText('网络操作失败，请重试')
        self.main_logger.error(f'网络操作失败：{message}')
        self.update_output_info(f'网络操作失败：{message}')

    def _on_network_finished(self, job):
        if self._network_job is job:
            self._network_job = None
        job.deleteLater()
        self._sync_controls()
        if self._close_pending:
            QtCore.QTimer.singleShot(0, self.close)
        elif self._refresh_pending:
            self._refresh_pending = False
            QtCore.QTimer.singleShot(0, self.get_task_list)

    def token_login(self):
        if self._network_job is not None or self.task_worker is not None:
            return
        self.token = self.token_input.text().splitlines()[0].strip() if self.token_input.text().strip() else ''
        if not self.token:
            self.warn_info.setStyleSheet('color: red;')
            self.warn_info.setText('登录失败！请输入 token！')
            return
        self._logged_in = False
        self._all_tasks = []
        self._recent_completions = RecentCompletions()
        self._resume_tasks = []
        self._resume_state = None
        self._resume_announced = False
        self.public_info.class_task = []
        self.public_info.task_list = []
        self.task_list.setRowCount(0)
        self.user_info.setText('未获取')
        self.warn_info.setStyleSheet('color: #505050;')
        self.warn_info.setText('正在后台登录…')
        token = self.token
        self._start_network_job(lambda: login_result(token), self._on_login_result)

    def _on_login_result(self, result):
        messages = {1: 'token 已过期，请重新获取', 2: 'HTTP 请求错误', 3: '连接超时，请检查网络',
                    4: '响应格式错误', 5: 'SSL 连接错误', 6: '代理连接错误', 7: '网络连接错误',
                    8: '需安全验证，请在词达人 App/微信中完成验证后重新登录',
                    9: '服务器拒绝登录，请查看日志中的具体原因'}
        if not isinstance(result, dict):
            self.warn_info.setStyleSheet('color: red;')
            self.warn_info.setText('登录失败：' + messages.get(result, '未知错误'))
            return
        user = (result.get('data') or {}).get('user_info')
        if not isinstance(user, dict):
            self._on_network_error('登录响应缺少用户信息')
            return
        self._logged_in = True
        self._checkpoint = TaskCheckpoint(self.root_path, account_key(user))
        self.warn_info.setStyleSheet('color: green;')
        self.warn_info.setText('登录成功！正在获取任务…')
        self.user_info.setText(' '.join(str(user.get(k) or '') for k in
                                      ('student_name', 'student_code', 'school_name', 'class_name')))
        self.update_output_info('登录成功！')
        self._refresh_pending = True

    def get_task_list(self):
        if not self._logged_in:
            return
        if self._network_job is not None or self.task_worker is not None:
            self._refresh_pending = True
            return
        self.public_info._task_choices = 1 if self.learn_task.isChecked() else 2
        PublicInfo.task_type = 'ClassTask'
        PublicInfo.task_type_int = 2
        self.update_output_info('正在后台刷新任务列表…')
        self._start_network_job(lambda: fetch_tasks(self.public_info), self._on_tasks_ready)

    def _on_tasks_ready(self, result):
        self._all_tasks = self._recent_completions.apply(result['tasks'])
        self.public_info.class_task = result['groups']
        choice = 1 if self.learn_task.isChecked() else 2
        self.public_info._task_choices = choice
        self.public_info.task_list = [t for t in self._all_tasks if int(t.get('task_type', 0)) == choice
                                      and int(t.get('over_status', 2)) != 3]
        self._render_tasks()
        if self._checkpoint is not None:
            self._resume_tasks, self._resume_state = self._checkpoint.reconcile(self._all_tasks)
            if self._resume_tasks and not self._resume_announced:
                self.update_output_info(f'检测到 {len(self._resume_tasks)} 个中断任务，点击“恢复中断任务”继续')
                self._resume_announced = True
        self.update_output_info('任务列表已刷新')
        self.warn_info.setText('登录成功！')

    def _render_tasks(self):
        for button in self.task_radio_group.buttons():
            self.task_radio_group.removeButton(button)
        self.task_list.setRowCount(0)
        for task in self.public_info.task_list:
            row = self.task_list.rowCount()
            self.task_list.insertRow(row)
            progress = float(task.get('progress') or 0)
            status = int(task.get('over_status', 2))
            disabled = status != 2 or progress >= 100
            radio = QtWidgets.QRadioButton(self.task_list)
            radio.setEnabled(not disabled)
            radio.clicked.connect(lambda checked, r=row: self._select_task_row(r))
            self.task_radio_group.addButton(radio)
            container = QtWidgets.QWidget(self.task_list)
            layout = QtWidgets.QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(radio)
            self.task_list.setCellWidget(row, 0, container)
            score = task.get('score')
            score_text = str(score if score is not None else 0) + (' (未开始)' if status == 1 else '')
            for col, text in enumerate([task['task_name'], f'{progress:g}%', score_text], start=1):
                cell = QtWidgets.QTableWidgetItem(text)
                cell.setData(QtCore.Qt.ItemDataRole.UserRole, task)
                if progress >= 100:
                    cell.setForeground(QtGui.QColor('green'))
                elif status == 1:
                    cell.setForeground(QtGui.QColor('gray'))
                if disabled:
                    cell.setToolTip('任务尚未开始或已经完成，无法启动')
                self.task_list.setItem(row, col, cell)

    def _select_task_row(self, row):
        """
        勾选单选框时同步选中表格行
        :param row:
        :return:
        """
        item = self.task_list.item(row, 1)
        if item:
            self.task_list.setCurrentItem(item)

    def _on_task_item_clicked(self, item):
        """
        点击任务行时自动勾选该行单选框
        :param item:
        :return:
        """
        try:
            task = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if task and (int(task.get('over_status', 2)) != 2 or float(task.get('progress') or 0) >= 100):
                return
            row = item.row()
            widget = self.task_list.cellWidget(row, 0)
            radio = widget.findChild(QtWidgets.QRadioButton) if widget else None
            if radio and not radio.isChecked():
                radio.setChecked(True)
        except Exception as e:
            self.main_logger.error(f"选择任务行失败: {e}")


    def start(self):
        if self.task_worker is not None or self._network_job is not None:
            return
        item = self.task_list.currentItem()
        task = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
        if not task or int(task.get('over_status', 2)) != 2:
            self.update_output_info('没有可执行的任务')
            return
        if float(task.get('progress') or 0) >= 100:
            self.update_output_info('该班级任务已经完成')
            return
        reply = QMessageBox.question(self, '开始任务', f"确认开始任务 {task['task_name']} 吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._launch_tasks([task], False)

    def start_batch(self):
        if self.task_worker is not None or self._network_job is not None:
            return
        tasks = [t for t in self.public_info.task_list if float(t.get('progress') or 0) < 100
                 and int(t.get('over_status', 2)) == 2]
        if not tasks:
            self.update_output_info('没有可执行的未完成任务')
            return
        reply = QMessageBox.question(self, '一键刷题', f'确认依次执行 {len(tasks)} 个未完成任务吗？',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._launch_tasks(tasks, True)

    def _launch_tasks(self, tasks, batch_mode, counts=None):
        if self.task_worker is not None or self._network_job is not None or not self._logged_in:
            return
        self.public_info.is_self_built = False
        for key in ('right_count', 'wrong_count', 'skip_count'):
            setattr(self.public_info, key, int((counts or {}).get(key, 0)))
        self._batch_mode = batch_mode
        worker = self.task_worker_class(tasks, batch_mode=batch_mode, public_info=self.public_info,
                                        logger=self.main_logger, checkpoint=self._checkpoint)
        self.task_worker = worker
        worker.task_finished.connect(self.on_task_finished)
        worker.task_completed.connect(self._recent_completions.remember)
        worker.task_error.connect(self.on_task_error)
        worker.task_progress.connect(self.update_progress)
        worker.task_notice.connect(self.on_task_notice)
        worker.batch_finished.connect(self.on_batch_finished)
        worker.finished.connect(lambda: self._on_worker_finished(worker))
        self._sync_controls()
        worker.start()
        self.update_output_info(f'后台执行开始：{len(tasks)} 个任务')

    def resume_tasks(self):
        if not self._resume_tasks or self.task_worker is not None or self._network_job is not None:
            return
        names = '、'.join(t['task_name'] for t in self._resume_tasks)
        reply = QMessageBox.question(self, '恢复中断任务', f'继续 {names}？服务器会返回当前进度和题目。',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            state = self._resume_state or {}
            self._launch_tasks(self._resume_tasks, bool(state.get('batch_mode')), state.get('counts'))

    def _on_worker_finished(self, worker):
        worker.save_checkpoint()
        worker.flush_report()
        if self.task_worker is worker:
            self.task_worker = None
        worker.deleteLater()
        self._batch_mode = False
        self._sync_controls()
        if self._close_pending:
            QtCore.QTimer.singleShot(0, self.close)
        else:
            self._refresh_pending = False
            QtCore.QTimer.singleShot(1000, self.get_task_list)

    def update_progress(self, progress_text):
        """
        更新进度
        :param progress_text: 格式 "done/total|right|wrong|skip|index/total|task_name"
        :return:
        """
        # 先按 | 切分(避免 index/total 段中的 / 破坏 done/total 解析)
        segments = progress_text.split('|')
        dt = segments[0].split('/')
        if len(dt) == 2:
            try:
                done = int(dt[0])
                total = int(dt[1])
                self.progress_bar.setMaximum(total)
                self.progress_bar.setValue(done)
                self.progress_label.setText(f"{done}/{total}")
                if len(segments) > 2:
                    self.progress_right_label.setText(f"正确 {segments[1]}")
                    self.progress_wrong_label.setText(f"错误 {segments[2]}")
                    if len(segments) > 3:
                        self.progress_skip_label.setText(f"跳过 {segments[3]}")
                        if len(segments) > 5:
                            phase = f" · {segments[6]}" if len(segments) > 6 else ''
                            speed = ' · 极速' if self.public_info.fast_mode else ''
                            self.progress_task_label.setText(f"[{segments[4]}] {segments[5]}{phase}{speed}")
            except ValueError:
                pass


    def on_task_finished(self, message):
        self.main_logger.info(message)
        self.update_output_info(message)
        if not self._batch_mode:
            self.progress_bar.setValue(self.progress_bar.maximum())
            if self.public_info.play_music:
                threading.Thread(target=self.play_music, daemon=True).start()
            QMessageBox.information(self, '任务完成', message)

    def on_batch_finished(self, summary):
        self.main_logger.info(summary)
        self.update_output_info(summary)
        if self.public_info.play_music:
            threading.Thread(target=self.play_music, daemon=True).start()
        QMessageBox.information(self, '一键刷题完成', summary)

    def on_task_notice(self, message):
        self.main_logger.info(message)
        self.update_output_info(message)

    def on_task_error(self, error_message):
        self.main_logger.error(error_message)
        self.update_output_info(f'运行出错：{error_message}')
        QMessageBox.warning(self, '任务执行失败', error_message)

    def open_settings(self, m):
        """
        打开设置
        :param m:
        :return:
        """
        if m.text() == "首选项...":
            self.settings = view.setting.Ui_Form(self.public_info)
            self.settings.show()

    def open_helper(self, m):
        """
        打开帮助
        :param m:
        :return:
        """
        if m.text() == "使用教程":
            self.use_introduction = view.introduce.Ui_Form()
            self.use_introduction.show()
        elif m.text() == "关于Easy_Cidaren":
            QtGui.QDesktopServices.openUrl(QtCore.QUrl('https://github.com/ularch/Easy_Cidaren'))
        elif m.text() == "关于作者":
            QtGui.QDesktopServices.openUrl(QtCore.QUrl('https://github.com/ularch'))
        elif m.text() == "关于":
            uid = get_uuid()
            msg_box = QMessageBox()
            msg_box.setWindowTitle("关于")
            msg_box.setText(f"EasyCidaren\n版本: {self.public_info.version}\n作者: ularch\n开源地址: https://github.com/ularch/Easy_Cidaren\n唯一设备ID: {uid}")
            msg_box.setIcon(QMessageBox.Icon.Information)
            copy_button = msg_box.addButton("复制", QMessageBox.ButtonRole.ActionRole)
            close_button = msg_box.addButton("关闭", QMessageBox.ButtonRole.AcceptRole)
            msg_box.setDefaultButton(close_button)
            msg_box.exec()
            if msg_box.clickedButton() == copy_button:
                clipboard = QApplication.clipboard()
                info_text = f"EasyCidaren\n版本: {self.public_info.version}\n作者: ularch\n开源地址: https://github.com/ularch/Easy_Cidaren\n唯一设备ID: {uid}"
                clipboard.setText(info_text)
                QMessageBox.information(self, "复制成功", "已将相关信息复制到剪贴板")
        elif m.text() == "第三方":
            self.get_token()
        elif m.text() == "内置":
            self.open_builtin_token_dialog()
        elif m.text() == "导出日志文件":
            from log.log import export_logs
            export_logs(self)

    def play_music(self):
        """
        播放音乐
        :return:
        """
        if hasattr(self.public_info, 'music_path') and self.public_info.music_path:
            if os.path.exists(self.public_info.music_path):
                music_path = self.public_info.music_path
            else:
                music_path = self.root_path + "/assets/music.wav"
                self.main_logger.error("自定义音乐文件不存在，使用默认音乐")
        else:
            music_path = self.root_path + "/assets/music.wav"
        try:
            playsound(music_path)
        except Exception as e:
            self.main_logger.info(f"playsound播放失败，使用winsound播放: {e}")
            try:
                winsound.PlaySound(music_path, winsound.SND_FILENAME)
            except Exception as e2:
                self.main_logger.info(f"winsound播放失败: {e2}")

    def get_token(self):
        """
        打开获取 token 界面
        :return:
        """
        exe_path = self.root_path + "\\get token\\词达人token获取.exe"
        try:
            subprocess.Popen([exe_path], shell=True)
        except:
            self.main_logger.info("词达人token获取.exe打开失败")

    def open_builtin_token_dialog(self):
        """
        打开内置 token 获取功能
        :return:
        """
        try:
            from view.builtin_token import BuiltinTokenDialog
            fetch_token_path = os.path.join(self.root_path, "get token", "fetch_token")
            if not os.path.exists(fetch_token_path):
                QMessageBox.critical(self, "错误", f"fetch_token 目录不存在：{fetch_token_path}")
                return
            dialog = BuiltinTokenDialog(parent=self, fetch_token_path=fetch_token_path)
            dialog.captured.connect(self.on_builtin_token_captured)
            dialog.exec()
        except ImportError as e:
            QMessageBox.critical(self, "错误", f"无法导入 builtin_token 模块：{e}")
            self.main_logger.error(f"导入 builtin_token 模块失败: {e}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开内置 token 获取功能失败：{e}")
            self.main_logger.error(f"打开内置 token 获取功能失败: {e}", exc_info=True)

    def on_builtin_token_captured(self, token):
        """
        内置 token 获取功能捕获 token
        :param token:
        :return:
        """
        if token:
            self.token_input.setText(token)
            self.update_output_info("Token 已自动填充到输入框")
            self.main_logger.info("内置 token 捕获成功，已自动填充")
            reply = QMessageBox.question(
                self,
                "自动登录",
                "Token 已捕获成功！是否立即登录？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.token_login()

    def set_ui_enabled(self, enabled):
        self.token_input.setEnabled(enabled)
        self.login.setEnabled(enabled)
        self.learn_task.setEnabled(enabled)
        self.test_task.setEnabled(enabled)
        self.task_list.setEnabled(enabled)
        self.start_task.setEnabled(enabled)
        self.batch_start.setEnabled(enabled)
        self.menu.setEnabled(enabled)
        self.menu_2.setEnabled(enabled)
        if not enabled:
            self.stop_task.setEnabled(True)


    def stop_current_task(self):
        if self.task_worker is None:
            return
        reply = QMessageBox.question(self, '确认停止', '停止后可以使用“恢复中断任务”继续。确定停止吗？',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.task_worker.stop()
            self.stop_task.setEnabled(False)
            self.update_output_info('正在停止，等待当前请求结束并保存进度…')

    def closeEvent(self, event):
        if self.task_worker is not None or self._network_job is not None:
            if not self._close_pending:
                reply = QMessageBox.question(self, '关闭程序', '后台操作仍在执行，保存进度后关闭程序？',
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                             QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                self._close_pending = True
                if self.task_worker is not None:
                    self.task_worker.stop()
                self._refresh_pending = False
                self._sync_controls()
            event.ignore()
        else:
            event.accept()
