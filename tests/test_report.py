# -*- coding: utf-8 -*-
"""report.py 的纯逻辑单测（不依赖 Tk，可在 CI 中运行）。

运行：pytest -q
"""
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import report      # noqa: E402
import storage     # noqa: E402

DATA = {"settings": {"reporter": ""}, "weeks": {}}


def make_week(days, workdays=None, plan=""):
    wd = workdays or sorted(days)
    return {"start_date": wd[0], "workdays": wd, "next_week_plan": plan,
            "days": {d: {"done": True, "items": items} for d, items in days.items()}}


def item(content, status="未开始", difficulty=""):
    return {"content": content, "status": status, "difficulty": difficulty}


# ---------- 统计口径 ----------

def test_跨日重复事项在概述中只算一项():
    """同一件事连记三天，「记录条数」是 3，但「推进事项」应该是 1。"""
    w = make_week({
        "2026-08-17": [item("重构订单模块", "进行中")],
        "2026-08-18": [item("重构订单模块", "进行中")],
        "2026-08-19": [item("重构订单模块", "已完成")],
    })
    stats, _ = report.collect_stats(w)
    assert stats["total"] == 3
    assert stats["unique"] == {"total": 1, "done": 1, "doing": 0, "todo": 0}
    s = report.overview_sentence(w)
    assert "推进事项 1 项" in s and "已完成 1 项" in s and "共记录 3 条明细" in s


def test_不同事项分别计数且条数与项数一致时不显示括号():
    w = make_week({"2026-08-17": [item("A", "已完成"), item("B", "未开始")]})
    stats, _ = report.collect_stats(w)
    assert stats["unique"] == {"total": 2, "done": 1, "doing": 0, "todo": 1}
    assert "共记录" not in report.overview_sentence(w)


def test_内容为空的条目各算一项不被误合并():
    w = make_week({"2026-08-17": [item("", "未开始", "难点甲"),
                                  item("", "未开始", "难点乙")]})
    stats, diffs = report.collect_stats(w)
    assert stats["unique"]["total"] == 2
    assert len(diffs) == 2


def test_跨日关联_进行中事项后续完成算已完成():
    w = make_week({
        "2026-08-17": [item("联调接口", "进行中")],
        "2026-08-19": [item("联调接口", "已完成")],
    })
    stats, _ = report.collect_stats(w)
    assert stats["merged"] == {("2026-08-17", 0): "2026-08-19"}
    assert stats["done"] == 2 and stats["doing"] == 0
    assert "联调接口" not in report.next_week_plan(w)


def test_统计不会往数据里写入空的日期条目():
    """刷新界面/生成周报是只读操作，不应把没记录的日期写成空结构。"""
    w = make_week({"2026-08-17": [item("A")]}, workdays=["2026-08-17", "2026-08-18"])
    report.collect_stats(w)
    report.build_plain(DATA, w)
    assert "2026-08-18" not in w["days"]


# ---------- 跨周关联 ----------

def make_data(*weeks):
    """把 make_week 产出的周拼成 data 结构（key 取周的 start_date）。"""
    return {"settings": {"reporter": ""},
            "weeks": {w["start_date"]: w for w in weeks}}


def test_跨周关联_上周进行中下周完成算已完成():
    wa = make_week({"2026-08-17": [item("跨周事项", "进行中")]})
    wb = make_week({"2026-08-25": [item("跨周事项", "已完成")]})
    data = make_data(wa, wb)
    stats, _ = report.collect_stats(wa, data)
    assert stats["merged"] == {("2026-08-17", 0): "2026-08-25"}
    assert stats["done"] == 1 and stats["doing"] == 0
    assert "跨周事项" not in report.next_week_plan(wa, data)
    assert "已于 2026.08.25 完成，下周" in report.build_html(data, wa)
    assert "（已于 2026.08.25 完成，下周）" in report.build_plain(data, wa)


def test_跨周关联_反向注记承接():
    wa = make_week({"2026-08-17": [item("跨周事项", "进行中")]})
    wb = make_week({"2026-08-25": [item("跨周事项", "已完成")]})
    data = make_data(wa, wb)
    stats, _ = report.collect_stats(wb, data)
    assert stats["carried"] == {("2026-08-25", 0): "2026-08-17"}
    assert "承接 2026.08.17，上周" in report.build_html(data, wb)
    assert "（承接 2026.08.17，上周）" in report.build_plain(data, wb)


def test_跨周关联_不传data时保持只关联同周():
    wa = make_week({"2026-08-17": [item("跨周事项", "进行中")]})
    stats, _ = report.collect_stats(wa)
    assert stats["merged"] == {} and stats["carried"] == {}
    assert stats["doing"] == 1


def test_跨周关联_取最早完成与最早开始():
    wa = make_week({"2026-08-17": [item("跨周事项", "进行中")]})
    wb = make_week({"2026-08-24": [item("跨周事项", "进行中")],
                    "2026-08-25": [item("跨周事项", "进行中")]})
    wc = make_week({"2026-08-31": [item("跨周事项", "进行中")],
                    "2026-09-02": [item("跨周事项", "已完成")]})
    data = make_data(wa, wb, wc)
    stats_a, _ = report.collect_stats(wa, data)
    assert stats_a["merged"] == {("2026-08-17", 0): "2026-09-02"}
    assert "已于 2026.09.02 完成，后 2 周" in report.build_html(data, wa)
    stats_c, _ = report.collect_stats(wc, data)
    assert stats_c["carried"] == {("2026-09-02", 0): "2026-08-17"}
    assert "承接 2026.08.17，前 2 周" in report.build_html(data, wc)


def test_跨周关联_同周内完成优先于跨周完成():
    """本周后续已完成时按同周日期注记，不取更晚周的完成日期。"""
    wa = make_week({"2026-08-17": [item("跨周事项", "进行中")],
                    "2026-08-19": [item("跨周事项", "已完成")]})
    wb = make_week({"2026-08-25": [item("跨周事项", "已完成")]})
    data = make_data(wa, wb)
    stats, _ = report.collect_stats(wa, data)
    assert stats["merged"] == {("2026-08-17", 0): "2026-08-19"}
    assert "，下周" not in report.build_html(data, wa)  # 同周完成，不注「下周」


def test_week_gap_label():
    w = {"start_date": "2026-08-17"}
    assert report.week_gap_label(w, "2026-08-19") == ""
    assert report.week_gap_label(w, "2026-08-24") == "下周"
    assert report.week_gap_label(w, "2026-09-02") == "后 2 周"
    assert report.week_gap_label(w, "2026-08-14") == "上周"
    assert report.week_gap_label(w, "2026-08-07") == "前 2 周"
    assert report.week_gap_label(w, "不是日期") == ""


# ---------- 搜索 ----------

def test_搜索_模糊匹配内容与多关键词():
    data = make_data(make_week({
        "2026-08-17": [item("支付接口联调", "进行中", "验签报错")],
        "2026-08-18": [item("登录模块开发", "已完成")]}))
    hits = report.search_items(data, "联调")
    assert len(hits) == 1 and hits[0]["date"] == "2026-08-17"
    assert len(report.search_items(data, "支付 联调")) == 1    # 多词 AND
    assert report.search_items(data, "支付 登录") == []         # 须全部命中


def test_搜索_难点与状态也能搜到():
    data = make_data(make_week({
        "2026-08-17": [item("联调支付", "进行中", "验签报错\n等供应商回复")]}))
    assert len(report.search_items(data, "验签")) == 1
    assert report.search_items(data, "已完成") == []
    assert len(report.search_items(data, "进行中")) == 1


def test_搜索_大小写不敏感():
    data = make_data(make_week({"2026-08-17": [item("API 接口对接", "已完成")]}))
    assert len(report.search_items(data, "api")) == 1
    assert len(report.search_items(data, "API")) == 1


def test_搜索_下周计划也能搜到():
    data = make_data(make_week({"2026-08-17": [item("写方案", "进行中")]},
                               plan="下周推进数据迁移"))
    hits = report.search_items(data, "数据迁移")
    assert len(hits) == 1 and hits[0]["kind"] == "plan"


def test_搜索_结果按周从新到旧():
    data = make_data(
        make_week({"2026-08-17": [item("重复事项", "进行中")]}),
        make_week({"2026-08-24": [item("重复事项", "已完成")]}))
    hits = report.search_items(data, "重复事项")
    assert [h["week_key"] for h in hits] == ["2026-08-24", "2026-08-17"]


def test_搜索_空关键词返回空():
    data = make_data(make_week({"2026-08-17": [item("A")]}))
    assert report.search_items(data, "  ") == []
    assert report.search_items(data, "") == []


# ---------- 下周计划 ----------

def test_下周计划自动草拟去重():
    w = make_week({
        "2026-08-17": [item("写方案", "进行中")],
        "2026-08-18": [item("写方案", "进行中")],
    })
    plan = report.next_week_plan(w)
    assert plan.count("写方案") == 1


def test_下周计划优先使用用户填写内容():
    w = make_week({"2026-08-17": [item("写方案", "进行中")]}, plan="下周休假")
    assert report.next_week_plan(w) == "下周休假"


def test_未收尾事项列表可用于承接到新周():
    w = make_week({
        "2026-08-17": [item("A", "进行中"), item("B", "已完成")],
        "2026-08-18": [item("A", "已完成"), item("C", "未开始", "缺资料")],
    })
    carry = report.unfinished_items(w)
    assert [c["content"] for c in carry] == ["C"]
    assert carry[0]["difficulty"] == "缺资料"


# ---------- 回写保护（P0） ----------

def test_原样回写不改变任何数据():
    w = make_week({"2026-08-17": [item("联调支付", "进行中", "验签报错\n等供应商回复")]})
    before = copy.deepcopy(w["days"])
    report.apply_plain_back(w, report.build_plain(DATA, w))
    assert w["days"] == before


def test_多行难点原样回写不被压成一行():
    """build_plain 会把难点压平成「验签报错；等供应商回复」，回写时必须还原换行。"""
    w = make_week({"2026-08-17": [item("联调支付", "进行中", "验签报错\n等供应商回复")]})
    report.apply_plain_back(w, report.build_plain(DATA, w))
    assert w["days"]["2026-08-17"]["items"][0]["difficulty"] == "验签报错\n等供应商回复"


def test_用户确实修改了难点时以修改后的为准():
    w = make_week({"2026-08-17": [item("联调支付", "进行中", "验签报错\n等供应商回复")]})
    text = report.build_plain(DATA, w).replace("验签报错；等供应商回复", "供应商已回复")
    report.apply_plain_back(w, text)
    assert w["days"]["2026-08-17"]["items"][0]["difficulty"] == "供应商已回复"


def test_条目行格式被改坏时不清空当日记录():
    """这是原实现最危险的行为：解析不出条目就把当天写成空列表并落盘。"""
    w = make_week({"2026-08-17": [item("联调支付", "进行中")],
                   "2026-08-18": [item("写文档", "已完成")]})
    broken = report.build_plain(DATA, w).replace(
        "1. 联调支付 —— 进行中", "1、联调支付：进行中")
    n = report.apply_plain_back(w, broken)
    assert w["days"]["2026-08-17"]["items"] == [item("联调支付", "进行中")]
    assert n == 1     # 只回写了解析成功的周二


def test_回写前的影响评估能报出会被跳过的日期():
    w = make_week({"2026-08-17": [item("联调支付", "进行中")],
                   "2026-08-18": [item("写文档", "已完成")]})
    broken = report.build_plain(DATA, w).replace(
        "1. 联调支付 —— 进行中", "1、联调支付：进行中")
    info = report.plain_back_summary(w, broken)
    assert info["skipped"] == ["2026-08-17"]
    assert info["days"] == 1 and info["items"] == 1
    # 评估是只读的
    assert w["days"]["2026-08-17"]["items"] == [item("联调支付", "进行中")]


def test_回写能正常修改内容与状态():
    w = make_week({"2026-08-17": [item("联调支付", "进行中")]})
    text = report.build_plain(DATA, w).replace(
        "1. 联调支付 —— 进行中", "1. 联调支付 —— 已完成")
    assert report.apply_plain_back(w, text) == 1
    assert w["days"]["2026-08-17"]["items"][0]["status"] == "已完成"


def test_多行工作内容回写保留换行():
    w = make_week({"2026-08-17": [item("支付接口联调\n与供应商核对验签", "进行中")]})
    report.apply_plain_back(w, report.build_plain(DATA, w))
    assert w["days"]["2026-08-17"]["items"][0]["content"] == "支付接口联调\n与供应商核对验签"


def test_回写不会给未在文本中出现的日期建空结构():
    w = make_week({"2026-08-17": [item("A", "进行中")]},
                  workdays=["2026-08-17", "2026-08-18"])
    report.apply_plain_back(w, report.build_plain(DATA, w))
    assert "2026-08-18" not in w["days"]


# ---------- 输出格式 ----------

def test_html_全内联样式且转义():
    w = make_week({"2026-08-17": [item("<script>x</script>\n第二行", "已完成")]})
    html = report.build_html(DATA, w)
    assert "class=" not in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<br>" in html


def test_汇报人填写后出现在周报中():
    w = make_week({"2026-08-17": [item("A")]})
    data = {"settings": {"reporter": "张三"}}
    assert "汇报人：张三" in report.build_html(data, w)
    assert "汇报人：张三" in report.build_plain(data, w)
    assert "汇报人" not in report.build_plain(DATA, w)


def test_cf_html_偏移量正确():
    body = "<div>测试</div>"
    raw = report._make_cf_html(body)
    def num(field):
        i = raw.index(field.encode()) + len(field) + 1
        return int(raw[i:i + 10])
    assert raw[num("StartFragment"):num("EndFragment")].decode("utf-8") == body
    assert num("EndHTML") == len(raw)


@pytest.mark.parametrize("bad", [None, {}, {"days": None}, {"workdays": "x"}])
def test_统计不会因结构异常崩溃(bad):
    w = storage._clean_week("2026-08-17", bad)
    report.collect_stats(w)
    report.build_plain(DATA, w)
    report.build_html(DATA, w)
