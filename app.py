# -*- coding: utf-8 -*-
"""数字经济与管理学院综合管理平台 - 后端服务(内网单机部署)。"""
import re
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_from_directory, session)
from waitress import serve
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash

from core import ai_service, auth, ledger, tasks
from core.ai_service import AiError
from core.config import load_config
from core.storage import (FILES_DIR, BusyFileError, append_log, init_storage,
                          ledger_path, read_rows)

CONFIG = load_config()

app = Flask(__name__)
app.secret_key = auth.get_secret_key()
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 单个附件最大 50MB

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".pdf",
               ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
               ".txt", ".zip", ".rar", ".7z", ".mp4", ".mov"}


def g():
    return session["user"]


def ok(payload=None, **extra):
    data = {"ok": True}
    if payload:
        data.update(payload)
    data.update(extra)
    return jsonify(data)


def fail(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


@app.errorhandler(BusyFileError)
def handle_busy(e):
    return fail(str(e), 409)


@app.errorhandler(PermissionError)
def handle_perm(e):
    return fail(str(e) or "权限不足。", 403)


@app.errorhandler(ValueError)
def handle_value(e):
    return fail(str(e))


@app.errorhandler(AiError)
def handle_ai(e):
    return fail(str(e), 503)


@app.errorhandler(HTTPException)
def handle_http(e):
    return fail(e.description, e.code)


@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.exception(e)
    return fail("服务异常,请稍后重试;若持续出现请查看 server 日志。", 500)


# ---------- 页面 ----------

@app.get("/")
def index():
    if not session.get("user"):
        return redirect("/login")
    return render_template("index.html")


@app.get("/login")
def login_page():
    if session.get("user"):
        return redirect("/")
    return render_template("login.html")


# ---------- 登录 ----------

@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    user = auth.verify((data.get("username") or "").strip(), data.get("password") or "")
    if not user:
        return fail("用户名或密码错误,或账号已停用。", 401)
    session["user"] = user
    append_log(user["username"], "登录")
    return ok({"user": user})


@app.post("/api/logout")
def api_logout():
    session.pop("user", None)
    return ok()


@app.get("/api/me")
def api_me():
    user = session.get("user")
    if not user:
        return fail("未登录。", 401)
    return ok({"user": user})


@app.get("/api/meta")
@auth.login_required
def api_meta():
    u = g()
    return ok({
        "user": u,
        "offices_visible": ledger.visible_offices(u),
        "categories": ledger.CATEGORIES,
        "completion": ledger.COMPLETION_OPTIONS,
        "can_publish": tasks.can_publish(u),
        "is_admin": u["role"] == "admin",
        "is_leader": u["role"] in ("admin", "leader"),
        "can_ai": ai_service.can_use_ai(u, CONFIG),
        "today": datetime.now().strftime("%Y-%m-%d"),
    })


# ---------- 日历与台账 ----------

@app.get("/api/calendar")
@auth.login_required
def api_calendar():
    u = g()
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    if not (1 <= month <= 12):
        return fail("月份不正确。")
    return ok({"year": year, "month": month,
               "days": ledger.month_counts(u, year, month),
               "task_days": tasks.month_task_days(u, year, month),
               "today": now.strftime("%Y-%m-%d")})


@app.get("/api/ledger/day")
@auth.login_required
def api_ledger_day():
    date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    return ok({"date": date, "entries": ledger.get_day(g(), date)})


@app.post("/api/ledger/add")
@auth.login_required
def api_ledger_add():
    data = request.get_json(silent=True) or {}
    row = ledger.add_entry(g(), data.get("office") or "", data)
    return ok({"entry": row})


@app.post("/api/ledger/update")
@auth.login_required
def api_ledger_update():
    data = request.get_json(silent=True) or {}
    row = ledger.update_entry(g(), data.get("office") or "",
                              data.get("entry_id") or "", data)
    return ok({"entry": row})


@app.post("/api/ledger/void")
@auth.login_required
def api_ledger_void():
    data = request.get_json(silent=True) or {}
    row = ledger.void_entry(g(), data.get("office") or "", data.get("entry_id") or "")
    return ok({"entry": row})


# ---------- 附件(浏览器上传归档,网页下载链接) ----------

def _sanitize_name(name: str) -> str:
    name = re.sub(r"\s+", "_", name or "附件")
    return re.sub(r"[^\w.\-\u4e00-\u9fa5]", "_", name)


@app.post("/api/upload")
@auth.login_required
def api_upload():
    u = g()
    if u["role"] != "office":
        return fail("仅三办账号可上传附件。", 403)
    f = request.files.get("file")
    if f is None or not f.filename:
        return fail("未收到文件。")
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return fail(f"不支持的文件类型:{ext}")
    date = request.form.get("date") or datetime.now().strftime("%Y-%m-%d")
    folder_name = f"{date[:7]}-{u['office']}"  # 例:2026-10-综合办
    target = FILES_DIR / folder_name
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H%M%S")
    final_name = f"{stamp}_{_sanitize_name(Path(f.filename).stem)}{ext}"
    f.save(target / final_name)
    rel = f"{folder_name}/{final_name}"
    append_log(u["username"], "上传附件", rel)
    return ok({"path": rel, "name": f.filename})


@app.get("/files/<path:subpath>")
@auth.login_required
def files(subpath):
    parts = subpath.split("/")
    if len(parts) < 2:
        abort(404)
    seg = parts[0].split("-", 2)  # "2026-10-综合办" -> ["2026","10","综合办"]
    dept = seg[2] if len(seg) == 3 else ""
    u = g()
    if u["role"] == "office" and dept != u["office"]:
        abort(403)
    return send_from_directory(FILES_DIR, subpath)


# ---------- 工作安排 ----------

@app.get("/api/tasks")
@auth.login_required
def api_tasks():
    u = g()
    rows = tasks.list_tasks(u,
                            status=request.args.get("status") or "",
                            dept=request.args.get("dept") or "",
                            coord=request.args.get("coord") == "1",
                            due=request.args.get("due") or "")
    return ok({"tasks": rows})


@app.get("/api/tasks/<task_id>")
@auth.login_required
def api_task_detail(task_id):
    task, replies, flags = tasks.get_task(g(), task_id)
    return ok({"task": task, "replies": replies, "flags": flags})


@app.post("/api/tasks")
@auth.login_required
def api_task_create():
    data = request.get_json(silent=True) or {}
    row = tasks.create_task(g(), data)
    return ok({"task": row})


@app.post("/api/tasks/<task_id>/reply")
@auth.login_required
def api_task_reply(task_id):
    data = request.get_json(silent=True) or {}
    task, reply = tasks.reply_task(g(), task_id, data.get("content") or "",
                                   data.get("progress") or "",
                                   bool(data.get("need_coord")))
    return ok({"task": task, "reply": reply})


@app.post("/api/tasks/<task_id>/status")
@auth.login_required
def api_task_status(task_id):
    data = request.get_json(silent=True) or {}
    row = tasks.set_status(g(), task_id, data.get("status") or "",
                           bool(data.get("resolve_coord")))
    return ok({"task": row})


# ---------- AI 智能生成 ----------

@app.post("/api/ai/daily")
@auth.login_required
def api_ai_daily():
    u = g()
    if not ai_service.can_use_ai(u, CONFIG):
        return fail("当前账号无 AI 生成权限(仅管理员、院领导及综合办)。", 403)
    data = request.get_json(silent=True) or {}
    date = data.get("date") or datetime.now().strftime("%Y-%m-%d")
    result = ai_service.generate("daily", u, date=date)
    append_log(u["username"], "AI生成当日简讯", date)
    return ok(result)


@app.post("/api/ai/month")
@auth.login_required
def api_ai_month():
    u = g()
    if not ai_service.can_use_ai(u, CONFIG):
        return fail("当前账号无 AI 生成权限(仅管理员、院领导及综合办)。", 403)
    data = request.get_json(silent=True) or {}
    now = datetime.now()
    year = int(data.get("year") or now.year)
    month = int(data.get("month") or now.month)
    result = ai_service.generate("monthly", u, year=year, month=month)
    append_log(u["username"], "AI生成月度总结", f"{year}-{month:02d}")
    return ok(result)


# ---------- 系统管理(仅管理员) ----------

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = session.get("user")
        if not u:
            return fail("未登录。", 401)
        if u["role"] != "admin":
            return fail("仅管理员可操作。", 403)
        return fn(*args, **kwargs)
    return wrapper


@app.get("/api/users")
@admin_required
def api_users():
    return ok({"users": auth.list_users()})


@app.post("/api/users/add")
@admin_required
def api_users_add():
    data = request.get_json(silent=True) or {}
    auth.add_user(data.get("username") or "", data.get("name") or "",
                  data.get("role") or "", data.get("office") or "",
                  data.get("password") or "")
    return ok()


@app.post("/api/users/reset")
@admin_required
def api_users_reset():
    data = request.get_json(silent=True) or {}
    auth.reset_password(data.get("username") or "", data.get("password") or "")
    return ok()


@app.post("/api/users/toggle")
@admin_required
def api_users_toggle():
    data = request.get_json(silent=True) or {}
    auth.toggle_user(data.get("username") or "")
    return ok()


def main():
    init_storage()
    auth.init_users()
    host = CONFIG["server"].get("host", "0.0.0.0")
    port = int(CONFIG["server"].get("port", 8000))
    print(f"* 数字经济与管理学院综合管理平台已启动")
    print(f"* 本机访问: http://127.0.0.1:{port}")
    print(f"* 手机(同一校园网/Wi-Fi)访问: http://<本机IP>:{port}")
    serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()
