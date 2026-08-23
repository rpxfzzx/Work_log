# -*- coding: utf-8 -*-
"""工作日志：Tkinter 图形界面。

双击 启动工作日志.bat，或执行 python worklog.py 运行。
"""
import datetime
import os
import re
import sys
import tkinter as tk
import webbrowser
import tkinter.font as tkfont
from tkinter import messagebox, ttk

import report
import storage


def _enable_dpi_awareness():
    """Windows 高 DPI（125%/150% 缩放）下 Tk 默认会被系统拉伸，界面发虚。
    声明为 per-monitor DPI aware 后由 Tk 自己按真实像素绘制，字体边缘清晰。
    非 Windows 或旧系统上静默跳过。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # Win 8.1+
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()        # Win 7 回退
    except Exception:
        pass


def _resource_path(name):
    """打包成 exe 后资源在解压目录，否则在项目目录。"""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(storage.BASE_DIR, name)


class WorkLogApp:
    # 状态下拉的文字颜色样式（与序号徽章颜色一致）
    STATUS_STYLE = {
        "已完成": "StatusDone.TCombobox",
        "进行中": "StatusDoing.TCombobox",
        "未开始": "StatusNone.TCombobox",
    }
    # 固定列宽（像素，表头与条目行共用，保证严格对齐）
    COL_SEQ, COL_STATUS, COL_DEL = 38, 112, 34

    def __init__(self, root, auto_setup=False):
        self.root = root
        self.data = storage.load_data()
        self.week_key = None       # 当前查看的周 key（周一日期字符串）
        self.current_date = None   # 当前查看的日期字符串
        self.row_widgets = []      # 条目行控件列表
        self.selected_row = None   # 选中的行（用于“删除选中行”）
        self._col_flex = (340, 260)  # 弹性列当前像素宽度（工作内容, 难点备注），随窗口宽度更新

        self._font_family = self._pick_font()
        self._setup_style()
        self._build_ui()

        self._select_initial_date(auto_setup)
        self.refresh_all()

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind("<Control-s>", lambda e: self.save_now(notify=True))
        root.bind("<Control-Return>", lambda e: (self.add_row(), "break")[1])
        root.bind("<Control-d>", lambda e: (self.delete_selected_row(), "break")[1])

    # ---------- 初始化 ----------

    def _pick_font(self):
        fams = set(tkfont.families(self.root))
        for f in ("Microsoft YaHei UI", "微软雅黑", "Microsoft YaHei", "Segoe UI"):
            if f in fams:
                return f
        return "TkDefaultFont"

    def _setup_style(self):
        self.root.title("工作日志 Work Log")
        self.root.geometry("1020x720")
        self.root.minsize(900, 620)
        style = ttk.Style()
        style.configure(".", font=(self._font_family, 10))
        style.configure("StatusDone.TCombobox", foreground="#375623")
        style.configure("StatusDoing.TCombobox", foreground="#1f4e79")
        style.configure("StatusNone.TCombobox", foreground="#595959")
        self._set_window_icon()

    def _set_window_icon(self):
        for name in ("logo_64.png", "logo.png"):
            try:
                self._icon_img = tk.PhotoImage(file=_resource_path(name))
                self.root.iconphoto(True, self._icon_img)
                return
            except tk.TclError:
                continue

    def _build_ui(self):
        f = self._font_family

        # ---- 标头：周范围 / 工作日总数 / 填写进度 ----
        top = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        self.lbl_header = ttk.Label(top, text="", font=(f, 10, "bold"))
        self.lbl_header.pack(side="left")
        ttk.Button(top, text="周设置", command=self.open_week_setup).pack(side="right", padx=(8, 0))
        ttk.Button(top, text="📅 历史记录", command=self.open_history).pack(side="right")

        # ---- 次标头：当前日期 / 周几 / 第几个工作日 ----
        sub = ttk.Frame(self.root, padding=(10, 4))
        sub.pack(fill="x")
        self.lbl_sub = ttk.Label(sub, text="", font=(f, 13, "bold"))
        self.lbl_sub.pack(side="left")
        self.var_done = tk.BooleanVar(value=False)
        self.chk_done = tk.Checkbutton(
            sub, text="今日记录已完成", variable=self.var_done,
            font=(f, 10), command=self._on_done_toggle)
        self.chk_done.pack(side="right")

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10)

        # ---- 表头 + 条目编辑区：共用同一网格列，表头与内容严格对齐 ----
        middle = tk.Frame(self.root)
        middle.pack(fill="both", expand=True, padx=10, pady=(0, 2))
        middle.columnconfigure(0, weight=1)
        middle.rowconfigure(1, weight=1)

        self._head = head = tk.Frame(middle, bg="#f5f5f5")
        head.grid(row=0, column=0, sticky="ew", padx=4)
        head.columnconfigure(1, minsize=self._col_flex[0])
        head.columnconfigure(3, minsize=self._col_flex[1])
        seq_head = tk.Frame(head, width=WorkLogApp.COL_SEQ, bg="#f5f5f5")
        seq_head.grid(row=0, column=0, pady=5, sticky="ns")
        seq_head.pack_propagate(False)
        tk.Label(seq_head, text="序号", bg="#f5f5f5", fg="#666666", font=(f, 9)).pack(anchor="center")
        tk.Label(head, text="工作内容", anchor="w", bg="#f5f5f5", fg="#666666", font=(f, 9)).grid(
            row=0, column=1, sticky="ew", padx=2)
        st_head = tk.Frame(head, width=WorkLogApp.COL_STATUS, bg="#f5f5f5")
        st_head.grid(row=0, column=2, pady=5, sticky="ns")
        st_head.pack_propagate(False)
        tk.Label(st_head, text="状态", anchor="w", bg="#f5f5f5", fg="#666666", font=(f, 9)).pack(
            fill="x", padx=(6, 0))
        tk.Label(head, text="难点备注", anchor="w", bg="#f5f5f5", fg="#666666", font=(f, 9)).grid(
            row=0, column=3, sticky="ew", padx=2)
        del_head = tk.Frame(head, width=WorkLogApp.COL_DEL, bg="#f5f5f5")
        del_head.grid(row=0, column=4, pady=5, sticky="ns")
        del_head.pack_propagate(False)

        container = tk.Frame(middle)
        container.grid(row=1, column=0, sticky="nsew")
        self.canvas = tk.Canvas(container, highlightthickness=0, bg="#ffffff")
        scroll = ttk.Scrollbar(middle, orient="vertical", command=self.canvas.yview)
        scroll.grid(row=0, column=1, rowspan=2, sticky="ns")
        self.table_frame = tk.Frame(self.canvas, bg="#ffffff")
        self.table_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        win = self.canvas.create_window((0, 0), window=self.table_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(fill="both", expand=True)
        middle.bind("<Configure>", self._update_flex_columns)
        self.canvas.bind(
            "<Enter>",
            lambda e: self.canvas.bind_all(
                "<MouseWheel>",
                lambda ev: self.canvas.yview_scroll(-int(ev.delta / 120), "units")))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        # ---- 下周计划 ----
        plan_frame = ttk.Frame(self.root, padding=(10, 2, 10, 0))
        plan_frame.pack(fill="x")
        ttk.Label(plan_frame, text="下周计划（写入周报第四部分）：").pack(anchor="w")
        self.txt_plan = tk.Text(plan_frame, height=3, font=(f, 10), wrap="word")
        self.txt_plan.pack(fill="x")
        self.txt_plan.bind("<FocusOut>", lambda e: self._save_plan())

        # ---- 按钮栏：左（条目操作）中（日期导航）右（生成周报），三段对称 ----
        btns = ttk.Frame(self.root, padding=(10, 4, 10, 2))
        btns.pack(fill="x")
        btns.columnconfigure(1, weight=1)
        left_grp = ttk.Frame(btns)
        left_grp.grid(row=0, column=0, sticky="w")
        center_grp = ttk.Frame(btns)
        center_grp.grid(row=0, column=1)
        right_grp = ttk.Frame(btns)
        right_grp.grid(row=0, column=2, sticky="e")
        ttk.Button(left_grp, text="＋ 添加一行", command=self.add_row).pack(side="left")
        ttk.Button(left_grp, text="删除选中行", command=self.delete_selected_row).pack(side="left", padx=(8, 0))
        ttk.Button(left_grp, text="⧉ 复制昨日", command=self.copy_prev_day).pack(side="left", padx=(8, 0))
        ttk.Button(center_grp, text="◀ 前一天", command=lambda: self.nav(-1)).pack(side="left")
        ttk.Button(center_grp, text="💾 保存当天", command=lambda: self.save_now(notify=True)).pack(
            side="left", padx=(8, 0))
        ttk.Button(center_grp, text="明天 ▶", command=lambda: self.nav(1)).pack(side="left", padx=(8, 0))
        ttk.Button(right_grp, text="📤 生成周报（上传）", command=self.open_report).pack(side="left")

        # ---- 状态栏：左消息右提示，两端对称 ----
        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10)
        status = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        status.pack(fill="x")
        self.lbl_status = ttk.Label(status, text="就绪", foreground="#595959")
        self.lbl_status.pack(side="left")
        ttk.Label(status, text="Ctrl+S 保存 · Ctrl+Enter 添加行 · Ctrl+D 删除选中行",
                  foreground="#9e9e9e").pack(side="right")

    def _update_flex_columns(self, event=None):
        """窗口宽度变化时，按实际像素同步表头与所有条目行的弹性列宽（保证严格对齐）。"""
        try:
            canvas_w = self.canvas.winfo_width()
        except (tk.TclError, AttributeError):
            return
        if canvas_w <= 1:
            return
        content = max(canvas_w - 8, 320)  # 行内容总宽（行/表头两侧各有 4px 内边距）
        fixed = WorkLogApp.COL_SEQ + WorkLogApp.COL_STATUS + WorkLogApp.COL_DEL
        w1 = max(80, int((content - fixed) * 0.6))
        w3 = max(80, content - fixed - w1)
        if (w1, w3) == self._col_flex:
            return
        self._col_flex = (w1, w3)
        self._head.columnconfigure(1, minsize=w1)
        self._head.columnconfigure(3, minsize=w3)
        for rw in self.row_widgets:
            rw["frame"].columnconfigure(1, minsize=w1)
            rw["frame"].columnconfigure(3, minsize=w3)

    # ---------- 周 / 日期管理 ----------

    def week(self):
        return storage.get_week(self.data, self.week_key) if self.week_key else None

    def _select_initial_date(self, auto_setup):
        """启动时定位到今天；今天所在周未设置则弹周设置（auto_setup 时静默建默认周）。"""
        today = datetime.date.today()
        key = storage.format_date(storage.monday_of(today))
        week = self.data["weeks"].get(key)
        if week and week.get("workdays"):
            wd = week["workdays"]
            today_s = storage.format_date(today)
            self.week_key = key
            self.current_date = today_s if today_s in wd else (wd[-1] if today_s > wd[-1] else wd[0])
            return
        if auto_setup:
            self._create_default_week(key, today)
            self._status_msg("本周尚未设置，已按默认（周一至周五）创建，可点“周设置”修改。")
        else:
            self.root.after(150, self._setup_week_interactive)

    def _setup_week_interactive(self):
        today = datetime.date.today()
        key = storage.format_date(storage.monday_of(today))
        week = self.data["weeks"].get(key)
        if week and week.get("workdays"):
            wd = week["workdays"]
            today_s = storage.format_date(today)
            self.week_key = key
            self.current_date = today_s if today_s in wd else (wd[-1] if today_s > wd[-1] else wd[0])
            self.refresh_all()
            return
        if not self.open_week_setup(default_date=today):
            self._create_default_week(key, today)
            self._status_msg("本周尚未设置，已按默认（周一至周五）创建，可点“周设置”修改。")
        self.refresh_all()

    def _create_default_week(self, key, start_date):
        flags = [True, True, True, True, True, False, False]
        wd = storage.make_workdays(start_date, flags)
        is_new = key not in self.data["weeks"]
        self.data["weeks"].setdefault(
            key, {"start_date": key, "workdays": wd, "next_week_plan": "", "days": {}})
        self.week_key = key
        today_s = storage.format_date(start_date)
        self.current_date = today_s if today_s in wd else (wd[-1] if wd else today_s)
        if is_new:
            self._carry_over_from_prev_week(key)
        storage.save_data(self.data)

    def _carry_over_from_prev_week(self, key):
        """新建一周时，把上一周未收尾的事项自动带入第一个工作日（状态原样保留）。
        返回带入条数；该日已有记录时不做任何事，避免覆盖。"""
        prev_keys = sorted(k for k in self.data["weeks"] if k < key)
        if not prev_keys:
            return 0
        prev = self.data["weeks"][prev_keys[-1]]
        carry = report.unfinished_items(prev)
        if not carry:
            return 0
        week = storage.get_week(self.data, key)
        wd = week.get("workdays", [])
        if not wd:
            return 0
        first = storage.get_day(week, wd[0])
        if first.get("items"):
            return 0
        first["items"] = [dict(it) for it in carry]
        return len(carry)

    def _find_neighbor_week(self, delta):
        keys = sorted(self.data["weeks"])
        if not keys or self.week_key not in keys:
            return None
        i = keys.index(self.week_key) + delta
        return keys[i] if 0 <= i < len(keys) else None

    def nav(self, delta):
        """前后切换工作日，跨周自动跳转相邻周。"""
        self.collect_and_save()
        week = self.week()
        wd = week.get("workdays", []) if week else []
        idx = wd.index(self.current_date) if self.current_date in wd else -1
        target = idx + delta
        if 0 <= target < len(wd):
            self.current_date = wd[target]
        else:
            nxt = self._find_neighbor_week(delta)
            nwd = self.data["weeks"][nxt].get("workdays", []) if nxt else []
            if not nwd:
                messagebox.showinfo("提示", "已经是第一个/最后一个工作日了。", parent=self.root)
                return
            self.week_key = nxt
            self.current_date = nwd[-1] if delta < 0 else nwd[0]
        self.refresh_all()

    # ---------- 条目编辑 ----------

    def _clear_rows(self):
        for rw in self.row_widgets:
            rw["frame"].destroy()
        self.row_widgets = []
        self.selected_row = None

    @staticmethod
    def _needed_lines(tw, text):
        """按字体测量计算文本在 Text 当前像素宽度下的显示行数（1~6 截断）。
        Tk 的 count -displaylines 在布局时序下会返回错误值（虚高或漏行），
        因此改用 Tcl font measure 纯测量折行：优先在空白处断，超宽片段二分按字符硬断，
        与 wrap="word" 视觉一致。"""
        try:
            avail = tw.winfo_width() - 8  # 减去边框与内部边缘余量，略保守避免截断
        except tk.TclError:
            return 1
        if avail <= 0:
            return 1

        def measure(s):
            return int(tw.tk.call("font", "measure", tw.cget("font"), s))

        lines = 0
        for line in text.split("\n"):
            if not line:
                lines += 1
                continue
            cur = ""
            for part in re.split(r"(\s+)", line):
                if measure(cur + part) <= avail:
                    cur += part
                    continue
                if cur:
                    lines += 1
                cur = part  # 注意：cur 为空时也必须承接 part，否则超宽片段被丢弃
                while measure(cur) > avail:  # 单个超宽片段按字符硬断（二分找最大可放前缀）
                    lo, hi, best = 1, len(cur), 0
                    while lo <= hi:
                        mid = (lo + hi) // 2
                        if measure(cur[:mid]) <= avail:
                            best = mid
                            lo = mid + 1
                        else:
                            hi = mid - 1
                    lines += 1
                    cur = cur[max(best, 1):]
            if cur:
                lines += 1
        return max(1, min(6, lines))

    @staticmethod
    def _autosize_text(tw):
        """按内容自动调整 Text 高度（1~6 行）。布局完成前（宽度仍是 1 字符宽）跳过，
        等 <Configure> 事件以真实宽度重算。"""
        try:
            if tw.winfo_width() <= 50:
                return
        except tk.TclError:
            return
        h = WorkLogApp._needed_lines(tw, tw.get("1.0", "end-1c"))
        if int(tw.cget("height")) != h:
            tw.config(height=h)

    def add_row(self, content="", status="未开始", difficulty=""):
        """新增一行条目：彩色序号徽章 + 可换行的多行内容框（列宽与表头严格一致）。"""
        f = self._font_family
        idx = len(self.row_widgets)
        frm = tk.Frame(self.table_frame, bg="#ffffff")
        frm.pack(fill="x", padx=4, pady=2)
        frm.columnconfigure(1, minsize=self._col_flex[0])
        frm.columnconfigure(3, minsize=self._col_flex[1])

        badge_box = tk.Frame(frm, width=WorkLogApp.COL_SEQ, bg="#ffffff")
        badge_box.grid(row=0, column=0, sticky="ns", pady=3)
        badge_box.pack_propagate(False)
        badge = tk.Label(badge_box, text=f"{idx + 1}.", fg="#ffffff",
                         bg=report.STATUS_TEXT_COLORS.get(status, "#595959"),
                         font=(f, 9, "bold"))
        badge.pack(fill="both", expand=True)

        txt_c = tk.Text(frm, font=(f, 10), height=1, width=1, wrap="word", undo=False,
                        borderwidth=1, relief="solid", highlightthickness=1,
                        highlightbackground="#d9d9d9", highlightcolor="#9e9e9e")
        txt_c.grid(row=0, column=1, sticky="ew", padx=2, pady=3)
        txt_c.insert("1.0", content)

        status_box = tk.Frame(frm, width=WorkLogApp.COL_STATUS, bg="#ffffff")
        status_box.grid(row=0, column=2, sticky="ns", pady=3)
        status_box.pack_propagate(False)
        var_s = tk.StringVar(value=status)
        combo = ttk.Combobox(status_box, textvariable=var_s, values=storage.STATUSES,
                             state="readonly", width=8, font=(f, 10),
                             style=WorkLogApp.STATUS_STYLE.get(status, "StatusNone.TCombobox"))
        combo.pack(fill="x", padx=2)

        txt_d = tk.Text(frm, font=(f, 10), height=1, width=1, wrap="word", undo=False,
                        borderwidth=1, relief="solid", highlightthickness=1,
                        highlightbackground="#d9d9d9", highlightcolor="#9e9e9e")
        txt_d.grid(row=0, column=3, sticky="ew", padx=2, pady=3)
        txt_d.insert("1.0", difficulty)

        del_box = tk.Frame(frm, width=WorkLogApp.COL_DEL, bg="#ffffff")
        del_box.grid(row=0, column=4, sticky="ns", pady=3)
        del_box.pack_propagate(False)
        btn_del = ttk.Button(del_box, text="✕", width=3)
        btn_del.pack(anchor="center")

        rw = {"frame": frm, "badge": badge, "content": txt_c, "status": var_s,
              "combo": combo, "diff": txt_d, "btn": btn_del,
              "boxes": (badge_box, status_box, del_box)}
        btn_del.config(command=lambda rw=rw: self.delete_row_by_ref(rw))
        var_s.trace_add("write", lambda *a, rw=rw: self._on_status_change(rw))
        for w in (frm, badge_box, txt_c, status_box, txt_d, del_box):
            w.bind("<Button-1>", lambda e, rw=rw: self._select_row(rw), add="+")
        for w in (txt_c, txt_d):
            # 注意：lambda 必须用默认参数捕获 w，否则循环结束后 w 恒为 txt_d，
            # 会导致工作内容框的事件实际调整难点备注框的高度
            w.bind("<FocusOut>", lambda e: self.collect_and_save())
            w.bind("<KeyRelease>", lambda e, w=w: self._autosize_text(w))
            w.bind("<Configure>", lambda e, w=w: self._autosize_text(w))
        self.row_widgets.append(rw)
        self._autosize_text(txt_c)
        self._autosize_text(txt_d)
        return rw

    def _apply_row_color(self, rw, highlight=False):
        bg = "#cce5ff" if highlight else "#ffffff"
        rw["frame"].config(bg=bg)
        for box in rw.get("boxes", ()):
            box.config(bg=bg)

    def _select_row(self, rw):
        if self.selected_row is rw:
            return
        if self.selected_row:
            self._apply_row_color(self.selected_row, highlight=False)
        self.selected_row = rw
        self._apply_row_color(rw, highlight=True)

    def _on_status_change(self, rw):
        s = rw["status"].get()
        rw["badge"].config(bg=report.STATUS_TEXT_COLORS.get(s, "#595959"))
        rw["combo"].config(style=WorkLogApp.STATUS_STYLE.get(s, "StatusNone.TCombobox"))
        self.collect_and_save()

    def _renumber(self):
        for i, rw in enumerate(self.row_widgets, 1):
            rw["badge"].config(text=f"{i}.")

    def delete_row_by_ref(self, rw):
        self.row_widgets.remove(rw)
        rw["frame"].destroy()
        if self.selected_row is rw:
            self.selected_row = None
        self._renumber()
        self.collect_and_save()

    def delete_selected_row(self):
        if self.selected_row:
            self.delete_row_by_ref(self.selected_row)
        elif self.row_widgets:
            self.delete_row_by_ref(self.row_widgets[-1])
        else:
            self._status_msg("当前没有可删除的条目。")

    def copy_prev_day(self):
        """把上一个工作日的条目复制到当天（已完成的不再复制，其余状态原样保留）。"""
        if not self.current_date:
            return
        self.collect_and_save()
        prev = storage.prev_workday(self.data, self.week_key, self.current_date)
        if not prev:
            self._status_msg("没有找到上一个工作日的记录。")
            return
        pweek = storage.get_week(self.data, prev[0])
        items = [it for it in storage.peek_day(pweek, prev[1]).get("items", [])
                 if (it.get("status") or "未开始") != "已完成"
                 and ((it.get("content") or "").strip() or (it.get("difficulty") or "").strip())]
        if not items:
            self._status_msg(f"{storage.short_date(prev[1])} 没有可承接的未完成条目。")
            return
        exist = {report.norm_content(rw["content"].get("1.0", "end-1c")) for rw in self.row_widgets}
        added = 0
        for it in items:
            if report.norm_content(it.get("content")) in exist:
                continue     # 已有同名条目 → 跳过，避免重复
            self.add_row(it.get("content", ""), it.get("status") or "未开始",
                         it.get("difficulty", ""))
            added += 1
        self.collect_and_save()
        self.root.after_idle(self._reautosize_rows)
        self._status_msg(f"已从 {storage.short_date(prev[1])} 复制 {added} 条未完成条目"
                         + ("（其余为重复项已跳过）" if added < len(items) else ""))

    # ---------- 数据读写 ----------

    def collect_current_day(self):
        """把编辑区内容写回当前日期数据（空白条目自动丢弃）。"""
        if not self.current_date:
            return None
        week = self.week()
        if not week:
            return None
        day = storage.get_day(week, self.current_date)
        items = []
        for rw in self.row_widgets:
            content = rw["content"].get("1.0", "end-1c").strip()
            diff = rw["diff"].get("1.0", "end-1c").strip()
            if content or diff:
                items.append({"content": content, "status": rw["status"].get(), "difficulty": diff})
        day["items"] = items
        day["done"] = bool(self.var_done.get())
        return day

    def _save_plan(self):
        if not hasattr(self, "txt_plan"):
            return
        week = self.week()
        if week is not None:
            week["next_week_plan"] = self.txt_plan.get("1.0", "end-1c")

    def collect_and_save(self):
        if self.current_date:
            self.collect_current_day()
        self._save_plan()
        storage.save_data(self.data)

    def save_now(self, notify=True):
        self.collect_and_save()
        if notify and self.current_date:
            self._status_msg(f"已保存（{storage.short_date(self.current_date)} "
                             f"{storage.weekday_cn(self.current_date)}）")

    def _on_close(self):
        self.collect_and_save()
        self.root.destroy()

    # ---------- 界面刷新 ----------

    def refresh_all(self):
        """重建当前日期的全部显示。"""
        self._clear_rows()
        self.var_done.set(False)
        week = self.week()
        if week and self.current_date:
            wd = week.get("workdays", [])
            day = storage.get_day(week, self.current_date)
            pos = wd.index(self.current_date) + 1 if self.current_date in wd else 0
            text = f"{storage.short_date(self.current_date)} {storage.weekday_cn(self.current_date)}"
            if pos:
                text += f" · 第 {pos}/{len(wd)} 个工作日"
            self.lbl_sub.config(text=text)
            for it in day.get("items", []):
                self.add_row(it.get("content", ""), it.get("status") or "未开始",
                             it.get("difficulty", ""))
            self.var_done.set(bool(day.get("done")))
        else:
            self.lbl_sub.config(text="尚未设置工作日，请点击右上角“周设置”")
        self._refresh_header()
        self._refresh_plan_field()
        # 行刚重建时宽度尚未布局，等布局完成后再统一重算各框高度（与 <Configure> 双保险）
        self.root.after_idle(self._reautosize_rows)

    def _reautosize_rows(self):
        for rw in self.row_widgets:
            self._autosize_text(rw["content"])
            self._autosize_text(rw["diff"])

    def _refresh_header(self):
        week = self.week()
        if not week or not week.get("workdays"):
            self.lbl_header.config(text="尚未设置工作日")
            return
        wd = week["workdays"]
        filled = sum(1 for d in wd if storage.peek_day(week, d).get("done"))
        self.lbl_header.config(
            text=f"{storage.week_range_label(week)} · 本周共 {len(wd)} 个工作日 · "
                 f"已填写 {filled}/{len(wd)} 天")

    def _refresh_plan_field(self):
        if not hasattr(self, "txt_plan"):
            return
        week = self.week()
        new = week.get("next_week_plan", "") if week else ""
        cur = self.txt_plan.get("1.0", "end-1c")
        if cur != new:
            self.txt_plan.delete("1.0", "end")
            self.txt_plan.insert("1.0", new)

    def _status_msg(self, text):
        self.lbl_status.config(text=text)

    def _on_done_toggle(self):
        """勾选“今日记录已完成”后自动进入明日（功能 2）。"""
        self.collect_and_save()
        self._refresh_header()
        if self.var_done.get():
            week = self.week()
            wd = week.get("workdays", []) if week else []
            i = wd.index(self.current_date) if self.current_date in wd else -1
            if 0 <= i < len(wd) - 1:
                self.nav(1)
                self._status_msg(f"今日记录已完成，已进入 {storage.short_date(self.current_date)} "
                                 f"{storage.weekday_cn(self.current_date)}")
            else:
                self._status_msg("本周全部记录完成！可以生成周报了 🎉")

    # ---------- 周设置对话框 ----------

    def open_week_setup(self, default_date=None):
        """周设置对话框。返回 True 表示已设置，False 表示取消。"""
        if default_date is None:
            default_date = (storage.parse_date(self.current_date)
                            if self.current_date else datetime.date.today())
        f = self._font_family
        win = tk.Toplevel(self.root)
        win.title("周设置：工作日安排")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        self._setup_result = False

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        row0 = ttk.Frame(frm)
        row0.pack(fill="x", pady=4)
        ttk.Label(row0, text="汇报人：").pack(side="left")
        self._setup_var_reporter = tk.StringVar(
            value=self.data.get("settings", {}).get("reporter", ""))
        tk.Entry(row0, textvariable=self._setup_var_reporter, width=14, font=(f, 10)).pack(side="left")
        ttk.Label(row0, text="（可留空；填写后会显示在周报标题下方）").pack(side="left", padx=6)

        row1 = ttk.Frame(frm)
        row1.pack(fill="x", pady=4)
        ttk.Label(row1, text="起始日期：").pack(side="left")
        self._setup_var_date = tk.StringVar(value=storage.format_date(default_date))
        tk.Entry(row1, textvariable=self._setup_var_date, width=14, font=(f, 10)).pack(side="left")
        ttk.Label(row1, text="（自动取该日所在周的周一，格式 YYYY-MM-DD）").pack(side="left", padx=6)

        ttk.Label(frm, text="选择工作日：").pack(anchor="w", pady=(10, 2))
        row2 = ttk.Frame(frm)
        row2.pack(fill="x")
        self._setup_vars = []
        defaults = [True, True, True, True, True, False, False]
        for i, name in enumerate(storage.WEEKDAY_NAMES):
            v = tk.BooleanVar(value=defaults[i])
            v.trace_add("write", lambda *a: self._update_setup_preview())
            tk.Checkbutton(row2, text=name, variable=v, font=(f, 10)).pack(side="left", padx=4)
            self._setup_vars.append(v)
        self._setup_lbl_preview = ttk.Label(frm, text="", foreground="#1f4e79")
        self._setup_lbl_preview.pack(anchor="w", pady=(8, 0))
        self._update_setup_preview()

        row3 = ttk.Frame(frm)
        row3.pack(fill="x", pady=(12, 0))
        ttk.Button(row3, text="确定", command=lambda: self._confirm_week_setup(win)).pack(
            side="left", padx=(0, 8))
        ttk.Button(row3, text="取消", command=win.destroy).pack(side="left")

        self.root.wait_window(win)
        return self._setup_result

    def _update_setup_preview(self):
        try:
            d = storage.parse_date(self._setup_var_date.get())
            flags = [v.get() for v in self._setup_vars]
            wd = storage.make_workdays(d, flags)
            parts = [f"{storage.short_date(w)} {storage.weekday_cn(w)}" for w in wd]
            self._setup_lbl_preview.config(
                text="将生成工作日：" + ("、".join(parts) if parts else "（未勾选任何一天）"))
        except (ValueError, AttributeError, tk.TclError):
            self._setup_lbl_preview.config(text="日期格式无效")

    def _confirm_week_setup(self, win):
        try:
            d = storage.parse_date(self._setup_var_date.get())
        except ValueError:
            messagebox.showerror("日期格式错误", "请按 YYYY-MM-DD 格式输入日期，例如 2026-08-19。", parent=win)
            return
        flags = [v.get() for v in self._setup_vars]
        if not any(flags):
            messagebox.showerror("未选择工作日", "请至少勾选一个工作日。", parent=win)
            return
        wd = storage.make_workdays(d, flags)
        key = storage.format_date(storage.monday_of(d))
        is_new = key not in self.data["weeks"]
        week = self.data["weeks"].setdefault(
            key, {"start_date": key, "workdays": [], "next_week_plan": "", "days": {}})
        week["workdays"] = wd
        self.data.setdefault("settings", {})["reporter"] = self._setup_var_reporter.get().strip()
        carried = self._carry_over_from_prev_week(key) if is_new else 0
        storage.save_data(self.data)
        self._setup_result = True
        win.destroy()
        if self.week_key != key:
            self.week_key = key
            self.current_date = wd[0]
        elif self.current_date not in wd:
            self.current_date = wd[0]
        self.refresh_all()
        msg = f"已设置 {storage.week_range_label(week)}，共 {len(wd)} 个工作日"
        if carried:
            msg += f"；已自动带入上周未完成事项 {carried} 条"
        self._status_msg(msg)

    # ---------- 历史记录对话框 ----------

    def open_history(self):
        # 打开前先落盘：窗口里的跳转/删除都会重建界面，未保存的编辑否则会丢失
        self.collect_and_save()
        f = self._font_family
        win = tk.Toplevel(self.root)
        win.title("历史记录（双击跳转）")
        win.transient(self.root)
        win.grab_set()          # 模态：避免开出多个历史窗口各自改数据
        win.geometry("460x540")
        lb = tk.Listbox(win, font=(f, 10), activestyle="dotbox")
        lb.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        mapping = []  # ("week", key) 或 ("day", key, 日期)

        def fill():
            lb.delete(0, "end")
            mapping.clear()
            for key in sorted(self.data["weeks"], reverse=True):
                week = self.data["weeks"][key]
                lb.insert("end", f"▍ {storage.week_range_label(week)}（{len(week.get('workdays', []))} 个工作日）")
                mapping.append(("week", key))
                for d in week.get("workdays", []):
                    day = week.get("days", {}).get(d, {})
                    n = len(day.get("items", []))
                    mark = "✓" if day.get("done") else ("·" if n else " ")
                    lb.insert("end", f"    {storage.short_date(d)} {storage.weekday_cn(d)}   {mark}  {n} 条记录")
                    mapping.append(("day", key, d))

        def selected():
            sel = lb.curselection()
            return mapping[sel[0]] if sel else None

        def go():
            item = selected()
            if item and item[0] == "day":
                self.collect_and_save()   # 跳转前保存当前编辑
                self.week_key, self.current_date = item[1], item[2]
                self.refresh_all()
                win.destroy()

        def delete_day():
            item = selected()
            if not item or item[0] != "day":
                messagebox.showinfo("提示", "请先选中某个日期（有缩进的行）。", parent=win)
                return
            _, key, d = item
            label = f"{storage.short_date(d)} {storage.weekday_cn(d)}"
            if not messagebox.askyesno("确认删除",
                                       f"确认删除 {label} 的全部记录吗？\n此操作不可恢复。",
                                       parent=win):
                return
            self.collect_and_save()
            storage.snapshot("del_day")   # 删除前留快照，可从 data/backup/ 取回
            self.data["weeks"][key]["days"].pop(d, None)
            storage.save_data(self.data)
            if self.week_key == key:
                self.refresh_all()
            fill()
            self._status_msg(f"已删除 {label} 的记录（如需恢复见 data/backup/）")

        def delete_week():
            item = selected()
            if not item or item[0] != "week":
                messagebox.showinfo("提示", "请先选中要删除的整周（▍开头的一行）。", parent=win)
                return
            key = item[1]
            week = self.data["weeks"][key]
            label = storage.week_range_label(week)
            if not messagebox.askyesno("确认删除",
                                       f"确认删除整周 {label} 的记录和工作日设置吗？\n此操作不可恢复。",
                                       parent=win):
                return
            self.collect_and_save()
            storage.snapshot("del_week")  # 删除前留快照，可从 data/backup/ 取回
            self.data["weeks"].pop(key, None)
            storage.save_data(self.data)
            if self.week_key == key:
                self.week_key = None
                self.current_date = None
                self.refresh_all()
            fill()
            self._status_msg(f"已删除整周 {label}（如需恢复见 data/backup/）")

        fill()
        btns = ttk.Frame(win, padding=(8, 0, 8, 8))
        btns.pack(fill="x")
        ttk.Button(btns, text="跳转到该日", command=go).pack(side="left")
        ttk.Button(btns, text="删除该日记录", command=delete_day).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="删除整周", command=delete_week).pack(side="left", padx=(8, 0))
        lb.bind("<Double-Button-1>", lambda e: go())

    # ---------- 周报 ----------

    def open_report(self):
        self.collect_and_save()
        week = self.week()
        if not week or not week.get("workdays"):
            messagebox.showwarning("无法生成周报", "本周尚未设置工作日，请先点击“周设置”。", parent=self.root)
            return
        wd = week["workdays"]
        filled = sum(1 for d in wd if storage.peek_day(week, d).get("done"))
        if filled < len(wd):
            if not messagebox.askyesno(
                    "尚未全部填写",
                    f"本周还有 {len(wd) - filled} 天未标记完成，仍要生成周报吗？",
                    parent=self.root):
                return
        ReportDialog(self.root, self, self.data, week)


class ReportDialog:
    """周报预览与导出对话框。"""

    def __init__(self, parent, app, data, week):
        self.app = app
        self.data = data
        self.week = week
        f = app._font_family

        self.win = tk.Toplevel(parent)
        self.win.title("周报预览与导出")
        self.win.transient(parent)
        self.win.grab_set()
        self.win.geometry("780x680")
        self.win.minsize(640, 520)

        top = ttk.Frame(self.win, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text=report.report_title(week), font=(f, 12, "bold")).pack(anchor="w")
        ttk.Label(top, text=report.overview_sentence(week), foreground="#595959").pack(
            anchor="w", pady=(2, 0))

        body = ttk.Frame(self.win, padding=(10, 6))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="纯文本预览（可直接修改，改完点「💾 保存修改」回写到记录，HTML 版同步生效）：").pack(anchor="w")
        self.txt = tk.Text(body, font=(f, 10), wrap="word", undo=True)
        self.txt.pack(fill="both", expand=True, pady=(2, 6))
        draft = week.get("report_draft")
        self.txt.insert("1.0", draft if draft else report.build_plain(data, week))

        btns = ttk.Frame(self.win, padding=(10, 0, 10, 4))
        btns.pack(fill="x")
        ttk.Button(btns, text="💾 保存修改", command=self._save_and_apply).pack(side="left")
        ttk.Button(btns, text="📋 复制 HTML（粘贴到 Outlook）", command=self._copy_html).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="导出 HTML 文件", command=self._export_html).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="浏览器预览", command=self._preview_browser).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="导出纯文本", command=self._export_txt).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="用 Outlook 打开邮件", command=self._open_outlook).pack(side="left", padx=(8, 0))

        self.lbl_status = ttk.Label(
            self.win,
            text="HTML 版为带样式表格，粘贴到 Outlook 正文不变形；纯文本版可在上方预览中修改。",
            foreground="#595959", padding=(10, 0, 10, 8))
        self.lbl_status.pack(fill="x")

    def _msg(self, text):
        self.lbl_status.config(text=text)

    def _save_and_apply(self):
        """把预览里的修改解析回写记录并落盘；解析不出明细时保存为草稿（下次打开恢复）。

        回写是覆盖式的，所以先做影响评估并让用户确认：
        某天一条都没解析出来（多半是格式被改坏了）会跳过该天、保留原记录。
        """
        text = self.txt.get("1.0", "end-1c")
        info = report.plain_back_summary(self.week, text)
        if info["items"]:
            tips = [f"将回写 {info['days']} 天共 {info['items']} 条记录（覆盖这些天的原有条目）。"]
            if info["skipped"]:
                tips.append("以下日期未能从文本解析出条目，将保留原记录不做修改：\n  "
                            + "、".join(storage.short_date(d) for d in info["skipped"])
                            + "\n（通常是「1. 内容 —— 状态」这一行的格式被改动了）")
            tips.append("原数据已自动备份到 data/backup/。确认继续？")
            if not messagebox.askyesno("确认回写", "\n\n".join(tips), parent=self.win):
                self._msg("已取消回写，记录未改动。")
                return
            storage.snapshot("report_writeback")
        n = report.apply_plain_back(self.week, text)
        if n:
            self.week.pop("report_draft", None)  # 修改已进数据，草稿不再需要
            storage.save_data(self.data)
            self.app.collect_and_save()
            self.app.refresh_all()
            msg = f"✅ 已保存修改并回写 {n} 条记录，HTML 版与纯文本版同步生效。"
            if info["skipped"]:
                msg += f"（{len(info['skipped'])} 天格式无法解析，已保留原记录）"
            self._msg(msg)
        else:
            self.week["report_draft"] = text
            storage.save_data(self.data)
            self._msg("✅ 已保存为草稿（未能从文本解析出明细，复制 HTML 仍按原数据生成；"
                      "导出纯文本 / Outlook 邮件会使用当前修改后的内容。）")

    def _copy_html(self):
        ok, err = report.copy_html_to_clipboard(report.build_html(self.data, self.week))
        if ok:
            self._msg("✅ 已复制到剪贴板，到 Outlook 邮件正文按 Ctrl+V 即可（表格样式保持不变）。")
        else:
            messagebox.showerror("复制失败", err, parent=self.win)

    def _export_html(self):
        path = report.export_file(self.data, self.week, "html")
        self._msg(f"✅ 已导出：{path}")

    def _preview_browser(self):
        try:
            path = report.export_file(self.data, self.week, "html")
            # 用 webbrowser 而非 os.startfile：后者只存在于 Windows，其他平台会 AttributeError
            webbrowser.open("file:///" + os.path.abspath(path).replace(os.sep, "/"))
            self._msg(f"✅ 已在浏览器打开：{path}")
        except (OSError, webbrowser.Error) as e:
            messagebox.showerror("打开失败", str(e), parent=self.win)

    def _export_txt(self):
        path = report.export_file(self.data, self.week, "txt",
                                  custom_text=self.txt.get("1.0", "end-1c"))
        self._msg(f"✅ 已导出：{path}")

    def _open_outlook(self):
        ok, err = report.outlook_available()
        if not ok:
            messagebox.showerror("无法调用 Outlook", err, parent=self.win)
            return
        subject = report.report_title(self.week)
        try:
            report.open_in_outlook(subject,
                                   report.build_html(self.data, self.week, full_document=True),
                                   self.txt.get("1.0", "end-1c"))
            self._msg("✅ 已在 Outlook 中打开周报邮件，可编辑后发送。")
        except Exception as e:
            messagebox.showerror("调用 Outlook 失败", str(e), parent=self.win)


def main():
    if "--smoke" in sys.argv:
        # 打包后的 exe 自检：工作日志.exe --smoke
        run_smoke(os.path.join(os.environ.get("TEMP", "."), "worklog_smoke_exe"))
        return
    _enable_dpi_awareness()
    root = tk.Tk()
    WorkLogApp(root)
    root.mainloop()


def run_smoke(data_dir):
    """自动化冒烟测试：临时数据目录下构建界面、添加条目、保存、生成周报。"""
    import shutil
    shutil.rmtree(data_dir, ignore_errors=True)
    os.makedirs(data_dir, exist_ok=True)
    storage.DATA_DIR = data_dir
    storage.DATA_FILE = os.path.join(data_dir, "worklog.json")
    storage.BACKUP_DIR = os.path.join(data_dir, "backup")
    root = tk.Tk()
    app = WorkLogApp(root, auto_setup=True)
    root.update_idletasks()
    root.update()
    assert app.week_key and app.current_date, "初始周/日期未就绪"
    app.add_row("完成登录模块开发", "已完成", "")
    app.add_row("支付接口联调\n与供应商核对验签逻辑", "进行中", "签名验签报错\n待供应商反馈")
    app.collect_and_save()
    week = app.week()
    day = storage.get_day(week, app.current_date)
    assert len(day["items"]) == 2, f"条目未保存：{day}"
    assert day["items"][0]["content"] == "完成登录模块开发"
    assert "\n" in day["items"][1]["content"], "多行内容未保存"
    stats, diffs = report.collect_stats(week)
    assert stats["total"] == 2 and stats["doing"] == 1 and len(diffs) == 1, stats
    html = report.build_html(app.data, week)
    assert "<table" in html, "HTML 缺少表格"
    assert "class=" not in html, "HTML 含 class 样式，Outlook 可能变形"
    assert "<br>" in html, "多行内容未转换为 <br>"
    plain = report.build_plain(app.data, week)
    assert "一、本周工作概述" in plain and "四、下周计划" in plain
    # 复制昨日：先造一条前一日记录，再验证只承接未完成条目且不重复
    wd = week["workdays"]
    i_today = wd.index(app.current_date)
    if i_today > 0:
        prev_d = wd[i_today - 1]
        storage.get_day(week, prev_d)["items"] = [
            {"content": "昨日已完成的活", "status": "已完成", "difficulty": ""},
            {"content": "昨日待续的活", "status": "进行中", "difficulty": "缺接口文档"},
            {"content": "完成登录模块开发", "status": "进行中", "difficulty": ""}]
        app.current_date = wd[i_today]
        app.copy_prev_day()
        contents = [rw["content"].get("1.0", "end-1c") for rw in app.row_widgets]
        assert "昨日待续的活" in contents, contents
        assert "昨日已完成的活" not in contents, "已完成条目不应被复制"
        assert contents.count("完成登录模块开发") == 1, "重复条目未去重"
        app.delete_row_by_ref(app.row_widgets[-1])
        app.collect_and_save()
    # 跨日关联：周一「进行中」→ 周三同内容「已完成」→ 归入已完成，不进下周计划草拟
    fake_week = {"start_date": "2026-08-17",
                 "workdays": ["2026-08-17", "2026-08-18", "2026-08-19"],
                 "next_week_plan": "", "days": {
                     "2026-08-17": {"done": True, "items": [
                         {"content": "跨日关联测试事项", "status": "进行中", "difficulty": ""}]},
                     "2026-08-19": {"done": True, "items": [
                         {"content": "跨日关联测试事项", "status": "已完成", "difficulty": ""}]}}}
    stats, diffs = report.collect_stats(fake_week)
    assert stats["total"] == 2 and stats["done"] == 2 and stats["doing"] == 0, stats
    assert stats["merged"] == {("2026-08-17", 0): "2026-08-19"}, stats["merged"]
    # 去重口径：同一件事跨两天记录，概述只算 1 项
    assert stats["unique"]["total"] == 1 and stats["unique"]["done"] == 1, stats["unique"]
    assert "推进事项 1 项" in report.overview_sentence(fake_week), \
        report.overview_sentence(fake_week)
    assert "已于" in report.build_html(app.data, fake_week), "HTML 明细缺关联注记"
    assert "已于" in report.build_plain(app.data, fake_week), "纯文本明细缺关联注记"
    assert "跨日关联测试事项" not in report.next_week_plan(fake_week), "已收尾事项不应进下周计划"
    # 预览文本解析回写：修改内容后应写回数据（HTML 版同步生效）
    fake_plain = report.build_plain(app.data, fake_week)
    changed = fake_plain.replace("跨日关联测试事项", "跨日关联测试事项（升级版）")
    n = report.apply_plain_back(fake_week, changed)
    assert n == 2, f"回写条目数应为 2：{n}"
    assert fake_week["days"]["2026-08-17"]["items"][0]["content"] == "跨日关联测试事项（升级版）"
    assert fake_week["days"]["2026-08-19"]["items"][0]["content"] == "跨日关联测试事项（升级版）"
    # 回写保护：某天格式被改坏（解析不出条目）时保留原记录，不得清空
    broken = report.build_plain(app.data, fake_week).replace(
        "1. 跨日关联测试事项（升级版） —— 进行中", "1、跨日关联测试事项（升级版）：进行中")
    info = report.plain_back_summary(fake_week, broken)
    assert info["skipped"] == ["2026-08-17"], info
    report.apply_plain_back(fake_week, broken)
    assert fake_week["days"]["2026-08-17"]["items"], "格式异常时不应清空当日记录"
    # 难点多行：原样回写不应被压成单行
    diff_week = {"start_date": "2026-08-17", "workdays": ["2026-08-17"], "days": {
        "2026-08-17": {"done": True, "items": [
            {"content": "联调支付", "status": "进行中", "difficulty": "验签报错\n等供应商回复"}]}}}
    report.apply_plain_back(diff_week, report.build_plain(app.data, diff_week))
    assert diff_week["days"]["2026-08-17"]["items"][0]["difficulty"] == "验签报错\n等供应商回复", \
        "多行难点在回写后丢失了换行"
    # 数据文件容错：结构错误不应导致崩溃
    with open(storage.DATA_FILE, "w", encoding="utf-8") as f:
        f.write('{"weeks": [], "settings": "oops"}')
    recovered = storage.load_data()
    assert recovered["weeks"] == {} and recovered["settings"]["reporter"] == "", recovered
    print("SMOKE OK:", report.report_title(week))
    print("stats:", stats)
    root.destroy()


if __name__ == "__main__":
    main()
