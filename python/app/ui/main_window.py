"""
main_window.py —— 主窗口（M5 模块）
作用：把前面 M1~M4 做的功能，用 PySide6 做成一个能点的图形界面。
      包含：代理开关、订阅管理、节点&策略组、流量、日志、关于(语言切换)。
      关掉窗口只是最小化到托盘，程序仍在后台运行（见 tray.py）。
"""
import os
import re
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QTableWidget,
    QTableWidgetItem, QCheckBox, QHeaderView, QMessageBox,
    QFileDialog, QApplication, QDialog, QFormLayout, QLineEdit,
    QSpinBox, QDialogButtonBox, QSystemTrayIcon, QPlainTextEdit,
)
from PySide6.QtCore import Signal, QThread, QTimer
from PySide6.QtGui import QTextCursor, QFont

from app.ui.i18n import _, set_lang
from core import kernel, proxy, subscription as sub, nodes, config, traffic as traffic_mod, kernel_log, tun

# 模式下拉对应内核的 mode 值
MODES = ["rule", "global", "direct"]


# ---------------------------------------------------------------------------
# 后台工作线程：把"会卡界面"的操作（启内核/更新订阅/测速）放到子线程
# ---------------------------------------------------------------------------
class Worker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args

    def run(self):
        try:
            self.finished.emit(self.fn(*self.args))
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 记住内核进程（关窗不退出，进程要留着）
        self.kernel_proc = None
        # 后台工作线程：必须保存为实例属性，否则函数返回后会被 Python 回收，
        # 导致还在运行的 QThread 被销毁、程序闪退（PySide6 经典坑）
        self._worker_kernel = None
        self._worker_update = None
        self._worker_test = None
        # TUN 启动失败（多半没权限）时，后台把原因存这里，界面负责弹窗提示"已降级"
        self._pending_tun_fallback = None

        # 流量监控器（M6）：挂在 Qt 事件循环里定时拉 /connections
        self.traffic_monitor = traffic_mod.TrafficMonitor(self)
        self.traffic_monitor.updated.connect(self._on_traffic_updated)
        self.traffic_monitor.error.connect(self._on_traffic_error)

        # 日志监控器（M7）：定时增量读取内核日志文件，像 tail -f
        self.log_tail = kernel_log.KernelLogTail(kernel.kernel_log_path())
        self._log_filter = "all"   # 当前级别过滤：all / info+ / warn+ / error
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._poll_log)

        # 读取保存的语言设置
        settings = config.load_settings()
        set_lang(settings.get("language", "zh"))

        self._build_ui()
        self._retranslate()
        self._refresh_all()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.resize(720, 480)

    # ===================== 界面搭建 =====================
    def _build_ui(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tabs.addTab(self._build_proxy_page(), "proxy")
        self.tabs.addTab(self._build_sub_page(), "sub")
        self.tabs.addTab(self._build_node_page(), "node")
        # 流量页插在第 3 位，日志页在第 4 位，关于页自动后移到第 5 位
        self.tabs.insertTab(3, self._build_traffic_page(), "traffic")
        self.tabs.insertTab(4, self._build_log_page(), "log")
        self.tabs.addTab(self._build_about_page(), "about")

    def _build_proxy_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        # --- 内核控制 ---
        g1 = QGroupBox("kernel")
        v1 = QVBoxLayout(g1)
        self.kernel_status = QLabel("kernel")
        self.btn_kernel = QPushButton("kernel")
        self.btn_kernel.clicked.connect(self.on_toggle_kernel)
        v1.addWidget(self.kernel_status)
        v1.addWidget(self.btn_kernel)
        self._g_kernel = g1  # 存引用，翻译时改标题用

        # --- 系统代理 ---
        g2 = QGroupBox("proxy")
        v2 = QVBoxLayout(g2)
        self.proxy_status = QLabel("proxy")
        self.btn_proxy = QPushButton("proxy")
        self.btn_proxy.clicked.connect(self.on_toggle_proxy)
        h_mode = QHBoxLayout()
        self.mode_label = QLabel("mode")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        h_mode.addWidget(self.mode_label)
        h_mode.addWidget(self.mode_combo)
        v2.addWidget(self.proxy_status)
        v2.addWidget(self.btn_proxy)
        v2.addLayout(h_mode)
        self._g_proxy = g2  # 存引用，翻译时改标题用

        # --- TUN 模式（M8：全局透明代理）---
        g3 = QGroupBox("tun")
        v3 = QVBoxLayout(g3)
        self.tun_check = QCheckBox("tun")
        self.tun_check.toggled.connect(self.on_toggle_tun)
        self.tun_hint = QLabel("tun_hint")
        self.tun_hint.setWordWrap(True)   # 提示文字较长，允许换行
        self.btn_tun_grant = QPushButton("grant")
        self.btn_tun_grant.clicked.connect(self.on_grant_tun)
        v3.addWidget(self.tun_check)
        v3.addWidget(self.tun_hint)
        v3.addWidget(self.btn_tun_grant)
        self._g_tun = g3  # 存引用，翻译时改标题用

        layout.addWidget(g1)
        layout.addWidget(g2)
        layout.addWidget(g3)
        layout.addStretch()
        return page

    def _build_sub_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        bar = QHBoxLayout()
        self.btn_add_remote = QPushButton("add_remote")
        self.btn_add_local = QPushButton("add_local")
        self.btn_update_all = QPushButton("update_all")
        self.btn_add_remote.clicked.connect(self.on_add_remote)
        self.btn_add_local.clicked.connect(self.on_add_local)
        self.btn_update_all.clicked.connect(self.on_update_all)
        bar.addWidget(self.btn_add_remote)
        bar.addWidget(self.btn_add_local)
        bar.addWidget(self.btn_update_all)
        bar.addStretch()

        self.sub_table = QTableWidget()
        self.sub_table.setColumnCount(6)
        self.sub_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)

        layout.addLayout(bar)
        layout.addWidget(self.sub_table)
        return page

    def _build_node_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        # 状态提示：告诉用户内核是否运行（节点页完全依赖内核 API）
        self.node_status = QLabel("node_status")
        layout.addWidget(self.node_status)

        top = QHBoxLayout()
        self.group_label = QLabel("group")
        self.group_combo = QComboBox()
        self.group_combo.currentTextChanged.connect(self.on_group_changed)
        self.btn_refresh_nodes = QPushButton("refresh")
        self.btn_refresh_nodes.clicked.connect(self.refresh_nodes)
        self.btn_test_all = QPushButton("test_all")
        self.btn_test_all.clicked.connect(self.on_test_all)
        top.addWidget(self.group_label)
        top.addWidget(self.group_combo, 1)
        top.addWidget(self.btn_refresh_nodes)
        top.addWidget(self.btn_test_all)

        self.node_table = QTableWidget()
        self.node_table.setColumnCount(3)
        self.node_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.node_table.cellClicked.connect(self.on_node_clicked)

        layout.addLayout(top)
        layout.addWidget(self.node_table)
        return page

    def _build_traffic_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        # 状态/提示：告诉用户监控是否在跑（依赖内核）
        self.traffic_status = QLabel("traffic_status")
        layout.addWidget(self.traffic_status)

        # --- 速度 + 累计 ---
        g_speed = QGroupBox("speed")
        v_speed = QVBoxLayout(g_speed)
        self.down_speed_label = QLabel("down")
        self.up_speed_label = QLabel("up")
        self.total_down_label = QLabel("total_down")
        self.total_up_label = QLabel("total_up")
        v_speed.addWidget(self.down_speed_label)
        v_speed.addWidget(self.up_speed_label)
        v_speed.addWidget(self.total_down_label)
        v_speed.addWidget(self.total_up_label)
        layout.addWidget(g_speed)
        self._g_traffic_speed = g_speed  # 翻译时改标题用

        # --- 当前连接列表 ---
        self.conn_table = QTableWidget()
        self.conn_table.setColumnCount(6)
        self.conn_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        layout.addWidget(self.conn_table, 1)
        return page

    def _build_log_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        # 状态提示：内核是否在跑（日志文件总存在，但运行中才是实时的）
        self.log_status = QLabel("log_status")
        layout.addWidget(self.log_status)

        # --- 工具条：级别过滤 / 自动滚动 / 清空显示 ---
        bar = QHBoxLayout()
        self.log_filter_label = QLabel("level")
        self.log_filter_combo = QComboBox()
        self.log_filter_combo.addItems(["all", "info+", "warn+", "error"])
        self.log_filter_combo.currentTextChanged.connect(self.on_log_filter_changed)
        self.log_autoscroll = QCheckBox("autoscroll")
        self.log_autoscroll.setChecked(True)
        self.btn_clear_log = QPushButton("clear")
        self.btn_clear_log.clicked.connect(self.on_clear_log_view)
        bar.addWidget(self.log_filter_label)
        bar.addWidget(self.log_filter_combo)
        bar.addWidget(self.log_autoscroll)
        bar.addWidget(self.btn_clear_log)
        bar.addStretch()
        layout.addLayout(bar)

        # --- 日志正文：等宽字体、只读 ---
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Monospace"))
        self.log_view.setMaximumBlockCount(5000)  # 只留最近 5000 行，防止内存越滚越大
        layout.addWidget(self.log_view, 1)
        return page

    def _build_about_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        h1 = QHBoxLayout()
        self.lang_label = QLabel("lang")
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["中文", "English"])
        self.lang_combo.currentIndexChanged.connect(self.on_lang_changed)
        settings = config.load_settings()
        self.lang_combo.setCurrentIndex(0 if settings.get("language", "zh") == "zh" else 1)
        h1.addWidget(self.lang_label)
        h1.addWidget(self.lang_combo)
        h1.addStretch()

        self.version_label = QLabel("version")
        self.version_value = QLabel("clashDP v1.0 (dev)")

        layout.addLayout(h1)
        layout.addWidget(self.version_label)
        layout.addWidget(self.version_value)
        layout.addStretch()
        return page

    # ===================== 翻译（中英切换） =====================
    def _retranslate(self):
        self.setWindowTitle(_("clashDP 代理客户端", "clashDP Proxy Client"))
        self.tabs.setTabText(0, _("代理", "Proxy"))
        self.tabs.setTabText(1, _("订阅", "Subscriptions"))
        self.tabs.setTabText(2, _("节点", "Proxies"))
        self.tabs.setTabText(3, _("流量", "Traffic"))
        self.tabs.setTabText(4, _("日志", "Logs"))
        self.tabs.setTabText(5, _("关于", "About"))

        # 代理页
        self._g_kernel.setTitle(_("内核控制", "Kernel Control"))
        self._g_proxy.setTitle(_("系统代理", "System Proxy"))
        self.mode_label.setText(_("路由模式", "Routing Mode"))
        self.mode_combo.setItemText(0, _("规则", "Rule"))
        self.mode_combo.setItemText(1, _("全局", "Global"))
        self.mode_combo.setItemText(2, _("直连", "Direct"))
        # 代理页 - TUN
        self._g_tun.setTitle(_("TUN 模式（全局透明代理）", "TUN Mode (Global Proxy)"))
        self.tun_check.setText(_("开启 TUN 模式", "Enable TUN"))
        self.btn_tun_grant.setText(_("授权 TUN 权限", "Grant TUN Permission"))

        # 订阅页
        self.btn_add_remote.setText(_("添加订阅链接", "Add URL"))
        self.btn_add_local.setText(_("添加本地配置", "Add Local"))
        self.btn_update_all.setText(_("更新全部", "Update All"))
        self.sub_table.setHorizontalHeaderLabels([
            _("名称", "Name"), _("类型", "Type"), _("节点数", "Nodes"),
            _("更新时间", "Updated"), _("启用", "Enabled"), _("操作", "Action"),
        ])

        # 节点页
        self.group_label.setText(_("策略组", "Group"))
        self.btn_refresh_nodes.setText(_("刷新", "Refresh"))
        self.btn_test_all.setText(_("测速全部", "Test All"))
        self.node_table.setHorizontalHeaderLabels([
            _("节点", "Node"), _("类型", "Type"), _("延迟(ms)", "Delay(ms)"),
        ])

        # 流量页
        self._g_traffic_speed.setTitle(_("实时速度 / 累计流量", "Live Speed / Totals"))
        self.traffic_status.setText(
            _("流量监控：请先在『代理』页启动内核，再切回本页即可自动开始监控。",
              "Traffic monitor: start the kernel on the Proxy tab, then come back here to auto-monitor."))
        self.down_speed_label.setText(_("↓ 下载速度：—", "↓ Down: —"))
        self.up_speed_label.setText(_("↑ 上传速度：—", "↑ Up: —"))
        self.total_down_label.setText(_("累计下载：—", "Total Down: —"))
        self.total_up_label.setText(_("累计上传：—", "Total Up: —"))
        self.conn_table.setHorizontalHeaderLabels([
            _("进程", "Process"), _("目标", "Destination"), _("出口节点", "Via"),
            _("类型", "Type"), _("下行", "Down"), _("上行", "Up"),
        ])

        # 日志页
        self.log_status.setText(
            _("日志：请先在『代理』页启动内核，这里会实时滚动运行日志。",
              "Logs: start the kernel on the Proxy tab; live logs will appear here."))
        self.log_filter_label.setText(_("级别", "Level"))
        self.log_filter_combo.setItemText(0, _("全部", "All"))
        self.log_filter_combo.setItemText(1, _("信息+", "Info+"))
        self.log_filter_combo.setItemText(2, _("警告+", "Warn+"))
        self.log_filter_combo.setItemText(3, _("仅错误", "Error"))
        self.log_autoscroll.setText(_("自动滚动", "Auto-scroll"))
        self.btn_clear_log.setText(_("清空显示", "Clear View"))

        # 关于页
        self.lang_label.setText(_("界面语言", "Language"))
        self.version_label.setText(_("版本", "Version"))
        self.version_value.setText(_("clashDP v1.0 (开发版)", "clashDP v1.0 (dev)"))

        # 动态状态文本也跟着刷新
        self._refresh_kernel_status()
        self._refresh_proxy_status()
        self._refresh_tun_status()

    # ===================== 状态刷新 =====================
    def _refresh_all(self):
        self._refresh_kernel_status()
        self._refresh_proxy_status()
        self.refresh_subs()
        self.refresh_nodes()

    def on_tab_changed(self, index):
        """切到某个标签页时刷新对应数据，避免"开了内核节点页还空着"。"""
        # 先停掉所有页专属的定时轮询，再按当前页开启需要的，省资源
        self.traffic_monitor.stop()
        self.log_timer.stop()
        if index == 0:      # 代理页
            self._refresh_kernel_status()
            self._refresh_proxy_status()
        elif index == 2:    # 节点页
            self.refresh_nodes()
        elif index == 3:    # 流量页
            self._start_traffic_if_visible()
        elif index == 4:    # 日志页
            self._start_log_if_visible()

    # ===================== 流量页（M6） =====================
    def _start_traffic_if_visible(self):
        """内核在跑且当前停在流量页时，才启动轮询；否则停掉，省资源也避免无意义报错。"""
        running = bool(self.kernel_proc and kernel.is_running(self.kernel_proc))
        if self.tabs.currentIndex() == 3 and running:
            self.traffic_monitor.start()
        else:
            self.traffic_monitor.stop()

    def _on_traffic_updated(self, down_rate, up_rate, total_down, total_up, conns):
        self.traffic_status.setText(
            _("实时流量监控中…（每秒刷新）", "Monitoring live traffic (1s)…"))
        self.down_speed_label.setText(
            _("↓ 下载速度：%s/s" % traffic_mod.format_bytes(down_rate),
              "↓ Down: %s/s" % traffic_mod.format_bytes(down_rate)))
        self.up_speed_label.setText(
            _("↑ 上传速度：%s/s" % traffic_mod.format_bytes(up_rate),
              "↑ Up: %s/s" % traffic_mod.format_bytes(up_rate)))
        self.total_down_label.setText(
            _("累计下载：%s" % traffic_mod.format_bytes(total_down),
              "Total Down: %s" % traffic_mod.format_bytes(total_down)))
        self.total_up_label.setText(
            _("累计上传：%s" % traffic_mod.format_bytes(total_up),
              "Total Up: %s" % traffic_mod.format_bytes(total_up)))

        # 连接列表：每行一条连接
        self.conn_table.setRowCount(len(conns))
        for i, c in enumerate(conns):
            m = c.get("metadata", {}) or {}
            # 进程名：Linux 没开 TUN 时内核拿不到，显示为"—"（属内核限制，不是 bug）
            proc = m.get("processPath") or m.get("process") or "—"
            host = m.get("host") or "%s:%s" % (
                m.get("destinationIP", ""), m.get("destinationPort", ""))
            chain = c.get("chains", []) or []
            via = chain[-1] if chain else "—"   # chains 最后一项才是真正出口节点
            typ = "%s/%s" % (m.get("network", ""), m.get("type", ""))
            self.conn_table.setItem(i, 0, QTableWidgetItem(str(proc)))
            self.conn_table.setItem(i, 1, QTableWidgetItem(str(host)))
            self.conn_table.setItem(i, 2, QTableWidgetItem(str(via)))
            self.conn_table.setItem(i, 3, QTableWidgetItem(str(typ)))
            self.conn_table.setItem(i, 4, QTableWidgetItem(
                traffic_mod.format_bytes(c.get("download", 0))))
            self.conn_table.setItem(i, 5, QTableWidgetItem(
                traffic_mod.format_bytes(c.get("upload", 0))))

    def _on_traffic_error(self, msg):
        # 出错（多半内核没跑/密钥不对）：明确告诉用户，而不是默默空白
        self.traffic_status.setText(
            _("流量读取失败：%s\n请确认内核已启动（『代理』页点启动内核）。"
              % msg,
              "Traffic read failed: %s\nMake sure the kernel is running." % msg))
        self.conn_table.setRowCount(0)

    # ===================== 日志页（M7） =====================
    def _start_log_if_visible(self):
        """停在日志页就启动轮询；即使内核没运行也能看历史日志。"""
        if self.tabs.currentIndex() == 4:
            self.log_timer.start(1000)   # 每秒读一次新增
            self._poll_log()             # 切进来立刻先读一遍，不用等 1 秒
        else:
            self.log_timer.stop()

    def _poll_log(self):
        """读取日志文件新增内容，按当前级别过滤后追加到文本框。"""
        running = bool(self.kernel_proc and kernel.is_running(self.kernel_proc))
        if running:
            self.log_status.setText(
                _("日志：实时滚动中…（每秒刷新）", "Logs: streaming live (1s)…"))
        else:
            self.log_status.setText(
                _("日志：内核未运行；如之前启动过，这里显示上次的日志。",
                  "Logs: kernel not running; showing previous log if any."))

        new_lines = self.log_tail.read_new()
        if not new_lines:
            return
        shown = [ln for ln in new_lines if self._level_match(ln)]
        if not shown:
            return
        self._append_log_lines(shown)

    def _append_log_lines(self, lines):
        """
        把新日志追加到文本框，并且"不该跳的时候绝不跳"。
        坑：QPlainTextEdit.appendPlainText() 内部会把光标移到文档末尾，
            视图就会强制滚到底——所以取消勾选自动滚动也不管用。
        解法：用一个独立的 QTextCursor 在末尾插入，不移动可见光标；
              再手动保存/恢复滚动条位置，双保险。
        """
        sb = self.log_view.verticalScrollBar()
        keep = sb.value()                      # 记住当前滚动位置
        doc = self.log_view.document()

        cur = QTextCursor(doc)                 # 独立游标：不碰用户可见光标
        cur.movePosition(QTextCursor.End)
        text = "\n".join(lines)
        # 文档已有内容时先补一个换行，避免和上一行粘在一起
        if doc.characterCount() > 1:
            cur.insertText("\n" + text)
        else:
            cur.insertText(text)

        if self.log_autoscroll.isChecked():
            # 勾选了才跟到最新；延后一拍再设，等文档布局算完滚动范围
            sb.setValue(sb.maximum())
            QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))
        else:
            # 没勾选：恢复原来的滚动位置，视线不动
            sb.setValue(keep)
            QTimer.singleShot(0, lambda: sb.setValue(keep))

    def _level_match(self, line):
        """
        按级别判断该行是否通过当前过滤。
        mihomo 日志有两种格式，都要认：
          - 写进文件（非终端）时的 logrus 格式：time="..." level=info msg="..."
          - 终端/传统格式：INFO[2026-...] msg
        """
        f = self._log_filter
        if f == "all":
            return True
        lvl = self._extract_level(line)
        if f == "error":
            return lvl == "error"
        if f == "warn+":
            return lvl in ("warning", "warn", "error", "fatal")
        if f == "info+":
            return lvl in ("info", "warning", "warn", "error", "fatal")
        return True

    @staticmethod
    def _extract_level(line):
        """从一行日志里取出级别词（小写）；取不到返回空串。"""
        s = line.strip()
        # 格式1（logrus，mihomo 写文件时用）：time="..." level=info msg="..."
        m = re.search(r"\blevel=([A-Za-z]+)", s)
        if m:
            return m.group(1).lower()
        # 格式2（传统）：INFO[2026-...] msg
        head = s.split("[", 1)[0].strip().lower()
        if head in ("debug", "info", "warn", "warning", "error", "fatal"):
            return head
        return ""

    def on_log_filter_changed(self, text):
        """切换级别过滤：清空显示，从头重读全量日志并按新过滤重画。"""
        self._log_filter = text
        self.log_view.clear()
        self.log_tail.reset()
        self._poll_log()

    def on_clear_log_view(self):
        """只清空界面显示，不删日志文件；把读取位置推进到末尾，避免立刻补回来。"""
        self.log_view.clear()
        try:
            self.log_tail.offset = os.path.getsize(self.log_tail.path)
        except OSError:
            self.log_tail.offset = 0

    def _refresh_kernel_status(self):
        running = self.kernel_proc is not None and kernel.is_running(self.kernel_proc)
        self._g_kernel_status_text(running)
        self.btn_kernel.setText(
            _("停止内核", "Stop Kernel") if running else _("启动内核", "Start Kernel"))

    def _g_kernel_status_text(self, running):
        self.kernel_status.setText(
            _("内核：运行中", "Kernel: Running") if running
            else _("内核：已停止", "Kernel: Stopped"))

    def _refresh_proxy_status(self):
        mode = proxy.get_proxy_mode()
        on = (mode == "manual")
        self.proxy_status.setText(
            _("系统代理：已开启", "System Proxy: On") if on
            else _("系统代理：已关闭", "System Proxy: Off"))
        self.btn_proxy.setText(
            _("关闭系统代理", "Turn Off Proxy") if on else _("开启系统代理", "Turn On Proxy"))

    def refresh_subs(self):
        mgr = sub.SubscriptionManager()
        subs = mgr.list_all()
        self.sub_table.setRowCount(len(subs))
        for i, s in enumerate(subs):
            self.sub_table.setItem(i, 0, QTableWidgetItem(s.get("name", "")))
            self.sub_table.setItem(i, 1, QTableWidgetItem(
                _("远程", "Remote") if s.get("type") == "remote" else _("本地", "Local")))
            self.sub_table.setItem(i, 2, QTableWidgetItem(str(s.get("node_count", 0))))
            self.sub_table.setItem(i, 3, QTableWidgetItem(
                (s.get("updated_at") or _("未更新", "Never"))[:19]))
            # 启用勾选
            cb = QCheckBox()
            cb.setChecked(s.get("enabled", True))
            cb.toggled.connect(lambda v, sid=s["id"]: self.on_toggle_sub(sid, v))
            self.sub_table.setCellWidget(i, 4, cb)
            # 删除按钮
            btn = QPushButton(_("删除", "Delete"))
            btn.clicked.connect(lambda _, sid=s["id"]: self.on_delete_sub(sid))
            self.sub_table.setCellWidget(i, 5, btn)

    def refresh_nodes(self):
        # 先提示内核状态（节点页完全依赖内核 API，没跑就明确告诉用户）
        running = bool(self.kernel_proc and kernel.is_running(self.kernel_proc))
        if running:
            self.node_status.setText(
                _("内核运行中，节点列表如下。", "Kernel running, proxies below."))
        else:
            self.node_status.setText(
                _("内核未运行：请先在『代理』页点『启动内核』，再回来这里。",
                  "Kernel not running: start it on the Proxy tab first."))

        # 内核没运行 / 连不上时，安静地显示空列表，绝不能让启动崩溃
        try:
            nm = nodes.NodeManager()
            groups = nm.list_groups()
        except Exception as e:
            # 不再静默清空：把错误显示出来，方便你判断是"没启动"还是"连不上"
            self.group_combo.clear()
            self.node_table.setRowCount(0)
            self.node_status.setText(
                _("读取节点失败：%s\n请确认内核已启动（『代理』页点启动内核）。"
                  % str(e),
                  "Failed to read nodes: %s\nMake sure the kernel is running."
                  % str(e)))
            return
        selectors = [g for g in groups if g["type"].lower() == "selector"]
        self.group_combo.clear()
        self.group_combo.addItems([g["name"] for g in selectors])
        if not selectors:
            # 内核在跑但一个策略组都没有：多半是订阅还没更新
            self.node_table.setRowCount(0)
            if running:
                self.node_status.setText(
                    _("内核在运行，但没有读到任何策略组。请先到『订阅』页点『更新全部』。"
                      "（当前配置可能还没有节点数据）",
                      "Kernel is running but no proxy groups found. "
                      "Go to Subscriptions tab and click 'Update All'."))
            return
        self.on_group_changed(selectors[0]["name"])

    # ===================== 代理页操作 =====================
    def on_toggle_kernel(self):
        if self.kernel_proc and kernel.is_running(self.kernel_proc):
            kernel.stop_kernel(self.kernel_proc)
            self.kernel_proc = None
            self._refresh_kernel_status()
            self.refresh_nodes()
            self.traffic_monitor.stop()
        else:
            self._start_kernel_via_worker()

    def _start_kernel_with_repair(self):
        """
        启动内核，尽量"起得来"：
          1) 配置校验不过（ConfigError）：按当前订阅重建配置再试一次
             （会自动剔除无效规则，避免订阅里的坏规则把你卡死）。
          2) TUN 开着但启动失败（多半没权限）：自动关掉 TUN、重建配置再试，
             并把原因记到 self._pending_tun_fallback，由界面提示"已降级"。
        注意：这个函数跑在后台线程里，不要在这里碰界面控件。
        """
        try:
            return kernel.start_kernel()
        except kernel.ConfigError:
            sub.apply_subscriptions()     # 重新生成配置（自动剔除无效规则）
            return kernel.start_kernel()
        except RuntimeError as e:
            # 注意：ConfigError 是 RuntimeError 的子类，已被上面接住，不会走到这
            settings = config.load_settings()
            if settings.get("tun_enabled"):
                settings["tun_enabled"] = False
                config.save_settings(settings)
                sub.apply_subscriptions()     # 重建 tun.enable=false 的配置
                self._pending_tun_fallback = str(e)   # 交给界面弹窗提示
                return kernel.start_kernel()
            raise

    def _start_kernel_via_worker(self, on_done=None):
        """
        在后台线程里启动内核，避免界面卡住。
        启动失败（如内核秒退、配置错误）会把日志弹窗给你看，不再"无反应"。
        on_done: 启动成功后额外要执行的函数（如顺便开系统代理）。
        """
        self._busy(_("正在启动内核…", "Starting kernel…"))
        w = Worker(self._start_kernel_with_repair)
        def on_ok(proc):
            self.kernel_proc = proc
            self._refresh_kernel_status()
            self.refresh_nodes()
            self._start_traffic_if_visible()
            self._start_log_if_visible()
            self._consume_tun_fallback()
            if on_done:
                on_done()
        w.finished.connect(on_ok)
        w.error.connect(self._on_kernel_error)
        w.finished.connect(lambda _: self._idle())
        self._worker_kernel = w
        w.start()

    def _on_kernel_error(self, msg):
        """统一的"启动/操作失败"弹窗，并对常见原因补上可操作提示。"""
        tip = ""
        low = str(msg).lower()
        if "address already in use" in low or "already in use" in low or "bind" in low:
            tip = _("\n\n提示：端口被占用，可能还有旧的 mihomo 在后台运行。\n"
                    "可在终端执行：pkill -f mihomo  然后重试。",
                    "\n\nHint: port in use; an old mihomo may still be running.\n"
                    "Run: pkill -f mihomo, then retry.")
        QMessageBox.critical(self, _("启动失败", "Start Failed"), str(msg) + tip)

    def on_toggle_proxy(self):
        try:
            if proxy.get_proxy_mode() == "manual":
                proxy.disable_proxy()
            else:
                proxy.enable_proxy()
        except proxy.ProxyError as e:
            QMessageBox.warning(
                self, _("系统代理设置失败", "Proxy Error"),
                _("无法设置系统代理：\n%s\n\n请确认你在 deepin 桌面会话中运行本程序。"
                  % str(e),
                  "Could not set system proxy:\n%s\n\nMake sure you run this inside a deepin desktop session."
                  % str(e)))
            return
        self._refresh_proxy_status()

    def on_mode_changed(self, idx):
        mode = MODES[idx]
        try:
            nm = nodes.NodeManager()
            nm.api.set_mode(mode)
        except Exception as e:
            QMessageBox.warning(self, _("提示", "Note"),
                                _("切换模式需内核在运行：", "Need kernel running: ") + str(e))

    # ===================== TUN 模式（M8） =====================
    def _refresh_tun_status(self):
        """同步 TUN 勾选状态，并按"有没有权限 / 是否已开启"显示对应提示。"""
        st = tun.status()
        enabled = bool(config.load_settings().get("tun_enabled", False))

        # 同步勾选框（blockSignals 防止又触发 on_toggle_tun 造成递归）
        self.tun_check.blockSignals(True)
        self.tun_check.setChecked(enabled)
        self.tun_check.blockSignals(False)

        if not st["ok"]:
            self.tun_hint.setText(
                _("TUN 需要管理员权限：点下方按钮授权（只需一次，换内核后要重新授权）。",
                  "TUN needs admin permission: click below to grant once "
                  "(re-grant after replacing the kernel)."))
        elif enabled:
            self.tun_hint.setText(
                _("TUN 已开启：整机流量由内核接管，无需再设系统代理。",
                  "TUN is on: all traffic is handled by the kernel."))
        else:
            self.tun_hint.setText(
                _("权限已就绪，勾选即可开启全局透明代理。",
                  "Permission ready; tick to enable global transparent proxy."))

        # 没权限才显示"授权"按钮，有权限就藏起来不碍事
        self.btn_tun_grant.setVisible(not st["ok"])

    def on_toggle_tun(self, checked):
        """勾选/取消 TUN：保存设置，必要时重建配置并重启内核。"""
        settings = config.load_settings()
        settings["tun_enabled"] = bool(checked)
        config.save_settings(settings)

        # 开启但没权限：先保存勾选状态，引导授权；这次不重启（重启也会失败）
        if checked and not tun.has_tun_capability():
            self._refresh_tun_status()
            QMessageBox.information(
                self, _("需要授权", "Permission Needed"),
                _("开启 TUN 需要管理员权限。\n\n"
                  "请点下方「授权 TUN 权限」按钮（只需一次），授权后再重启内核即可生效。",
                  "Enabling TUN requires admin permission.\n\n"
                  "Click 'Grant TUN Permission' once, then restart the kernel."))
            return

        self._refresh_tun_status()
        running = bool(self.kernel_proc and kernel.is_running(self.kernel_proc))
        if running:
            self._apply_and_restart_kernel()
        else:
            self.statusBar().showMessage(
                _("已保存，下次启动内核时生效。",
                  "Saved; takes effect on next kernel start."), 4000)

    def on_grant_tun(self):
        """点「授权 TUN 权限」：尝试 pkexec 自动授权，失败则给出手动命令。"""
        self._busy(_("正在请求授权（可能弹出密码框）…", "Requesting permission…"))
        ok, msg = tun.grant_capability()
        self._idle()
        if ok:
            QMessageBox.information(self, _("授权成功", "Granted"), msg)
        else:
            QMessageBox.warning(self, _("授权失败", "Grant Failed"), msg)
        self._refresh_tun_status()

    def _consume_tun_fallback(self):
        """若后台发生过 TUN 启动失败并自动降级，就在界面上提示一次。"""
        if not self._pending_tun_fallback:
            return
        msg = self._pending_tun_fallback
        self._pending_tun_fallback = None
        self._refresh_tun_status()   # 勾选状态回到关闭
        QMessageBox.warning(
            self, _("TUN 已降级", "TUN Fallback"),
            _("TUN 模式启动失败，已自动回退到普通系统代理模式（功能不受影响）。\n\n"
              "常见原因：没有管理员权限，或 TUN 网卡创建失败。\n"
              "可点「授权 TUN 权限」后再试一次。\n\n内核日志（节选）：\n%s" % msg[:800],
              "TUN failed to start; fell back to normal system-proxy mode.\n\n"
              "Common cause: missing permission or TUN device error.\n"
              "Grant permission and retry.\n\nKernel log (tail):\n%s" % msg[:800]))

    def _apply_and_restart_kernel(self):
        """重建配置（带上最新 tun 开关）并重启内核。"""
        old = self.kernel_proc

        def work():
            sub.apply_subscriptions()        # 按当前设置重建 config.yaml
            kernel.stop_kernel(old)
            return self._start_kernel_with_repair()   # 内含 TUN 失败降级

        def on_ok(proc):
            self.kernel_proc = proc
            self._refresh_kernel_status()
            self.refresh_nodes()
            self._start_traffic_if_visible()
            self._start_log_if_visible()
            self._consume_tun_fallback()

        self._busy(_("正在应用 TUN 设置…", "Applying TUN settings…"))
        w = Worker(work)
        w.finished.connect(on_ok)
        w.error.connect(self._on_kernel_error)
        w.finished.connect(lambda _: self._idle())
        self._worker_restart = w
        w.start()

    # ===================== 订阅页操作 =====================
    def on_add_remote(self):
        dlg = AddRemoteDialog(self)
        if dlg.exec():
            name, url, interval = dlg.get_data()
            if not name or not url:
                return
            mgr = sub.SubscriptionManager()
            mgr.add_remote(name, url, interval=interval)
            self.refresh_subs()

    def on_add_local(self):
        path, _ = QFileDialog.getOpenFileName(
            self, _("选择配置文件", "Select config"), "",
            _("YAML 文件 (*.yaml *.yml)", "YAML (*.yaml *.yml)"))
        if not path:
            return
        import os
        name = os.path.splitext(os.path.basename(path))[0]
        mgr = sub.SubscriptionManager()
        mgr.add_local(name, path)
        self.refresh_subs()

    def on_update_all(self):
        mgr = sub.SubscriptionManager()

        def work():
            res = mgr.update_all()
            info = sub.apply_subscriptions()
            return res, info

        self._busy(_("正在更新订阅…", "Updating subscriptions…"))
        w = Worker(work)
        w.finished.connect(lambda r: self._after_update(r))
        w.error.connect(self._on_kernel_error)
        w.finished.connect(lambda _: self._idle())
        self._worker_update = w
        w.start()

    def _after_update(self, r):
        res, info = r
        self.refresh_subs()

        running = bool(self.kernel_proc and kernel.is_running(self.kernel_proc))
        lines = [
            _("订阅已更新：节点 %d 个，策略组 %d 个，规则 %d 条，规则集 %d 个。"
              % (info["proxy_count"], info["group_count"],
                 info["rule_count"], info.get("provider_count", 0)),
              "Updated: %d nodes, %d groups, %d rules, %d rule-providers."
              % (info["proxy_count"], info["group_count"],
                 info["rule_count"], info.get("provider_count", 0))),
        ]

        # 有规则被自动剔除时，把原因列出来（最多显示 5 条，避免弹窗太长）
        warns = info.get("warnings") or []
        if warns:
            lines.append(_("已自动剔除 %d 条内核用不了的规则（不影响使用）：" % len(warns),
                           "%d unusable rules were dropped:" % len(warns)))
            for w in warns[:5]:
                lines.append("  · " + w)
            if len(warns) > 5:
                lines.append("  …")

        if running:
            lines.append(_("内核正在运行，已自动重启以加载新配置。",
                           "Kernel is running; restarting to apply."))
        else:
            lines.append(_("请点\"启动内核\"使配置生效。", "Start kernel to apply."))

        QMessageBox.information(self, _("完成", "Done"), "\n".join(lines))

        # 内核在跑就自动重启一次，省掉你手动"停止再启动"
        if running:
            self._restart_kernel_worker()
        else:
            self.refresh_nodes()

    def _restart_kernel_worker(self):
        """后台重启内核：先停旧的，再起新的（让新配置生效）。"""
        old = self.kernel_proc

        def work():
            kernel.stop_kernel(old)
            return kernel.start_kernel()

        def on_ok(proc):
            self.kernel_proc = proc
            self._refresh_kernel_status()
            self.refresh_nodes()
            self._start_traffic_if_visible()
            self._start_log_if_visible()
            self._consume_tun_fallback()

        w = Worker(work)
        w.finished.connect(on_ok)
        w.error.connect(self._on_kernel_error)
        self._worker_restart = w
        w.start()

    def on_toggle_sub(self, sid, enabled):
        mgr = sub.SubscriptionManager()
        mgr.set_enabled(sid, enabled)
        # 启用状态变化后需重新生成配置，提示用户更新
        self.statusBar().showMessage(
            _("已修改，点\"更新全部\"使配置生效。",
              "Changed. Click 'Update All' to apply."), 4000)

    def on_delete_sub(self, sid):
        mgr = sub.SubscriptionManager()
        mgr.remove(sid)
        self.refresh_subs()

    # ===================== 节点页操作 =====================
    def on_group_changed(self, group_name):
        if not group_name:
            self.node_table.setRowCount(0)
            return
        try:
            nm = nodes.NodeManager()
            data = nm.api.get_proxies().get("proxies", {})
            # 找该组的候选节点（这步也要在内核在线时才行）
            names = []
            for g in nm.list_groups():
                if g["name"] == group_name:
                    names = g["all"]
                    break
        except Exception as e:
            self.node_table.setRowCount(0)
            self.node_status.setText(
                _("读取该策略组节点失败：%s" % str(e),
                  "Failed to read group nodes: %s" % str(e)))
            return
        self.node_table.setRowCount(len(names))
        for i, n in enumerate(names):
            self.node_table.setItem(i, 0, QTableWidgetItem(n))
            self.node_table.setItem(i, 1, QTableWidgetItem(
                data.get(n, {}).get("type", "")))
            self.node_table.setItem(i, 2, QTableWidgetItem(""))

    def on_test_all(self):
        group = self.group_combo.currentText()
        if not group:
            return
        names = []
        for r in range(self.node_table.rowCount()):
            names.append(self.node_table.item(r, 0).text())
        if not names:
            return
        nm = nodes.NodeManager()

        def work():
            return nm.test_all_delays(names)

        self._busy(_("正在测速…", "Testing…"))
        w = Worker(work)
        w.finished.connect(lambda d: self._fill_delays(d))
        w.error.connect(self._on_kernel_error)
        w.finished.connect(lambda _: self._idle())
        self._worker_test = w
        w.start()

    def _fill_delays(self, delays):
        for r in range(self.node_table.rowCount()):
            name = self.node_table.item(r, 0).text()
            d = delays.get(name)
            text = str(d) if d is not None else _("超时", "timeout")
            self.node_table.setItem(r, 2, QTableWidgetItem(text))

    def on_node_clicked(self, row, col):
        group = self.group_combo.currentText()
        if not group:
            return
        name = self.node_table.item(row, 0).text()
        try:
            nm = nodes.NodeManager()
            nm.select(group, name)
            QMessageBox.information(
                self, _("已切换", "Switched"),
                _("已将 %s 设为 %s" % (group, name),
                  "Set %s -> %s" % (group, name)))
        except Exception as e:
            QMessageBox.warning(self, _("失败", "Failed"), str(e))

    # ===================== 关于页 =====================
    def on_lang_changed(self, idx):
        lang = "zh" if idx == 0 else "en"
        set_lang(lang)
        settings = config.load_settings()
        settings["language"] = lang
        config.save_settings(settings)
        self._retranslate()
        if hasattr(self, "tray"):
            self.tray.retranslate()

    # ===================== 托盘相关 =====================
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def start_all(self):
        """托盘‘启动代理’：启动内核 + 开系统代理。"""
        if self.kernel_proc and kernel.is_running(self.kernel_proc):
            # 内核已经在跑，直接开系统代理即可
            proxy.enable_proxy()
            self._refresh_kernel_status()
            self._refresh_proxy_status()
            self.refresh_nodes()
            return
        self._busy(_("正在启动代理…", "Starting proxy…"))
        w = Worker(self._start_kernel_with_repair)
        def on_ok(proc):
            self.kernel_proc = proc
            proxy.enable_proxy()
            self._refresh_kernel_status()
            self._refresh_proxy_status()
            self.refresh_nodes()
            self._start_traffic_if_visible()
            self._start_log_if_visible()
            self._consume_tun_fallback()
        w.finished.connect(on_ok)
        w.error.connect(self._on_kernel_error)
        w.finished.connect(lambda _: self._idle())
        self._worker_kernel = w
        w.start()

    def stop_all(self):
        """托盘‘停止代理’：关系统代理 + 停内核。"""
        proxy.disable_proxy()
        if self.kernel_proc:
            kernel.stop_kernel(self.kernel_proc)
            self.kernel_proc = None
        self.traffic_monitor.stop()
        self._refresh_kernel_status()
        self._refresh_proxy_status()

    # ===================== 关窗最小化到托盘 =====================
    def closeEvent(self, event):
        event.ignore()          # 不真正关闭
        self.hide()             # 只隐藏窗口
        self.tray.showMessage(
            _("clashDP", "clashDP"),
            _("已最小化到托盘，右键图标可退出", "Minimized to tray, right-click to quit"),
            QSystemTrayIcon.Information)

    # ===================== 小工具 =====================
    def _busy(self, text):
        self.statusBar().showMessage(text)

    def _idle(self):
        self.statusBar().clearMessage()


# ---------------------------------------------------------------------------
# “添加订阅链接”对话框
# ---------------------------------------------------------------------------
class AddRemoteDialog(QDialog):
    """简单的三字段对话框：名称 / 链接 / 自动更新间隔。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QFormLayout, QLineEdit, QSpinBox, QDialogButtonBox
        self.setWindowTitle(_("添加订阅链接", "Add Subscription URL"))
        layout = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(0, 720)
        self.interval_spin.setValue(24)
        layout.addRow(_("名称：", "Name:"), self.name_edit)
        layout.addRow(_("链接：", "URL:"), self.url_edit)
        layout.addRow(_("自动更新间隔(小时,0=不自动)：", "Auto-update(h,0=off):"),
                     self.interval_spin)
        box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addRow(box)

    def get_data(self):
        return (self.name_edit.text().strip(),
                self.url_edit.text().strip(),
                self.interval_spin.value())
