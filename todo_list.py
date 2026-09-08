# -*- coding: utf-8 -*-
"""常用工作清单：自定义日常常做的工作，录入时下拉选择。

清单文件：todo_list-config/todo_list.json（随程序目录走，exe 旁），结构：
    {"items": ["整理周报", "回复邮件", ...]}

读取时自动修复结构（去空行、去重复、非字符串转文本），写入为原子写。
"""
import json
import os

import storage

TODO_DIR = os.path.join(storage.BASE_DIR, "todo_list-config")
TODO_FILE = os.path.join(TODO_DIR, "todo_list.json")


def load_items():
    """读取常用工作清单（保持原始顺序）；文件不存在或损坏返回 []。"""
    if not os.path.exists(TODO_FILE):
        return []
    try:
        with open(TODO_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (ValueError, OSError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    seen = set()
    for it in items:
        if it is None:
            continue
        s = it.strip() if isinstance(it, str) else str(it).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def save_items(items):
    """覆盖写入常用工作清单（自动去空行、去重复，原子写）。"""
    clean = []
    seen = set()
    for it in items:
        if it is None:
            continue
        s = it.strip() if isinstance(it, str) else str(it).strip()
        if s and s not in seen:
            seen.add(s)
            clean.append(s)
    os.makedirs(TODO_DIR, exist_ok=True)
    storage.cleanup_stale_tmp(TODO_FILE)
    tmp = f"{TODO_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"items": clean}, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, TODO_FILE)


def ensure_file():
    """应用启动时调用：清单目录与文件不存在则创建（空清单），保证用户能看到配置位置。"""
    if not os.path.exists(TODO_FILE):
        save_items([])
