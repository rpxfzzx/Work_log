# -*- coding: utf-8 -*-
"""storage.py 的持久化 / 容错单测。"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage   # noqa: E402


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """把数据文件重定向到临时目录，避免污染真实 data/。"""
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "worklog.json"))
    monkeypatch.setattr(storage, "BACKUP_DIR", str(tmp_path / "backup"))
    return tmp_path


def write_raw(tmp_store, text):
    (tmp_store / "worklog.json").write_text(text, encoding="utf-8")


# ---------- 容错 ----------

def test_文件不存在返回空结构(tmp_store):
    d = storage.load_data()
    assert d == {"version": storage.DATA_VERSION,
                 "settings": {"reporter": ""}, "weeks": {}}


def test_json损坏时备份为bad并重建(tmp_store):
    write_raw(tmp_store, "{不是合法 json")
    d = storage.load_data()
    assert d["weeks"] == {}
    assert (tmp_store / "worklog.json.bad").exists()


@pytest.mark.parametrize("raw", [
    '[]',                                   # 顶层是数组
    '{"weeks": []}',                        # weeks 是数组
    '{"weeks": {"2026-08-17": "oops"}}',    # 周数据是字符串
    '{"weeks": {"不是日期": {}}}',            # 周 key 非法
    '{"settings": "oops", "weeks": {}}',    # settings 类型错
    'null',
])
def test_结构异常被修复而不是崩溃(tmp_store, raw):
    """原实现只 setdefault，遇到这些输入会在后续 AttributeError 崩溃。"""
    write_raw(tmp_store, raw)
    d = storage.load_data()
    assert isinstance(d["weeks"], dict)
    assert isinstance(d["settings"]["reporter"], str)
    storage.get_week(d, "2026-08-17")       # 不应抛异常


def test_非法状态被归一到未开始(tmp_store):
    write_raw(tmp_store, json.dumps({"weeks": {"2026-08-17": {"days": {
        "2026-08-17": {"items": [{"content": "A", "status": "已归档"}]}}}}}))
    it = storage.load_data()["weeks"]["2026-08-17"]["days"]["2026-08-17"]["items"][0]
    assert it["status"] == "未开始" and it["difficulty"] == ""


def test_条目里的非字典项被丢弃(tmp_store):
    write_raw(tmp_store, json.dumps({"weeks": {"2026-08-17": {"days": {
        "2026-08-17": {"items": ["坏数据", {"content": "A", "status": "已完成"}]}}}}}))
    items = storage.load_data()["weeks"]["2026-08-17"]["days"]["2026-08-17"]["items"]
    assert len(items) == 1 and items[0]["content"] == "A"


def test_周报草稿字段被保留(tmp_store):
    write_raw(tmp_store, json.dumps({"weeks": {"2026-08-17": {"report_draft": "草稿"}}}))
    assert storage.load_data()["weeks"]["2026-08-17"]["report_draft"] == "草稿"


# ---------- 写入 ----------

def test_保存后可原样读回并带版本号(tmp_store):
    d = storage._empty_data()
    w = storage.get_week(d, "2026-08-17")
    w["workdays"] = ["2026-08-17"]
    storage.get_day(w, "2026-08-17")["items"] = [
        {"content": "多行\n内容", "status": "进行中", "difficulty": ""}]
    storage.save_data(d)
    back = storage.load_data()
    assert back["version"] == storage.DATA_VERSION
    assert back["weeks"]["2026-08-17"]["days"]["2026-08-17"]["items"][0]["content"] == "多行\n内容"


def test_保存不留临时文件(tmp_store):
    storage.save_data(storage._empty_data())
    assert not (tmp_store / "worklog.json.tmp").exists()


def test_快照可用于恢复(tmp_store):
    d = storage._empty_data()
    storage.get_week(d, "2026-08-17")["workdays"] = ["2026-08-17"]
    storage.save_data(d)
    snap = storage.snapshot("test")
    d["weeks"].clear()                       # 模拟误删
    storage.save_data(d)
    assert storage.load_data()["weeks"] == {}
    restored = json.load(open(snap, encoding="utf-8"))
    assert "2026-08-17" in restored["weeks"]


def test_备份数量受限(tmp_store):
    storage.save_data(storage._empty_data())
    for i in range(storage.BACKUP_KEEP + 5):
        storage.snapshot(f"t{i:02d}")
    files = os.listdir(storage.BACKUP_DIR)
    assert len(files) <= storage.BACKUP_KEEP


# ---------- 日期工具 ----------

def test_peek_day不会写入数据():
    week = {"workdays": ["2026-08-17"], "days": {}}
    assert storage.peek_day(week, "2026-08-17") == {"done": False, "items": []}
    assert week["days"] == {}


def test_prev_workday可跨周回溯():
    data = {"weeks": {
        "2026-08-10": {"workdays": ["2026-08-13", "2026-08-14"]},
        "2026-08-17": {"workdays": ["2026-08-17", "2026-08-18"]}}}
    assert storage.prev_workday(data, "2026-08-17", "2026-08-18") == ("2026-08-17", "2026-08-17")
    assert storage.prev_workday(data, "2026-08-17", "2026-08-17") == ("2026-08-10", "2026-08-14")
    assert storage.prev_workday(data, "2026-08-10", "2026-08-13") is None


def test_make_workdays只取勾选的星期():
    import datetime
    d = datetime.date(2026, 8, 19)   # 星期三
    wd = storage.make_workdays(d, [True, False, True, False, True, False, False])
    assert wd == ["2026-08-17", "2026-08-19", "2026-08-21"]


def test_week_range_label无工作日时按整周():
    assert storage.week_range_label({"start_date": "2026-08-19", "workdays": []}) == \
        "2026.08.17 ~ 2026.08.23"
