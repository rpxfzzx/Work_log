# -*- coding: utf-8 -*-
"""工作日志：数据持久化与工作日历工具。

数据文件结构（data/worklog.json）：
    {"version": 1, "settings": {"reporter": ""}, "weeks": {周一日期: 周数据}}
读取时会做逐层结构校验与修复，写入为「原子写 + fsync」，并保留每日快照备份。
"""
import datetime
import glob
import json
import os
import shutil
import sys

# 打包成 exe 后（frozen），数据要写在 exe 旁边而不是临时解压目录，保证记忆功能跨重启有效
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "worklog.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backup")

DATA_VERSION = 1        # 数据结构版本，便于以后迁移
BACKUP_KEEP = 10        # 备份保留份数（超出按时间删最旧的）

WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
STATUSES = ["未开始", "进行中", "已完成"]


def _empty_data():
    return {"version": DATA_VERSION, "settings": {"reporter": ""}, "weeks": {}}


# ---------- 结构校验与修复 ----------
# 数据文件可能被手工编辑、被旧版本写过、或被同步工具截断，
# 这里逐层校验类型：结构不对就退回该层的默认值，绝不让上层因 AttributeError 崩溃。

def _is_date_str(s):
    if not isinstance(s, str):
        return False
    try:
        datetime.date.fromisoformat(s.strip())
        return True
    except ValueError:
        return False


def _clean_text(v):
    if isinstance(v, str):
        return v
    return "" if v is None else str(v)


def _clean_item(it):
    """单条记录 -> 规范结构；无法识别返回 None（丢弃）。"""
    if not isinstance(it, dict):
        return None
    status = it.get("status")
    if status not in STATUSES:
        status = "未开始"
    return {"content": _clean_text(it.get("content")),
            "status": status,
            "difficulty": _clean_text(it.get("difficulty"))}


def _clean_day(day):
    if not isinstance(day, dict):
        return {"done": False, "items": []}
    raw = day.get("items")
    items = []
    if isinstance(raw, list):
        items = [x for x in (_clean_item(i) for i in raw) if x is not None]
    return {"done": bool(day.get("done")), "items": items}


def _clean_week(key, week):
    if not isinstance(week, dict):
        week = {}
    raw_wd = week.get("workdays")
    workdays = sorted({d.strip() for d in raw_wd if _is_date_str(d)}) \
        if isinstance(raw_wd, list) else []
    raw_days = week.get("days")
    days = {}
    if isinstance(raw_days, dict):
        for d, v in raw_days.items():
            if _is_date_str(d):
                days[d.strip()] = _clean_day(v)
    out = {"start_date": key,
           "workdays": workdays,
           "next_week_plan": _clean_text(week.get("next_week_plan")),
           "days": days}
    if isinstance(week.get("report_draft"), str):
        out["report_draft"] = week["report_draft"]
    return out


def normalize_data(data):
    """把任意读入内容修成合法结构（就地不可靠，返回新对象）。"""
    if not isinstance(data, dict):
        return _empty_data()
    settings = data.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    weeks = data.get("weeks")
    clean_weeks = {}
    if isinstance(weeks, dict):
        for key, week in weeks.items():
            if _is_date_str(key):
                k = key.strip()
                clean_weeks[k] = _clean_week(k, week)
    return {"version": DATA_VERSION,
            "settings": {"reporter": _clean_text(settings.get("reporter"))},
            "weeks": clean_weeks}


# ---------- 读写 ----------

def load_data():
    """读取数据文件；不存在返回空结构，损坏则备份为 .bad 后重建，结构异常自动修复。"""
    if not os.path.exists(DATA_FILE):
        return _empty_data()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        try:
            os.replace(DATA_FILE, DATA_FILE + ".bad")
        except OSError:
            pass
        return _empty_data()
    return normalize_data(data)


def _prune_backups():
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "worklog_*.json")))
    for p in files[:-BACKUP_KEEP]:
        try:
            os.unlink(p)
        except OSError:
            pass


def snapshot(tag="auto"):
    """把当前数据文件另存一份带时间戳的备份，返回路径；无数据文件时返回 None。

    用于「周报回写、删除整周/某日」等破坏性操作之前，出问题可从 data/backup/ 取回。
    """
    if not os.path.exists(DATA_FILE):
        return None
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(BACKUP_DIR, f"worklog_{stamp}_{tag}.json")
        shutil.copy2(DATA_FILE, path)
        _prune_backups()
        return path
    except OSError:
        return None


def _daily_backup():
    """每天首次保存前留一份当日快照（记录的是「今天开始编辑之前」的状态）。"""
    if not os.path.exists(DATA_FILE):
        return
    day = datetime.date.today().strftime("%Y%m%d")
    marker = os.path.join(BACKUP_DIR, f"worklog_{day}_000000_daily.json")
    if os.path.exists(marker):
        return
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        shutil.copy2(DATA_FILE, marker)
        _prune_backups()
    except OSError:
        pass


def save_data(data, backup=True):
    """原子写入：先写临时文件、flush+fsync 落盘，再替换，防止写入中断或断电损坏数据。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    if backup:
        _daily_backup()
    data.setdefault("version", DATA_VERSION)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())   # 保证内容真正落盘后再替换，避免断电得到空文件
    os.replace(tmp, DATA_FILE)


# ---------- 日期工具 ----------

def parse_date(s):
    """'2026-08-19' -> date；格式错误抛 ValueError。"""
    return datetime.date.fromisoformat(str(s).strip())


def format_date(d):
    """date 或 '2026-08-19' -> '2026-08-19'"""
    if isinstance(d, str):
        d = parse_date(d)
    return d.isoformat()


def short_date(d):
    """date 或 '2026-08-19' -> '2026.08.19'"""
    if isinstance(d, str):
        d = parse_date(d)
    return format_date(d).replace("-", ".")


def monday_of(d):
    """date -> 所在周的周一"""
    return d - datetime.timedelta(days=d.weekday())


def weekday_cn(d):
    """date 或 '2026-08-19' -> '星期三'"""
    if isinstance(d, str):
        d = parse_date(d)
    return WEEKDAY_NAMES[d.weekday()]


def make_workdays(start_date, weekday_flags):
    """从 start_date 所在周的周一开始，取勾选的星期，返回日期字符串列表（升序）。
    weekday_flags: 长度 7 的布尔列表，索引 0 = 周一。
    """
    monday = monday_of(start_date)
    return [format_date(monday + datetime.timedelta(days=i))
            for i in range(7) if weekday_flags[i]]


# ---------- 数据访问 ----------

def get_week(data, key):
    """按周 key（周一日期字符串）取周数据，不存在则创建空结构。"""
    return data["weeks"].setdefault(
        key, {"start_date": key, "workdays": [], "next_week_plan": "", "days": {}})


def get_day(week, date_str):
    """取某日数据，不存在则创建空结构。"""
    return week["days"].setdefault(date_str, {"done": False, "items": []})


def peek_day(week, date_str):
    """只读取某日数据，不会在数据里创建空条目（用于刷新界面/统计）。"""
    day = week.get("days", {}).get(date_str)
    return day if isinstance(day, dict) else {"done": False, "items": []}


def prev_workday(data, week_key, date_str):
    """返回该工作日的上一个工作日（可跨周），没有则 None。"""
    week = data["weeks"].get(week_key)
    wd = week.get("workdays", []) if week else []
    if date_str in wd:
        i = wd.index(date_str)
        if i > 0:
            return week_key, wd[i - 1]
    keys = sorted(k for k in data["weeks"] if k < (week_key or ""))
    for k in reversed(keys):
        pwd = data["weeks"][k].get("workdays", [])
        if pwd:
            return k, pwd[-1]
    return None


def week_range_label(week):
    """'2026.08.17 ~ 2026.08.21'（取首个与末个工作日）。"""
    wd = week.get("workdays") or []
    if wd:
        return f"{short_date(wd[0])} ~ {short_date(wd[-1])}"
    monday = monday_of(parse_date(week.get("start_date", format_date(datetime.date.today()))))
    return f"{short_date(monday)} ~ {short_date(monday + datetime.timedelta(days=6))}"
