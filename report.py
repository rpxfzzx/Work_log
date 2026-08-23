# -*- coding: utf-8 -*-
"""工作日志：周报生成与导出（HTML / 纯文本 / 剪贴板 / Outlook）。

周报结构参考主流周报模板：基本信息 → 本周工作概述 → 每日工作明细 → 难点与问题 → 下周计划。
HTML 全部使用内联样式（无 class / 外部 CSS），保证复制粘贴到 Outlook 邮件正文不变形。
"""
import html as _html
import os
import re
import subprocess
import tempfile

import storage

# 状态配色：界面行底色与周报单元格底色共用
STATUS_COLORS = {
    "已完成": "#e2f0d9",  # 绿
    "进行中": "#ddebf7",  # 蓝
    "未开始": "#f2f2f2",  # 灰
}
STATUS_TEXT_COLORS = {
    "已完成": "#375623",
    "进行中": "#1f4e79",
    "未开始": "#595959",
}
# 同一事项跨日出现时的合并优先级：已完成 > 进行中 > 未开始
_STATUS_RANK = {"未开始": 0, "进行中": 1, "已完成": 2}

REPORTS_DIR = os.path.join(storage.BASE_DIR, "reports")

_esc = _html.escape


def _cell_html(s):
    """表格单元格文本：转义并把换行转为 <br>。"""
    return _esc(s).replace("\n", "<br>")


def _flat(s):
    """纯文本里的多行内容压成一行：行尾逗号/换行统一转为；，避免出现「，；」双标点。"""
    return re.sub(r"[，,、]?\s*\n\s*", "；", s)


def get_reporter(data):
    return ((data or {}).get("settings", {}) or {}).get("reporter", "").strip()


# ---------- 统计 ----------

def norm_content(s):
    """归一化工作内容用于跨日匹配：去掉所有空白字符，便于识别「同一事项」。"""
    return re.sub(r"\s+", "", (s or ""))


_norm = norm_content   # 模块内简写


def collect_stats(week):
    """返回 (stats, difficulties)。

    stats 字段：
      total/done/doing/todo/diff/filled —— 按「记录条数」计数；
      unique —— 按「事项」去重后的计数 {total/done/doing/todo}，
                 同一内容跨多天记录只算一项，状态取跨天最高（已完成 > 进行中 > 未开始）；
      merged —— {(日期, 条目序号): 完成日期}，即已收尾的「进行中」事项映射。
    difficulties: [(日期, 工作内容, 难点描述), ...]

    跨日关联：某日「进行中」的事项，若同周之后某天出现了内容一致的「已完成」条目，
    视为已收尾，归入已完成（概述数字、明细表标注与下周计划草拟均按此口径）。
    """
    stats = {"total": 0, "done": 0, "doing": 0, "todo": 0, "diff": 0,
             "filled": 0, "merged": {},
             "unique": {"total": 0, "done": 0, "doing": 0, "todo": 0}}
    diffs = []
    workdays = week.get("workdays", [])
    # 第一遍：收集「已完成」条目的归一化内容 → 最早完成日期
    done_dates = {}
    for d in workdays:
        for it in storage.peek_day(week, d).get("items", []):
            if (it.get("status") or "未开始") == "已完成":
                c = _norm(it.get("content"))
                if c:
                    done_dates.setdefault(c, d)
    # 第二遍：统计；「进行中」条目若同内容在之后某天已完成 → 归入已完成
    uniq = {}   # 事项 key -> 合并后的状态
    for d in workdays:
        day = storage.peek_day(week, d)
        if day.get("done"):
            stats["filled"] += 1
        items = day.get("items", [])
        for i, it in enumerate(items):
            stats["total"] += 1
            s = it.get("status") or "未开始"
            if s == "进行中":
                dd = done_dates.get(_norm(it.get("content")))
                if dd and dd > d:  # 完成条目在同周之后（不含同日）
                    stats["merged"][(d, i)] = dd
                    s = "已完成"
            if s == "已完成":
                stats["done"] += 1
            elif s == "进行中":
                stats["doing"] += 1
            else:
                stats["todo"] += 1
            # 去重口径：同内容视为一个事项；内容为空的条目各算一项（无法归并）
            c = _norm(it.get("content"))
            key = c if c else ("\x00blank", d, i)
            prev = uniq.get(key)
            if prev is None or _STATUS_RANK[s] > _STATUS_RANK[prev]:
                uniq[key] = s
            diff = (it.get("difficulty") or "").strip()
            if diff:
                stats["diff"] += 1
                diffs.append((d, (it.get("content") or "").strip(), diff))
    u = stats["unique"]
    u["total"] = len(uniq)
    for s in uniq.values():
        u["done" if s == "已完成" else ("doing" if s == "进行中" else "todo")] += 1
    return stats, diffs


def overview_sentence(week):
    """'本周共 5 个工作日，推进事项 4 项：已完成 2 项，进行中 1 项，未开始 1 项（共记录 7 条明细）；记录难点 2 条。'

    注意统计口径：同一件事跨多天记录只算「1 项」，避免概述数字虚高；
    括号里的「条明细」才是逐日记录的条数。
    """
    stats, _ = collect_stats(week)
    u = stats["unique"]
    parts = [f"本周共 {len(week.get('workdays', []))} 个工作日"]
    if stats["total"]:
        seg = (f"推进事项 {u['total']} 项：已完成 {u['done']} 项，"
               f"进行中 {u['doing']} 项，未开始 {u['todo']} 项")
        if stats["total"] != u["total"]:
            seg += f"（共记录 {stats['total']} 条明细）"
        parts.append(seg)
    else:
        parts.append("本周暂无工作记录")
    if stats["diff"]:
        parts.append(f"记录难点 {stats['diff']} 条")
    return parts[0] + "，" + "；".join(parts[1:]) + "。"


def unfinished_items(week):
    """本周尚未收尾的事项（按内容去重，保留最后一次出现的状态与难点）。

    「进行中」但在本周后续已完成的事项不计入。返回 [{content,status,difficulty}, ...]。
    """
    stats, _ = collect_stats(week)
    merged = stats.get("merged", {})
    out = {}
    for d in week.get("workdays", []):
        for i, it in enumerate(storage.peek_day(week, d).get("items", [])):
            s = it.get("status") or "未开始"
            content = (it.get("content") or "").strip()
            if not content:
                continue
            key = _norm(content)
            if s == "已完成" or (d, i) in merged:
                out.pop(key, None)          # 后来完成了 → 不再承接
                continue
            out[key] = {"content": content, "status": s,
                        "difficulty": (it.get("difficulty") or "").strip()}
    return list(out.values())


def next_week_plan(week):
    """用户填写的下周计划；为空时自动草拟（承接本周未收尾事项，同一事项只列一次）。"""
    plan = (week.get("next_week_plan") or "").strip()
    if plan:
        return plan
    carry = unfinished_items(week)
    if not carry:
        return "（待填写）"
    lines = ["（以下为自动草拟，请按需修改）"]
    lines += [f"{i}. 继续推进：{_flat(it['content'])}（{it['status']}）"
              for i, it in enumerate(carry, 1)]
    return "\n".join(lines)


def report_title(week):
    return f"【周报】{storage.week_range_label(week)} 工作汇报"


# ---------- HTML 生成 ----------

def _items_table_html(items, merged, day_key):
    rows = [
        '<table border="1" cellpadding="6" cellspacing="0" '
        'style="border-collapse:collapse;border-color:#bfbfbf;width:100%;">',
        '<tr style="background-color:#f2f2f2;">'
        '<th style="width:50px;">序号</th>'
        '<th>工作内容</th>'
        '<th style="width:100px;">状态</th>'
        '<th style="width:220px;">难点/备注</th></tr>',
    ]
    if not items:
        rows.append('<tr><td style="text-align:center;">—</td>'
                    '<td>（当日未记录）</td>'
                    '<td style="text-align:center;background-color:#f2f2f2;">—</td>'
                    '<td></td></tr>')
    else:
        for i, it in enumerate(items, 1):
            s = it.get("status") or "未开始"
            bg = STATUS_COLORS.get(s, "#f2f2f2")
            fg = STATUS_TEXT_COLORS.get(s, "#595959")
            status_cell = _esc(s)
            done_on = merged.get((day_key, i - 1))
            if done_on:  # 后续已收尾的「进行中」事项：状态加注完成日期
                status_cell += (f'<br><span style="font-weight:normal;color:#595959;'
                                f'font-size:11px;">已于 {storage.short_date(done_on)} 完成</span>')
            rows.append(
                '<tr>'
                f'<td style="text-align:center;">{i}</td>'
                f'<td style="vertical-align:top;">{_cell_html((it.get("content") or "").strip())}</td>'
                f'<td style="text-align:center;background-color:{bg};color:{fg};'
                f'font-weight:bold;">{status_cell}</td>'
                f'<td style="vertical-align:top;">{_cell_html((it.get("difficulty") or "").strip())}</td>'
                '</tr>')
    rows.append('</table>')
    return "".join(rows)


def build_html(data, week, full_document=False):
    """生成周报 HTML 片段（full_document=True 时返回完整文档，用于导出文件/Outlook）。"""
    stats, diffs = collect_stats(week)

    h = ['<div style="font-family:微软雅黑,Microsoft YaHei,Segoe UI,sans-serif;'
         'font-size:14px;color:#222222;line-height:1.6;">']
    # 品牌徽标（与 Logo 同色系，纯内联样式，粘贴到 Outlook 不变形）
    h.append('<p style="margin:0 0 8px 0;">'
             '<span style="display:inline-block;background-color:#3F51B1;color:#ffffff;'
             'font-weight:bold;font-size:12px;padding:3px 10px;border-radius:4px;">'
             '✓ 工作日志 · 周报</span></p>')
    h.append(f'<h2 style="font-size:18px;margin:0 0 12px 0;">{_esc(report_title(week))}</h2>')
    reporter = get_reporter(data)
    if reporter:
        h.append(f'<p style="margin:-6px 0 12px 0;color:#595959;font-size:13px;">'
                 f'汇报人：{_esc(reporter)}</p>')

    h.append('<h3 style="font-size:15px;margin:16px 0 6px 0;">一、本周工作概述</h3>')
    h.append(f'<p style="margin:0;">{_esc(overview_sentence(week))}</p>')

    h.append('<h3 style="font-size:15px;margin:16px 0 6px 0;">二、本周工作明细</h3>')
    for d in week.get("workdays", []):
        items = storage.peek_day(week, d).get("items", [])
        h.append(f'<p style="margin:12px 0 4px 0;"><b>{storage.format_date(d)}'
                 f'（{storage.weekday_cn(d)}）</b></p>')
        h.append(_items_table_html(items, stats.get("merged", {}), d))

    h.append('<h3 style="font-size:15px;margin:16px 0 6px 0;">三、难点与问题</h3>')
    if diffs:
        h.append('<ol style="margin:0;padding-left:24px;">')
        for d, content, diff in diffs:
            content = content or "（未填写内容）"
            h.append(f'<li>（{storage.short_date(d)}）{_cell_html(content)}：{_cell_html(diff)}</li>')
        h.append('</ol>')
    else:
        h.append('<p style="margin:0;">本周无难点记录。</p>')

    plan_html = _esc(next_week_plan(week)).replace("\n", "<br>")
    h.append('<h3 style="font-size:15px;margin:16px 0 6px 0;">四、下周计划</h3>')
    h.append(f'<p style="margin:0;">{plan_html}</p>')

    h.append('<p style="margin:20px 0 0 0;color:#888888;font-size:12px;">'
             '—— 由工作日志工具自动生成 ——</p>')
    h.append('</div>')

    fragment = "".join(h)
    if full_document:
        return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                f'<title>{_esc(report_title(week))}</title></head>'
                '<body style="background-color:#ffffff;">' + fragment + '</body></html>')
    return fragment


# ---------- 纯文本生成 ----------

_DATE_HEAD_RE = re.compile(r"^(\d{4})[-.](\d{1,2})[-.](\d{1,2})")
_ITEM_RE = re.compile(r"^(\d+)[.、]\s*(.+?)\s*—+\s*([^\s【（]+)(.*)$")
_DIFF_RE = re.compile(r"【难点：([^】]*)】")


def build_plain(data, week):
    stats, diffs = collect_stats(week)

    lines = [report_title(week)]
    reporter = get_reporter(data)
    if reporter:
        lines.append(f"汇报人：{reporter}")
    lines += [
        "",
        "一、本周工作概述",
        overview_sentence(week),
        "",
        "二、本周工作明细",
    ]
    for d in week.get("workdays", []):
        items = storage.peek_day(week, d).get("items", [])
        lines.append(f"{storage.format_date(d)}（{storage.weekday_cn(d)}）")
        if not items:
            lines.append("（当日未记录）")
        else:
            for i, it in enumerate(items, 1):
                s = it.get("status") or "未开始"
                done_on = stats.get("merged", {}).get((d, i - 1))
                content = (it.get("content") or "").strip() or "（未填写内容）"
                content = content.replace("\n", "\n    ")  # 续行缩进对齐
                line = f"{i}. {content} —— {s}"
                if done_on:  # 后续已收尾的「进行中」事项
                    line += f"（已于 {storage.short_date(done_on)} 完成）"
                diff = (it.get("difficulty") or "").strip()
                if diff:
                    line += f"【难点：{_flat(diff)}】"
                lines.append(line)
        lines.append("")
    lines.append("三、难点与问题")
    if diffs:
        for i, (d, content, diff) in enumerate(diffs, 1):
            lines.append(f"{i}. （{storage.short_date(d)}）"
                         f"{_flat(content or '（未填写内容）')}：{_flat(diff)}")
    else:
        lines.append("本周无难点记录。")
    lines += ["", "四、下周计划", next_week_plan(week), "", "—— 由工作日志工具自动生成 ——"]
    return "\n".join(lines)


# ---------- 纯文本回写 ----------

def _parse_plain(week, text):
    """解析周报预览文本，返回 (parsed, plan)。

    parsed: {日期: [条目, ...]}，日期行出现即建键（值可能为空列表 = 该日没解析出条目）；
    plan:   「四、下周计划」正文（无该小节时为 None）。
    """
    lines = text.split("\n")
    sec2 = sec4 = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if sec2 is None and s.startswith("二、") and "明细" in s:
            sec2 = i
        elif sec4 is None and s.startswith("四、") and "计划" in s:
            sec4 = i

    workdays = week.get("workdays", [])
    parsed = {}
    cur = None
    if sec2 is not None:
        sec3 = next((i for i in range(sec2 + 1, len(lines))
                     if lines[i].strip().startswith("三、")), len(lines))
        for ln in lines[sec2 + 1:sec3]:
            s = ln.strip()
            d = _DATE_HEAD_RE.match(s)
            if d and d.group(0) == s.split("（")[0]:  # 日期行：整行以日期开头且是工作日
                ds = f"{int(d.group(1)):04d}-{int(d.group(2)):02d}-{int(d.group(3)):02d}"
                if ds in workdays:
                    cur = ds
                    parsed.setdefault(cur, [])
                continue
            m = _ITEM_RE.match(s)
            if cur is not None and m:
                _, content, status, tail = m.groups()
                if status in storage.STATUSES:
                    dm = _DIFF_RE.search(tail)
                    parsed[cur].append({"content": content.strip(), "status": status,
                                        "difficulty": dm.group(1).strip() if dm else ""})
                continue
            # 多行内容的续行（缩进开头）合并到上一条
            if cur is not None and parsed.get(cur) and re.match(r"^\s{2,}", ln) and ln.strip():
                parsed[cur][-1]["content"] += "\n" + ln.strip()

    plan = None
    if sec4 is not None:
        plan = "\n".join(
            s for s in (ln.strip() for ln in lines[sec4 + 1:])
            if "由工作日志工具自动生成" not in s
            and s not in ("", "（以下为自动草拟，请按需修改）", "（待填写）"))
    return parsed, plan


def _restore_multiline_diff(new_items, old_items):
    """难点在纯文本里被压成单行（_flat），原样回写会丢换行。

    逐条比对：用户没改动该条难点（压平后与原值一致）时，恢复原始多行文本。
    """
    for i, it in enumerate(new_items):
        if i >= len(old_items):
            break
        old = (old_items[i].get("difficulty") or "")
        if old and _flat(old.strip()) == it.get("difficulty", ""):
            it["difficulty"] = old


def plain_back_summary(week, text):
    """回写前的影响评估（供界面弹确认框用），不修改任何数据。

    返回 {"days": 将更新的天数, "items": 将写入的条目数,
          "skipped": [解析不出条目、会被跳过保护的日期], "plan_changed": bool}
    """
    parsed, plan = _parse_plain(week, text)
    days = [d for d, v in parsed.items() if v]
    skipped = [d for d, v in parsed.items()
               if not v and storage.peek_day(week, d).get("items")]
    return {"days": len(days),
            "items": sum(len(parsed[d]) for d in days),
            "skipped": sorted(skipped),
            "plan_changed": plan is not None and plan != next_week_plan(week)}


def apply_plain_back(week, text):
    """把周报预览文本解析回周数据（尽力而为）：
    回写「二、本周工作明细」的条目与「四、下周计划」，覆盖对应日期原有条目。

    保护措施（防止误改格式导致记录被清空）：
      - 某日一条都没解析出来时**跳过该日**，保留原记录，不写空列表；
      - 难点未被用户改动时恢复原始多行文本，避免原样回写就丢换行。
    返回回写的条目条数；0 表示未解析出任何明细条目（调用方可按草稿处理）。
    """
    parsed, plan = _parse_plain(week, text)

    updated = 0
    for d, items in parsed.items():
        if not items:
            continue    # 解析不出条目 → 视为格式异常，绝不覆盖原数据
        old = storage.peek_day(week, d).get("items", [])
        _restore_multiline_diff(items, old)
        day = week.setdefault("days", {}).setdefault(d, {"done": False, "items": []})
        day.setdefault("done", False)
        day["items"] = items
        updated += len(items)

    # 下周计划回写：与当前生成值一致视为未改（保持自动草拟），否则写回自定义
    if plan is not None and plan != next_week_plan(week):
        week["next_week_plan"] = plan
    return updated


# ---------- 剪贴板（CF_HTML） ----------

def _make_cf_html(html):
    """构造带正确字节偏移的 CF_HTML 文档。"""
    hdr_fmt = ("Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\n"
               "StartFragment:{:010d}\r\nEndFragment:{:010d}\r\n")
    prefix = '<html><head><meta charset="utf-8"></head><body>\r\n<!--StartFragment-->'
    suffix = '<!--EndFragment-->\r\n</body></html>'
    header = hdr_fmt.format(0, 0, 0, 0)
    start_html = len(header.encode("utf-8"))
    start_frag = start_html + len(prefix.encode("utf-8"))
    end_frag = start_frag + len(html.encode("utf-8"))
    end_html = end_frag + len(suffix.encode("utf-8"))
    header = hdr_fmt.format(start_html, end_html, start_frag, end_frag)
    return (header + prefix + html + suffix).encode("utf-8")


def _declare_win32(user32, kernel32):
    """声明 Win32 函数签名。

    必须显式指定：GlobalAlloc/GlobalLock/SetClipboardData 返回的是句柄或指针（64 位），
    而 ctypes 默认按 c_int 处理返回值，在 64 位 Python 上会被截断成 32 位，
    导致 memmove 写到非法地址（静默失败甚至崩溃）。
    """
    import ctypes
    from ctypes import wintypes
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = wintypes.BOOL


def _copy_cf_html(html):
    """通过 Win32 API 直接写 CF_HTML，成功返回 True。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        _declare_win32(user32, kernel32)
        CF_HTML = user32.RegisterClipboardFormatW("HTML Format")
        GMEM_MOVEABLE = 0x0002
        data = _make_cf_html(html) + b"\x00"   # 自带结尾 NUL，memmove 不再越界读取
        if not user32.OpenClipboard(None):
            return False
        try:
            # 先把内存准备好，确认无误再 EmptyClipboard，
            # 避免中途失败时用户原有的剪贴板内容已被清空
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                return False
            p = kernel32.GlobalLock(h)
            if not p:
                kernel32.GlobalFree(h)
                return False
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_HTML, h):
                kernel32.GlobalFree(h)   # 未接管所有权，需自行释放
                return False
        finally:
            user32.CloseClipboard()
        return True
    except Exception:
        return False


def _copy_via_powershell(html):
    """备用方案：Set-Clipboard -AsHtml。成功返回 None，失败返回错误信息。

    注意 -AsHtml 只存在于 Windows PowerShell 5.1；PowerShell 7 的 Set-Clipboard
    已移除该参数，所以这里显式调用 powershell.exe 而不是 pwsh，并在缺参数时给出明确提示。
    """
    path = os.path.join(tempfile.gettempdir(), "_worklog_clip.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        cmd = ("Get-Content -LiteralPath '{}' -Raw -Encoding UTF8 | Set-Clipboard -AsHtml"
               ).format(path.replace("'", "''"))
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            err = (r.stderr or b"").decode("utf-8", "replace").strip()
            if "AsHtml" in err:
                err = ("当前 PowerShell 不支持 Set-Clipboard -AsHtml"
                       "（该参数仅 Windows PowerShell 5.1 提供）。")
            return err or "PowerShell 执行失败"
        return None
    except FileNotFoundError:
        return "未找到 powershell.exe"
    except Exception as e:
        return str(e)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def copy_html_to_clipboard(html):
    """把 HTML 写入剪贴板（CF_HTML）。返回 (ok, err_msg)。"""
    if _copy_cf_html(html):
        return True, ""
    err = _copy_via_powershell(html)
    if err:
        return False, f"复制失败：{err}\n可改用“导出 HTML 文件”后从浏览器复制。"
    return True, ""


# ---------- 文件导出 ----------

def report_filename(week, ext):
    return f"周报_{storage.week_range_label(week).replace(' ', '')}.{ext}"


def export_file(data, week, kind, custom_text=None):
    """导出文件。kind: 'html' | 'txt'。custom_text 仅对 txt 生效（用户可修改预览后导出）。
    返回文件路径。
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, report_filename(week, kind))
    if kind == "html":
        content = build_html(data, week, full_document=True)
    else:
        content = custom_text if custom_text is not None else build_plain(data, week)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ---------- Outlook（可选） ----------

try:
    import win32com.client  # noqa: F401
    OUTLOOK_SUPPORTED = True
except ImportError:
    OUTLOOK_SUPPORTED = False


def outlook_available():
    """返回 (可用, 错误信息)。实际测试 CreateItem，新版 Outlook 的 COM 受限时会如实报错。"""
    if not OUTLOOK_SUPPORTED:
        return False, "未安装 pywin32，无法调用 Outlook。请先在命令行执行：pip install pywin32"
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        del mail
        return True, ""
    except Exception as e:
        return False, (f"无法调用 Outlook：{e}\n"
                       "若使用的是新版 Outlook（或 Outlook 未配置），"
                       "请改用“复制 HTML”后在邮件正文中 Ctrl+V。")


def open_in_outlook(subject, html, plain):
    """调起 Outlook 新建邮件并填入周报，随后用户可自行发送。"""
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.Subject = subject
    mail.Body = plain
    mail.HTMLBody = html
    mail.Display()
