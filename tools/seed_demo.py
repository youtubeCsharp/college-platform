# -*- coding: utf-8 -*-
"""写入演示数据(仅当三本台账均为空时执行,便于首次演示;正式使用前可忽略)。

运行: python tools/seed_demo.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ledger, tasks
from core.storage import init_storage, ledger_path, read_rows

init_storage()

USERS = {
    "综合办": {"username": "zhb", "name": "综合办负责人", "role": "office", "office": "综合办"},
    "教学办": {"username": "jxb", "name": "教学办负责人", "role": "office", "office": "教学办"},
    "学生办": {"username": "xsb", "name": "学生办负责人", "role": "office", "office": "学生办"},
    "领导": {"username": "leader", "name": "院领导", "role": "leader", "office": ""},
}

SAMPLES = [
    ("综合办", 0, "党建工作", "组织学院党总支理论学习中心组(扩大)学习会,专题学习党的二十届三中全会精神", "已完成", "党总支委员"),
    ("综合办", 0, "行政事务", "完成9月份学院考勤汇总并报送人事处", "已完成", ""),
    ("教学办", 0, "教学运行", "组织2026级新生课程补退选,处理选课异常申请17条", "进行中", "教学办全体"),
    ("教学办", 0, "考试考务", "起草10月中旬期中考试考场安排初稿", "进行中", ""),
    ("教学办", 0, "学籍管理", "办理个别学生学籍异动事项(内部处理,暂缓公开)", "已完成", "", True),
    ("学生办", 0, "学生活动", "举办迎新晚会第二次节目审核,确定15个入选节目", "已完成", "团学骨干"),
    ("学生办", 0, "就业创业", "发布2026届毕业生秋季双选会邀请函,已联系32家单位", "已完成", ""),
    ("综合办", 7, "宣传信息", "采写学院迎新工作新闻稿并报送校园网主页", "已完成", ""),
    ("教学办", 7, "教研活动", "组织数字经济专业人才培养方案修订研讨会", "已完成", "各系主任"),
    ("学生办", 14, "奖助勤贷", "开展2026年国家奖助学金评审材料初审", "进行中", "资助专员"),
    ("综合办", 14, "会议与接待", "接待校教学督导组来院检查,安排会议与陪同路线", "已完成", ""),
]

empty = all(not read_rows(ledger_path(o), "台账") for o in ("综合办", "教学办", "学生办"))
if not empty:
    print("台账中已有数据,跳过演示数据写入。")
    sys.exit(0)

today = datetime.now()
for office, offset, cat, content, done, parts, *rest in SAMPLES:
    sensitive = bool(rest and rest[0])
    date = (today + timedelta(days=offset - 3)).strftime("%Y-%m-%d")
    ledger.add_entry(USERS[office], office, {
        "date": date, "category": cat, "content": content,
        "completion": done, "participants": parts, "remark": "",
        "sensitive": sensitive, "attachments": [],
    })

leader = USERS["领导"]
t1 = tasks.create_task(leader, {
    "title": "报送10月份教学工作月报", "dept": "教学办", "owner": "",
    "due": (today + timedelta(days=3)).strftime("%Y-%m-%d"),
    "priority": "高", "desc": "按教务处模板汇总本月教学运行数据,报综合办复核后上报。",
})
t2 = tasks.create_task(leader, {
    "title": "筹备学院学术月活动方案", "dept": "学生办", "owner": "",
    "due": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
    "priority": "中", "desc": "拟定活动方案、场地与经费需求,提交院务会审议。",
})
tasks.reply_task(USERS["学生办"], t2["任务编号"], "方案初稿已完成,场地预算需学院协调报告厅使用档期。", "进行中", True)

print("演示数据写入完成:三办台账共 %d 条,任务 2 项。" % len(SAMPLES))
