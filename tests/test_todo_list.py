# -*- coding: utf-8 -*-
"""todo_list.py 的读写单测。"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import todo_list   # noqa: E402


def _redirect(tmp_path, monkeypatch):
    """把清单文件重定向到临时目录，避免污染真实 todo_list-config/。"""
    monkeypatch.setattr(todo_list, "TODO_DIR", str(tmp_path))
    monkeypatch.setattr(todo_list, "TODO_FILE", str(tmp_path / "todo_list.json"))


def test_无文件返回空清单(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    assert todo_list.load_items() == []


def test_保存后原样读回(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    todo_list.save_items(["整理周报", "回复邮件"])
    assert todo_list.load_items() == ["整理周报", "回复邮件"]
    assert (tmp_path / "todo_list.json").exists()


def test_保存时去空行去重复且保持顺序(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    todo_list.save_items(["A", "", "  B  ", "A", None])
    assert todo_list.load_items() == ["A", "B"]


def test_json损坏返回空清单(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    (tmp_path / "todo_list.json").write_text("{不是 json", encoding="utf-8")
    assert todo_list.load_items() == []


def test_结构异常读取时自动修复(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    (tmp_path / "todo_list.json").write_text(
        json.dumps({"items": ["A", 123, None, " B "]}, ensure_ascii=False), encoding="utf-8")
    assert todo_list.load_items() == ["A", "123", "B"]
