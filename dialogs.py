# -*- coding: utf-8 -*-
"""工作日志：各功能对话框（周设置 / 历史记录 / 搜索 / 常用工作清单 / 周报预览导出）。

从 worklog.py 拆出，避免主文件过长。对话框通过 app（WorkLogApp 实例）访问数据、
刷新界面、推送撤销快照；本模块不反向导入 worklog，避免循环依赖。
"""
import datetime
import os
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

import report
import storage
import todo_list


# ---------- 周设置对话框 ----------

def open_week_setup(app, default_date=None):
    """周设置对话框。返回 True 表示已设置，False 表示取消。"""
    if default_date is None:
        default_date = (storage.parse_date(app.current_date)
                        if app.current_date else datetime.date.today())
    f = app._font_family
    win = tk.Toplevel(app.root)
    win.title("周设置：工作日安排")
    win.transient(app.root)
    win.grab_set()
    win.resizable(False, False)
    result = {"ok": False}

    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)

    row0 = ttk.Frame(frm)
    row0.pack(fill="x", pady=4)
    ttk.Label(row0, text="汇报人：").pack(side="left")
    var_reporter = tk.StringVar(
        value=app.data.get("settings", {}).get("reporter", ""))
    tk.Entry(row0, textvariable=var_reporter, width=14, font=(f, 10)).pack(side="left")
    ttk.Label(row0, text="（可留空；填写后会显示在周报标题下方）").pack(side="left", padx=6)

    row1 = ttk.Frame(frm)
    row1.pack(fill="x", pady=4)
    ttk.Label(row1, text="起始日期：").pack(side="left")
    var_date = tk.StringVar(value=storage.format_date(default_date))
    tk.Entry(row1, textvariable=var_date, width=14, font=(f, 10)).pack(side="left")
    ttk.Label(row1, text="（自动取该日所在周的周一，格式 YYYY-MM-DD）").pack(side="left", padx=6)

    ttk.Label(frm, text="选择工作日：").pack(anchor="w", pady=(10, 2))
    row2 = ttk.Frame(frm)
    row2.pack(fill="x")
    setup_vars = []
    defaults = [True, True, True, True, True, False, False]

    def update_preview():
        try:
            d = storage.parse_date(var_date.get())
            flags = [v.get() for v in setup_vars]
            wd = storage.make_workdays(d, flags)
            parts = [f"{storage.short_date(w)} {storage.weekday_cn(w)}" for w in wd]
            lbl_preview.config(
                text="将生成工作日：" + ("、".join(parts) if parts else "（未勾选任何一天）"))
        except (ValueError, AttributeError, tk.TclError):
            lbl_preview.config(text="日期格式无效")

    for i, name in enumerate(storage.WEEKDAY_NAMES):
        v = tk.BooleanVar(value=defaults[i])
        v.trace_add("write", lambda *a: update_preview())
        tk.Checkbutton(row2, text=name, variable=v, font=(f, 10)).pack(side="left", padx=4)
        setup_vars.append(v)
    lbl_preview = ttk.Label(frm, text="", foreground="#1f4e79")
    lbl_preview.pack(anchor="w", pady=(8, 0))
    update_preview()

    def confirm():
        try:
            d = storage.parse_date(var_date.get())
        except ValueError:
            messagebox.showerror("日期格式错误", "请按 YYYY-MM-DD 格式输入日期，例如 2026-08-19。", parent=win)
            return
        flags = [v.get() for v in setup_vars]
        if not any(flags):
            messagebox.showerror("未选择工作日", "请至少勾选一个工作日。", parent=win)
            return
        wd = storage.make_workdays(d, flags)
        key = storage.format_date(storage.monday_of(d))
        is_new = key not in app.data["weeks"]
        week = app.data["weeks"].setdefault(
            key, {"start_date": key, "workdays": [], "next_week_plan": "", "days": {}})
        if not is_new:
            # 取消勾选有记录的工作日会让这些记录“隐形”（仍留在文件里），先向用户说明
            removed = [dd for dd in week.get("workdays", []) if dd not in wd]
            orphan = [dd for dd in removed
                      if storage.peek_day(week, dd).get("items")
                      or storage.peek_day(week, dd).get("done")]
            if orphan:
                lines = "\n".join(
                    f"  {storage.short_date(dd)} {storage.weekday_cn(dd)}"
                    f"（{len(storage.peek_day(week, dd).get('items', []))} 条记录）"
                    for dd in orphan)
                if not messagebox.askyesno(
                        "确认调整工作日",
                        "以下日期取消勾选后，其记录将不再显示在界面和周报中\n"
                        "（数据仍保留在文件里，重新勾选该日期即可恢复）：\n\n"
                        + lines + "\n\n确认继续？",
                        parent=win):
                    return
            app._push_undo()
        week["workdays"] = wd
        app.data.setdefault("settings", {})["reporter"] = var_reporter.get().strip()
        carried = app._carry_over_from_prev_week(key) if is_new else 0
        storage.save_data(app.data)
        result["ok"] = True
        win.destroy()
        if app.week_key != key:
            app.week_key = key
            app.current_date = wd[0]
        elif app.current_date not in wd:
            app.current_date = wd[0]
        app.refresh_all()
        msg = f"已设置 {storage.week_range_label(week)}，共 {len(wd)} 个工作日"
        if carried:
            msg += f"；已自动带入上周未完成事项 {carried} 条"
        app._status_msg(msg)

    row3 = ttk.Frame(frm)
    row3.pack(fill="x", pady=(12, 0))
    ttk.Button(row3, text="确定", command=confirm).pack(side="left", padx=(0, 8))
    ttk.Button(row3, text="取消", command=win.destroy).pack(side="left")

    win.focus_force()   # 确保键盘事件进入对话框
    app.root.wait_window(win)
    return result["ok"]


# ---------- 历史记录对话框 ----------

def open_history(app):
    # 打开前先落盘：窗口里的跳转/删除都会重建界面，未保存的编辑否则会丢失
    app.collect_and_save()
    f = app._font_family
    win = tk.Toplevel(app.root)
    win.title("历史记录（双击跳转）")
    win.transient(app.root)
    win.grab_set()          # 模态：避免开出多个历史窗口各自改数据
    win.geometry("460x540")
    lb = tk.Listbox(win, font=(f, 10), activestyle="dotbox")
    lb.pack(fill="both", expand=True, padx=8, pady=(8, 4))
    mapping = []  # ("week", key) 或 ("day", key, 日期)

    def fill():
        lb.delete(0, "end")
        mapping.clear()
        for key in sorted(app.data["weeks"], reverse=True):
            week = app.data["weeks"][key]
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
            app.collect_and_save()   # 跳转前保存当前编辑
            app.week_key, app.current_date = item[1], item[2]
            app.refresh_all()
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
        app.collect_and_save()
        app._push_undo()
        storage.snapshot("del_day")   # 删除前留快照，可从 data/backup/ 取回
        app.data["weeks"][key]["days"].pop(d, None)
        storage.save_data(app.data)
        if app.week_key == key:
            app.refresh_all()
        fill()
        app._status_msg(f"已删除 {label} 的记录（可 Ctrl+Z 撤销；快照见 data/backup/）")

    def delete_week():
        item = selected()
        if not item or item[0] != "week":
            messagebox.showinfo("提示", "请先选中要删除的整周（▍开头的一行）。", parent=win)
            return
        key = item[1]
        week = app.data["weeks"][key]
        label = storage.week_range_label(week)
        if not messagebox.askyesno("确认删除",
                                   f"确认删除整周 {label} 的记录和工作日设置吗？\n此操作不可恢复。",
                                   parent=win):
            return
        app.collect_and_save()
        app._push_undo()
        storage.snapshot("del_week")  # 删除前留快照，可从 data/backup/ 取回
        app.data["weeks"].pop(key, None)
        storage.save_data(app.data)
        if app.week_key == key:
            app.week_key = None
            app.current_date = None
            app.refresh_all()
        fill()
        app._status_msg(f"已删除整周 {label}（可 Ctrl+Z 撤销；快照见 data/backup/）")

    fill()
    btns = ttk.Frame(win, padding=(8, 0, 8, 8))
    btns.pack(fill="x")
    ttk.Button(btns, text="跳转到该日", command=go).pack(side="left")
    ttk.Button(btns, text="删除该日记录", command=delete_day).pack(side="left", padx=(8, 0))
    ttk.Button(btns, text="删除整周", command=delete_week).pack(side="left", padx=(8, 0))
    lb.bind("<Double-Button-1>", lambda e: go())
    win.bind("<Escape>", lambda e: win.destroy())
    win.focus_force()   # 确保键盘事件（Esc）进入对话框


# ---------- 搜索 ----------

def open_search(app):
    """搜索对话框：对历史与当前全部记录做模糊搜索，双击/回车跳转到对应日期。"""
    app.collect_and_save()
    f = app._font_family
    win = tk.Toplevel(app.root)
    win.title("搜索记录（历史 + 当前）")
    win.transient(app.root)
    win.grab_set()
    win.geometry("720x560")
    win.minsize(560, 420)

    top = ttk.Frame(win, padding=(10, 8, 10, 0))
    top.pack(fill="x")
    ttk.Label(top, text="关键词：").pack(side="left")
    var_q = tk.StringVar()
    entry = tk.Entry(top, textvariable=var_q, font=(f, 10))
    entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
    lbl_count = ttk.Label(top, text="", foreground="#595959")
    lbl_count.pack(side="right")

    ttk.Label(win,
              text="模糊匹配工作内容 / 难点备注 / 状态 / 下周计划；"
                   "空格分隔多个关键词（须全部命中）。",
              foreground="#9e9e9e", padding=(10, 2, 10, 2)).pack(fill="x")

    body = ttk.Frame(win, padding=(10, 4))
    body.pack(fill="both", expand=True)
    txt = tk.Text(body, font=(f, 10), wrap="word", state="disabled",
                  background="#ffffff", cursor="arrow")
    scroll = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=scroll.set)
    txt.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    txt.tag_configure("hit", background="#ffe58f")     # 命中的关键词
    txt.tag_configure("week", font=(f, 9, "bold"), foreground="#3F51B1")
    txt.tag_configure("day", font=(f, 9, "bold"), foreground="#595959")
    txt.tag_configure("plan", foreground="#1f4e79")
    txt.tag_configure("sel", background="#cce5ff")     # 选中的行
    st_tags = {}
    for i, st in enumerate(report.STATUS_TEXT_COLORS):
        tag = f"st{i}"
        txt.tag_configure(tag, foreground=report.STATUS_TEXT_COLORS[st],
                          font=(f, 10, "bold"))
        st_tags[st] = tag

    closed = [False]
    pending = [None]      # 渲染防抖定时器
    line_no = 0
    mapping = []          # (行号, week_key, 日期或 None, kind)
    selected = {"line": None}

    def next_line():
        nonlocal line_no
        line_no += 1
        return line_no

    def render():
        nonlocal line_no
        if closed[0]:
            return
        q = var_q.get().strip()
        kws = [k for k in q.casefold().split() if k]
        txt.config(state="normal")
        txt.delete("1.0", "end")
        mapping.clear()
        line_no = 0
        selected["line"] = None
        txt.tag_remove("sel", "1.0", "end")

        def add_hits(ln, line_text):
            low = line_text.casefold()
            for kw in kws:
                pos = low.find(kw)
                while pos != -1:
                    txt.tag_add("hit", f"{ln}.{pos}", f"{ln}.{pos + len(kw)}")
                    pos = low.find(kw, pos + len(kw))

        results = report.search_items(app.data, q)
        if not q:
            txt.insert("end", "输入关键词开始搜索。\n")
            lbl_count.config(text="")
            txt.config(state="disabled")
            return
        if not results:
            txt.insert("end", f"没有找到与「{q}」相关的记录。\n")
            lbl_count.config(text="0 条")
            txt.config(state="disabled")
            return
        n_item = sum(1 for r in results if r["kind"] == "item")
        n_plan = len(results) - n_item
        lbl_count.config(text=f"{n_item} 条记录" + (f"，{n_plan} 条计划" if n_plan else ""))
        last_week = None
        last_day = None
        for r in results:
            if r["week_key"] != last_week:
                last_week, last_day = r["week_key"], None
                ln = next_line()
                suffix = "（当前周）" if r["week_key"] == app.week_key else ""
                txt.insert("end", f"▍ {r['week_label']}{suffix}\n", "week")
                mapping.append((ln, r["week_key"], None, "week"))
            if r["kind"] == "plan":
                ln = next_line()
                line_text = f"    四、下周计划：{report._flat(r['plan'])}"
                txt.insert("end", line_text + "\n", "plan")
                add_hits(ln, line_text)
                mapping.append((ln, r["week_key"], None, "plan"))
                continue
            if r["date"] != last_day:
                last_day = r["date"]
                ln = next_line()
                txt.insert("end", f"  {storage.short_date(r['date'])} "
                                 f"{storage.weekday_cn(r['date'])}\n", "day")
                mapping.append((ln, r["week_key"], r["date"], "day"))
            content = (r["item"].get("content") or "").strip() or "（未填写内容）"
            status = r["item"].get("status") or "未开始"
            diff = (r["item"].get("difficulty") or "").strip()
            prefix = f"    {r['seq']}. {report._flat(content)} —— "
            line_text = prefix + status + (f"【难点：{report._flat(diff)}】" if diff else "")
            ln = next_line()
            txt.insert("end", prefix)
            txt.insert("end", status, st_tags[status])
            if diff:
                txt.insert("end", f"【难点：{report._flat(diff)}】")
            txt.insert("end", "\n")
            add_hits(ln, line_text)
            mapping.append((ln, r["week_key"], r["date"], "item"))
        txt.config(state="disabled")
        # 默认选中第一条记录，回车即可跳转
        first = next((m for m in mapping if m[3] == "item"),
                     next((m for m in mapping if m[3] == "plan"), mapping[0]))
        selected["line"] = first[0]
        txt.tag_add("sel", f"{first[0]}.0", f"{first[0]}.0 lineend")

    def schedule_render():
        # 每敲一键全量搜索+重绘太重：停顿 200ms 后再渲染
        if closed[0]:
            return
        if pending[0] is not None:
            try:
                win.after_cancel(pending[0])
            except tk.TclError:
                pass
        pending[0] = win.after(200, render)

    def find_target(ln):
        tgt = None
        for m in mapping:
            if m[0] > ln:
                break
            tgt = m
        return tgt

    def goto_line(ln):
        tgt = find_target(ln)
        if not tgt:
            return
        _, wk, dt, _kind = tgt
        week = app.data["weeks"].get(wk)
        wd = week.get("workdays", []) if week else []
        if not wd:
            app._status_msg("该周没有设置工作日，无法跳转。")
            return
        app.week_key = wk
        if dt and dt in wd:
            app.current_date = dt
        elif app.current_date not in wd:
            app.current_date = wd[0]
        app.refresh_all()
        app._status_msg(f"已跳转到 {storage.short_date(app.current_date)} "
                        f"{storage.weekday_cn(app.current_date)}（搜索结果）")
        close()

    def jump_selected():
        if selected["line"] is not None:
            goto_line(selected["line"])

    def on_click(event):
        ln = int(txt.index(f"@{event.x},{event.y}").split(".")[0])
        if not txt.get(f"{ln}.0", f"{ln}.0 lineend").strip():
            return    # 空白行不可选
        txt.tag_remove("sel", "1.0", "end")
        txt.tag_add("sel", f"{ln}.0", f"{ln}.0 lineend")
        selected["line"] = ln

    def on_dbl(event):
        ln = int(txt.index(f"@{event.x},{event.y}").split(".")[0])
        if not txt.get(f"{ln}.0", f"{ln}.0 lineend").strip():
            return
        goto_line(ln)

    def close():
        if closed[0]:
            return
        closed[0] = True
        if pending[0] is not None:
            try:
                win.after_cancel(pending[0])
            except tk.TclError:
                pass
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", lambda e: close())
    win.bind("<Return>", lambda e: jump_selected())   # 对话框内任意位置回车均可跳转
    win.bind("<Map>", lambda e: entry.focus_force())  # 窗口显示后强制焦点到输入框，打开即可输入
    txt.bind("<Button-1>", on_click)
    txt.bind("<Double-Button-1>", on_dbl)
    var_q.trace_add("write", lambda *a: None if closed[0] else schedule_render())

    btns = ttk.Frame(win, padding=(10, 0, 10, 8))
    btns.pack(fill="x")
    ttk.Button(btns, text="跳转到选中记录（回车）", command=jump_selected).pack(side="left")
    ttk.Button(btns, text="关闭", command=close).pack(side="left", padx=(8, 0))

    render()
    win.focus_force()   # 确保键盘事件（回车跳转 / Esc 关闭）进入对话框
    entry.focus_set()


# ---------- 常用工作清单对话框 ----------

def open_todo_list(app):
    """常用工作清单管理对话框：添加 / 删除 / 排序，保存到 todo_list-config 目录。"""
    f = app._font_family
    win = tk.Toplevel(app.root)
    win.title("常用工作清单")
    win.transient(app.root)
    win.grab_set()
    win.geometry("470x430")
    win.minsize(430, 380)
    win.resizable(True, True)

    frm = ttk.Frame(win, padding=10)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="常用工作（录入时点工作内容右侧 ▾ 或右键内容框选择）：").pack(anchor="w")

    box = ttk.Frame(frm)
    box.pack(fill="both", expand=True, pady=6)
    lb = tk.Listbox(box, font=(f, 10), activestyle="dotbox")
    lb.pack(side="left", fill="both", expand=True)
    scroll = ttk.Scrollbar(box, command=lb.yview)
    scroll.pack(side="right", fill="y")
    lb.config(yscrollcommand=scroll.set)
    for it in todo_list.load_items():
        lb.insert("end", it)

    row_add = ttk.Frame(frm)
    row_add.pack(fill="x", pady=(0, 6))
    var_new = tk.StringVar()
    ent = tk.Entry(row_add, textvariable=var_new, font=(f, 10))
    ent.pack(side="left", fill="x", expand=True)

    def do_add():
        s = var_new.get().strip()
        if not s:
            return
        for i in range(lb.size()):
            if lb.get(i) == s:
                lb.selection_clear(0, "end")
                lb.selection_set(i)
                lb.see(i)
                var_new.set("")
                return
        lb.insert("end", s)
        lb.see("end")
        var_new.set("")

    ttk.Button(row_add, text="添加", command=do_add).pack(side="left", padx=(8, 0))

    row_btns = ttk.Frame(frm)
    row_btns.pack(fill="x", pady=(0, 8))
    ttk.Button(row_btns, text="上移", command=lambda: _move_todo_item(lb, -1)).pack(side="left")
    ttk.Button(row_btns, text="下移", command=lambda: _move_todo_item(lb, 1)).pack(
        side="left", padx=6)

    def do_delete():
        sel = lb.curselection()
        if sel:
            lb.delete(sel[0])

    ttk.Button(row_btns, text="删除选中", command=do_delete).pack(side="left")

    ttk.Label(frm, text=f"保存在：{todo_list.TODO_FILE}", foreground="#888888",
              font=(f, 8)).pack(anchor="w", pady=(0, 8))

    row_ok = ttk.Frame(frm)
    row_ok.pack(fill="x")
    saved_lbl = ttk.Label(row_ok, text="", foreground="#375623")

    def do_save():
        todo_list.save_items([lb.get(i) for i in range(lb.size())])
        saved_lbl.config(text=f"已保存 {lb.size()} 条")

    def do_save_and_close():
        todo_list.save_items([lb.get(i) for i in range(lb.size())])
        win.destroy()
        app._status_msg(f"常用工作清单已保存（{lb.size()} 条）")

    ttk.Button(row_ok, text="保存", command=do_save).pack(side="left")
    ttk.Button(row_ok, text="保存并关闭", command=do_save_and_close).pack(side="left", padx=6)
    ttk.Button(row_ok, text="取消", command=win.destroy).pack(side="left", padx=(16, 8))
    saved_lbl.pack(side="left")
    win.protocol("WM_DELETE_WINDOW", do_save_and_close)   # 点右上角 ✕ 也保存
    win.bind("<Return>", lambda e: do_add())
    win.focus_force()   # 确保键盘事件进入对话框
    ent.focus_set()


def _move_todo_item(lb, delta):
    sel = lb.curselection()
    if not sel:
        return
    i = sel[0]
    j = i + delta
    if not (0 <= j < lb.size()):
        return
    s = lb.get(i)
    lb.delete(i)
    lb.insert(j, s)
    lb.selection_clear(0, "end")
    lb.selection_set(j)
    lb.see(j)


# ---------- 周报预览与导出 ----------

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
        ttk.Label(top, text=report.overview_sentence(week, data), foreground="#595959").pack(
            anchor="w", pady=(2, 0))

        body = ttk.Frame(self.win, padding=(10, 6))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="纯文本预览（可直接修改，改完点「💾 保存修改」回写到记录，HTML 版同步生效）：").pack(anchor="w")
        self.txt = tk.Text(body, font=(f, 10), wrap="word", undo=True)
        self.txt.pack(fill="both", expand=True, pady=(2, 6))
        draft = week.get("report_draft")
        # 草稿保存后记录可能又被改过：指纹不一致时让用户选择用草稿还是重新生成，
        # 避免旧草稿静默覆盖新数据
        if draft and week.get("report_draft_fp"):
            if week["report_draft_fp"] != report.week_fingerprint(data, week):
                if not messagebox.askyesno(
                        "草稿与记录不一致",
                        "这份周报草稿保存后，工作记录已被修改过。\n\n"
                        "选「是」继续显示草稿；\n选「否」按当前记录重新生成周报。",
                        parent=self.win):
                    draft = None
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
        info = report.plain_back_summary(self.week, text, self.data)
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
            self.app._push_undo()
        n = report.apply_plain_back(self.week, text, self.data)
        if n:
            self.week.pop("report_draft", None)  # 修改已进数据，草稿不再需要
            self.week.pop("report_draft_fp", None)
            storage.save_data(self.data)
            self.app.collect_and_save()
            self.app.refresh_all()
            msg = f"✅ 已保存修改并回写 {n} 条记录，HTML 版与纯文本版同步生效。"
            if info["skipped"]:
                msg += f"（{len(info['skipped'])} 天格式无法解析，已保留原记录）"
            self._msg(msg)
        else:
            self.week["report_draft"] = text
            self.week["report_draft_fp"] = report.week_fingerprint(self.data, self.week)
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
