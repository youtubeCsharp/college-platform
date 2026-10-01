# -*- coding: utf-8 -*-
"""台账业务:三办物理隔离、只增/改/作废不物理删除、全程留痕。"""
from datetime import datetime

from .storage import (OFFICES, OFFICE_PREFIX, append_log, ledger_path,
                      read_rows, write_rows)

CATEGORIES = {
    "综合办": ["党建工作", "行政事务", "会议与接待", "文件流转", "人事考勤", "宣传信息", "其他"],
    "教学办": ["教学运行", "考试考务", "教学检查", "实践教学", "教研活动", "学籍管理", "其他"],
    "学生办": ["学生活动", "奖助勤贷", "心理健康", "就业创业", "宿舍管理", "团学工作", "其他"],
}

COMPLETION_OPTIONS = ["已完成", "进行中", "待推进"]


def visible_offices(user) -> list:
    if user["role"] in ("admin", "leader"):
        return list(OFFICES)
    return [user["office"]]


def can_edit(user, office: str) -> bool:
    return user["role"] == "office" and user["office"] == office


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _valid_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def _check_office(user, office):
    if office not in OFFICES:
        raise ValueError("部门不存在。")
    if not can_edit(user, office):
        raise PermissionError("权限隔离:只能操作本部门台账。")


def add_entry(user, office: str, data: dict) -> dict:
    _check_office(user, office)
    date = (data.get("date") or "").strip()
    if not _valid_date(date):
        raise ValueError("日期格式不正确。")
    content = (data.get("content") or "").strip()
    if not content:
        raise ValueError("工作内容不能为空。")
    category = data.get("category") if data.get("category") in CATEGORIES[office] else "其他"
    completion = data.get("completion") if data.get("completion") in COMPLETION_OPTIONS else "已完成"
    sensitive = bool(data.get("sensitive"))
    attachments = ";".join(data.get("attachments") or [])

    rows = read_rows(ledger_path(office), "台账")
    prefix = OFFICE_PREFIX[office]
    day_key = date.replace("-", "")
    head = f"{prefix}-{day_key}-"
    seq = 1
    for r in rows:
        if r.get("编号", "").startswith(head):
            try:
                seq = max(seq, int(r["编号"][len(head):]) + 1)
            except ValueError:
                pass
    entry_id = f"{head}{seq:03d}"

    row = {"编号": entry_id, "日期": date, "工作大类": category, "工作内容": content,
           "完成情况": completion, "参与人员": (data.get("participants") or "").strip(),
           "备注": (data.get("remark") or "").strip(),
           "敏感事项": "是" if sensitive else "否", "附件": attachments,
           "录入人": user["name"], "录入时间": _now(),
           "最后修改人": "", "最后修改时间": "", "状态": "正常"}
    rows.append(row)
    write_rows(ledger_path(office), "台账", rows)
    append_log(user["username"], "新增台账", f"{office} {entry_id}")
    return row


def update_entry(user, office: str, entry_id: str, data: dict) -> dict:
    _check_office(user, office)
    rows = read_rows(ledger_path(office), "台账")
    target = None
    for r in rows:
        if r.get("编号") == entry_id and r.get("状态") == "正常":
            target = r
            break
    if target is None:
        raise ValueError("未找到该条台账,或其已作废。")
    if not (data.get("content") or "").strip():
        raise ValueError("工作内容不能为空。")

    if data.get("category") in CATEGORIES[office]:
        target["工作大类"] = data["category"]
    if data.get("completion") in COMPLETION_OPTIONS:
        target["完成情况"] = data["completion"]
    target["工作内容"] = data["content"].strip()
    target["参与人员"] = (data.get("participants") or "").strip()
    target["备注"] = (data.get("remark") or "").strip()
    target["敏感事项"] = "是" if data.get("sensitive") else "否"

    # 附件:移除勾选项(仅断开链接,不动归档文件),再追加新上传
    keep = [p for p in (target.get("附件") or "").split(";") if p]
    remove = set(data.get("remove_attachments") or [])
    keep = [p for p in keep if p not in remove]
    keep += list(data.get("add_attachments") or [])
    target["附件"] = ";".join(keep)

    target["最后修改人"] = user["name"]
    target["最后修改时间"] = _now()
    write_rows(ledger_path(office), "台账", rows)
    append_log(user["username"], "修改台账", f"{office} {entry_id}")
    return target


def void_entry(user, office: str, entry_id: str) -> dict:
    _check_office(user, office)
    rows = read_rows(ledger_path(office), "台账")
    target = None
    for r in rows:
        if r.get("编号") == entry_id and r.get("状态") == "正常":
            target = r
            break
    if target is None:
        raise ValueError("未找到该条台账,或其已作废。")
    target["状态"] = "作废"
    target["最后修改人"] = user["name"]
    target["最后修改时间"] = _now()
    write_rows(ledger_path(office), "台账", rows)
    append_log(user["username"], "作废台账", f"{office} {entry_id}")
    return target


def get_day(user, date: str) -> dict:
    if not _valid_date(date):
        raise ValueError("日期格式不正确。")
    out = {}
    for office in visible_offices(user):
        rows = read_rows(ledger_path(office), "台账")
        out[office] = [r for r in rows
                       if r.get("日期") == date and r.get("状态") == "正常"]
    return out


def month_counts(user, year: int, month: int) -> dict:
    """{部门: {日: 条数}},仅正常状态。"""
    prefix = f"{year:04d}-{month:02d}"
    out = {}
    for office in visible_offices(user):
        rows = read_rows(ledger_path(office), "台账")
        days = {}
        for r in rows:
            if r.get("状态") != "正常":
                continue
            d = r.get("日期") or ""
            if d.startswith(prefix):
                day = int(d.split("-")[2])
                days[day] = days.get(day, 0) + 1
        out[office] = {str(k): v for k, v in days.items()}
    return out
