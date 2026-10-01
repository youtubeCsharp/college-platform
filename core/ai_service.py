# -*- coding: utf-8 -*-
"""AI 智能引擎:智谱 GLM-4-Flash(免费档)。

- 只读取文字台账,附件一律不参与;
- 生成前在代码层剔除"敏感事项=是"的条目,并做敏感词兜底扫描;
- 断网/未配密钥/接口异常均给出友好中文提示,核心台账功能不受影响;
- 模型名、接口地址、密钥全部在 config.json 中配置,可一键切换。
"""
import json

import requests

from .config import BASE_DIR, load_config
from .ledger import visible_offices
from .storage import ledger_path, read_rows

CONFIG_FILE = BASE_DIR / "config.json"

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-4-flash"


class AiError(Exception):
    """带友好中文提示的 AI 调用异常。"""


DAILY_SYSTEM = ("你是高校二级学院党政办公室的资深文字秘书,负责撰写学院官方工作简讯和新闻通讯稿。"
                "写作要求:语体庄重规范,符合高校党政机关公文与新闻通稿风格;严格基于所给台账事实撰写,"
                "不虚构、不夸大;表述简练凝练,多用动宾结构,恰当使用'扎实推进''有序开展''圆满完成'"
                "等规范表述;标题居中,正文分段,篇幅300-500字。")

MONTHLY_SYSTEM = ("你是高校二级学院党政办公室的资深文字秘书,负责起草学院月度工作总结。"
                  "写作要求:符合党政机关工作总结体例;结构清晰、层次分明;同类事项合并提炼,"
                  "剔除琐碎日常记录;严格基于所给台账事实,不虚构数据;语言规范凝练,"
                  "多用'完成''开展''组织'等动词开头的要点句式。")


def can_use_ai(user, cfg: dict) -> bool:
    allowed_offices = cfg.get("security", {}).get("ai_allowed_offices", [])
    if user["role"] in ("admin", "leader"):
        return True
    return user["role"] == "office" and user.get("office") in allowed_offices


def _is_sensitive(row: dict, keywords) -> bool:
    if (row.get("敏感事项") or "").strip() == "是":
        return True
    text = " ".join([row.get("工作内容", ""), row.get("备注", ""), row.get("参与人员", "")])
    return any(kw and kw in text for kw in keywords)


def collect_clean_data(user, date=None, year=None, month=None, keywords=()):
    """按权限收集台账文字;剔除作废与敏感条目。返回 (data, removed)。"""
    prefix = f"{year:04d}-{month:02d}" if year and month else None
    data, removed = {}, []
    for office in visible_offices(user):
        picked = []
        for r in read_rows(ledger_path(office), "台账"):
            if r.get("状态") != "正常":
                continue
            if date and r.get("日期") != date:
                continue
            if prefix and not (r.get("日期") or "").startswith(prefix):
                continue
            picked.append(r)
        clean, dropped = [], []
        for r in picked:
            (dropped if _is_sensitive(r, keywords) else clean).append(r)
        data[office] = clean
        for r in dropped:
            reason = "已标记敏感事项" if (r.get("敏感事项") or "").strip() == "是" else "命中敏感词"
            removed.append({"部门": office, "编号": r.get("编号", ""), "原因": reason})
    return data, removed


def _format_office(name: str, rows: list, with_date: bool = False) -> str:
    if not rows:
        return f"【{name}】(无工作记录)"
    lines = []
    for r in rows:
        line = f"- {r.get('工作大类', '')}:{r.get('工作内容', '')}(完成情况:{r.get('完成情况', '')}"
        if with_date and r.get("日期"):
            line += f";日期:{r['日期']}"
        if r.get("参与人员"):
            line += f";参与:{r['参与人员']}"
        line += ")"
        lines.append(line)
    return f"【{name}】\n" + "\n".join(lines)


def generate(kind: str, user, date=None, year=None, month=None) -> dict:
    cfg = load_config()
    ai = cfg.get("ai", {})
    if not (ai.get("api_key") or "").strip():
        raise AiError("尚未配置智谱 AI 的 API Key。请在平台目录下的 config.json 中"
                      "填写 ai.api_key(在智谱开放平台 bigmodel.cn 免费申请),保存后重启平台。")
    keywords = cfg.get("security", {}).get("sensitive_keywords", [])
    data, removed = collect_clean_data(user, date=date, year=year, month=month,
                                       keywords=keywords)
    total = sum(len(v) for v in data.values())
    if total == 0:
        raise AiError("所选时间段内没有可用的非敏感台账记录,无法生成。")

    if kind == "daily":
        body = "\n\n".join(_format_office(o, data[o]) for o in data)
        system = DAILY_SYSTEM
        user_prompt = (f"请根据以下 {date} 学院三部门工作台账,撰写一篇学院当日工作简讯(新闻通讯稿)。"
                       f"要求:1.自拟规范标题;2.正文300-500字,按工作重要程度组织;3.结尾可加一句"
                       f"'下一步'工作方向;4.直接输出简讯正文,不要任何解释。\n\n各部门台账如下:\n\n{body}")
    else:
        body = "\n\n".join(_format_office(o, data[o], with_date=True) for o in data)
        system = MONTHLY_SYSTEM
        user_prompt = (f"请根据以下 {year:04d}年{month:02d}月 各部门工作台账,撰写学院月度工作总结初稿。"
                       f"要求:1.按'一、综合办工作''二、教学办工作''三、学生办工作'三个板块组织;"
                       f"2.每个板块内合并同类工作、提炼要点,剔除琐碎记录;3.结尾增加'四、下月工作打算',"
                       f"列2至3条建议;4.直接输出总结正文,不要任何解释。\n\n台账如下:\n\n{body}")

    payload = {"model": ai.get("model", DEFAULT_MODEL),
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user_prompt}],
               "temperature": 0.3}
    headers = {"Authorization": f"Bearer {ai['api_key'].strip()}",
               "Content-Type": "application/json"}
    try:
        resp = requests.post(ai.get("base_url", DEFAULT_BASE_URL), json=payload,
                             headers=headers, timeout=int(ai.get("timeout_seconds", 60)))
    except requests.exceptions.ConnectionError:
        raise AiError("网络连接失败:AI 生成需要临时联网,请检查本机网络后重试。"
                      "台账录入等其余功能不受影响。")
    except requests.exceptions.Timeout:
        raise AiError("AI 接口请求超时,请稍后重试。")

    if resp.status_code != 200:
        detail = resp.text[:200]
        if resp.status_code == 401:
            raise AiError("AI 接口鉴权失败(401):请检查 config.json 中的 api_key 是否正确。")
        raise AiError(f"AI 接口返回错误(HTTP {resp.status_code}):{detail}")
    try:
        text = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        raise AiError("AI 接口返回格式异常,请稍后重试。")
    return {"text": text, "filtered": removed, "used": total}
