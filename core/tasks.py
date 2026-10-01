# -*- coding: utf-8 -*-
"""工作安排与跟进:发布-接收-回复进度/申请协调-办结,回复只增不删。"""
from datetime import datetime

from .storage import OFFICES, append_log, read_rows, task_path, write_rows

STATUSES = ["待接收", "进行中", "已完成", "已延期"]
PRIORITIES = ["高", "中", "低"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _valid_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def can_publish(user) -> bool:
    return user["role"] in ("admin", "leader") or \
        (user["role"] == "office" and user["office"] == "综合办")


def can_manage(user) -> bool:
    return user["role"] in ("admin", "leader")


def can_reply(user, task: dict) -> bool:
    if user["role"] in ("admin", "leader"):
        return True
    return user["role"] == "office" and user["office"] == task.get("指派部门")


def _visible(user, rows: list) -> list:
    if user["role"] in ("admin", "leader"):
        return rows
    return [r for r in rows if r.get("指派部门") == user["office"]]


def create_task(user, data: dict) -> dict:
    if not can_publish(user):
        raise PermissionError("当前账号无发布任务权限。")
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("任务标题不能为空。")
    dept = data.get("dept")
    if dept not in OFFICES:
        raise ValueError("指派部门不正确。")
    due = (data.get("due") or "").strip()
    if not _valid_date(due):
        raise ValueError("截止日期格式不正确。")
    priority = data.get("priority") if data.get("priority") in PRIORITIES else "中"

    rows = read_rows(task_path(), "任务表")
    today = datetime.now().strftime("%Y%m%d")
    head = f"RW-{today}-"
    seq = 1
    for r in rows:
        if r.get("任务编号", "").startswith(head):
            try:
                seq = max(seq, int(r["任务编号"][len(head):]) + 1)
            except ValueError:
                pass
    task_id = f"{head}{seq:03d}"
    row = {"任务编号": task_id, "任务标题": title, "指派部门": dept,
           "责任人": (data.get("owner") or "").strip(), "截止日期": due,
           "优先级": priority, "工作说明": (data.get("desc") or "").strip(),
           "状态": "待接收", "需协调资源": "否",
           "发布人": user["name"], "发布时间": _now(), "办结时间": ""}
    rows.append(row)
    write_rows(task_path(), "任务表", rows)
    append_log(user["username"], "发布任务", task_id)
    return row


def list_tasks(user, status: str = "", dept: str = "", coord: bool = False,
               due: str = "") -> list:
    rows = _visible(user, read_rows(task_path(), "任务表"))
    if status:
        rows = [r for r in rows if r.get("状态") == status]
    if dept and user["role"] in ("admin", "leader"):
        rows = [r for r in rows if r.get("指派部门") == dept]
    if coord:
        rows = [r for r in rows if r.get("需协调资源") == "是" and r.get("状态") != "已完成"]
    if due:
        rows = [r for r in rows if r.get("截止日期") == due]
    rows.sort(key=lambda r: r.get("发布时间") or "", reverse=True)
    return rows


def get_task(user, task_id: str):
    rows = _visible(user, read_rows(task_path(), "任务表"))
    task = next((r for r in rows if r.get("任务编号") == task_id), None)
    if task is None:
        raise ValueError("任务不存在或无权查看。")
    replies = [r for r in read_rows(task_path(), "回复表")
               if r.get("任务编号") == task_id]
    replies.sort(key=lambda r: r.get("回复时间") or "")
    flags = {"can_reply": can_reply(user, task), "can_manage": can_manage(user)}
    return task, replies, flags


def reply_task(user, task_id: str, content: str, progress: str, need_coord: bool):
    rows = read_rows(task_path(), "任务表")
    task = next((r for r in rows if r.get("任务编号") == task_id), None)
    if task is None:
        raise ValueError("任务不存在或无权操作。")
    if not can_reply(user, task):
        raise PermissionError("权限隔离:只有任务指派部门和管理层可回复。")
    content = (content or "").strip()
    if not content:
        raise ValueError("回复内容不能为空。")
    if progress not in STATUSES:
        progress = "进行中"

    replies = read_rows(task_path(), "回复表")
    reply_id = f"HF-{datetime.now().strftime('%Y%m%d%H%M%S')}{len(replies) % 100:02d}"
    reply = {"回复编号": reply_id, "任务编号": task_id, "回复人": user["name"],
             "回复时间": _now(), "回复内容": content, "进度状态": progress,
             "申请协调": "是" if need_coord else "否"}
    replies.append(reply)
    write_rows(task_path(), "回复表", replies)

    task["状态"] = progress
    if need_coord:
        task["需协调资源"] = "是"
    write_rows(task_path(), "任务表", rows)
    append_log(user["username"], "回复任务", task_id)
    return task, reply


def set_status(user, task_id: str, status: str, resolve_coord: bool = False):
    if not can_manage(user):
        raise PermissionError("仅管理员/院领导可变更任务状态。")
    if status not in STATUSES:
        raise ValueError("状态不合法。")
    rows = read_rows(task_path(), "任务表")
    task = next((r for r in rows if r.get("任务编号") == task_id), None)
    if task is None:
        raise ValueError("任务不存在。")
    task["状态"] = status
    if status == "已完成" and not task.get("办结时间"):
        task["办结时间"] = _now()
    if resolve_coord:
        task["需协调资源"] = "否"
    write_rows(task_path(), "任务表", rows)
    append_log(user["username"], "变更任务状态", f"{task_id} -> {status}")
    return task


def month_task_days(user, year: int, month: int) -> dict:
    """日历任务标记:{日: {total: n, coord: n}},仅统计未办结任务。"""
    prefix = f"{year:04d}-{month:02d}"
    out = {}
    for r in _visible(user, read_rows(task_path(), "任务表")):
        due = r.get("截止日期") or ""
        if not due.startswith(prefix) or r.get("状态") == "已完成":
            continue
        day = int(due.split("-")[2])
        d = out.setdefault(day, {"total": 0, "coord": 0})
        d["total"] += 1
        if r.get("需协调资源") == "是":
            d["coord"] += 1
    return {str(k): v for k, v in out.items()}
