# -*- coding: utf-8 -*-
"""账号与权限:三办分权录入、领导只读、管理员管账号。"""
import json
import re
import secrets
from functools import wraps

from flask import jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from .storage import DATA_DIR, OFFICES, append_log

USERS_FILE = DATA_DIR / "users.json"
SECRET_FILE = DATA_DIR / "secret.key"

ROLES = ("admin", "leader", "office")
ROLE_LABELS = {"admin": "管理员", "leader": "院领导", "office": "部门负责人"}

DEFAULT_USERS = [
    {"username": "admin", "name": "系统管理员", "role": "admin", "office": "", "password": "Admin@123"},
    {"username": "leader", "name": "院领导", "role": "leader", "office": "", "password": "Leader@123"},
    {"username": "zhb", "name": "综合办负责人", "role": "office", "office": "综合办", "password": "Zhb@123456"},
    {"username": "jxb", "name": "教学办负责人", "role": "office", "office": "教学办", "password": "Jxb@123456"},
    {"username": "xsb", "name": "学生办负责人", "role": "office", "office": "学生办", "password": "Xsb@123456"},
]


def get_secret_key() -> str:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(key, encoding="utf-8")
    return key


def init_users():
    if USERS_FILE.exists():
        return
    users = []
    for u in DEFAULT_USERS:
        users.append({"username": u["username"], "name": u["name"], "role": u["role"],
                      "office": u["office"], "active": True,
                      "password_hash": generate_password_hash(u["password"])})
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _load_users() -> list:
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_users(users: list):
    tmp = USERS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    tmp.replace(USERS_FILE)


def verify(username: str, password: str):
    if not username or not password:
        return None
    for u in _load_users():
        if u["username"] == username and u.get("active", True) \
                and check_password_hash(u["password_hash"], password):
            return {"username": u["username"], "name": u["name"],
                    "role": u["role"], "office": u.get("office", "")}
    return None


def list_users() -> list:
    out = []
    for u in _load_users():
        out.append({"username": u["username"], "name": u["name"], "role": u["role"],
                    "office": u.get("office", ""), "active": u.get("active", True)})
    return out


def add_user(username: str, name: str, role: str, office: str, password: str):
    if not re.fullmatch(r"[A-Za-z0-9_]{2,20}", username or ""):
        raise ValueError("用户名须为 2-20 位字母、数字或下划线。")
    if role not in ROLES:
        raise ValueError("角色不合法。")
    if role == "office" and office not in OFFICES:
        raise ValueError("部门负责人账号必须指定所属部门。")
    if not name or not name.strip():
        raise ValueError("姓名不能为空。")
    if not password or len(password) < 6:
        raise ValueError("密码至少 6 位。")
    users = _load_users()
    if any(u["username"] == username for u in users):
        raise ValueError("该用户名已存在。")
    users.append({"username": username, "name": name.strip(), "role": role,
                  "office": office if role == "office" else "",
                  "active": True, "password_hash": generate_password_hash(password)})
    _save_users(users)
    append_log("admin", "新增账号", username)


def reset_password(username: str, new_password: str):
    if not new_password or len(new_password) < 6:
        raise ValueError("密码至少 6 位。")
    users = _load_users()
    for u in users:
        if u["username"] == username:
            u["password_hash"] = generate_password_hash(new_password)
            _save_users(users)
            append_log("admin", "重置密码", username)
            return
    raise ValueError("用户不存在。")


def toggle_user(username: str):
    users = _load_users()
    for u in users:
        if u["username"] == username:
            u["active"] = not u.get("active", True)
            _save_users(users)
            append_log("admin", "停用/启用账号", f"{username} -> {u['active']}")
            return
    raise ValueError("用户不存在。")


def current_user():
    return session.get("user")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"ok": False, "error": "未登录或会话已过期。"}), 401
        return fn(*args, **kwargs)
    return wrapper
