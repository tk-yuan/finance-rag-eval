"""财会准则语料清洗：HTML → 结构化文本 + 元数据。

## 数据长什么样

财政部会计司的页面是**统一模板**，549 份共用同一个骨架：

    <title>关于印发《企业会计准则第30号——财务报表列报》的通知</title>
    ...导航条：财政部微信 / 财政部视频号 / 官方抖音号 / 移动客户端下载...
    当前位置：首页 > 政策发布
    关于印发《企业会计准则第30号——财务报表列报》的通知   ← 正文标题
    2026年08月05日来源：会计司                            ← 真实发布日期
    正文……
    ...页脚 / 相关文章 / JS...

## 一个必须避开的坑

**日期会被抓错。** 导航条里有一句「2017年11月21日 星期二」——
那是页面渲染的时间戳，**和文章发布日期毫无关系**，
但它是页面里出现的第一个「YYYY年MM月DD日」。
直接取第一个匹配的话，几百篇的发布日期会全变成 2017-11-21。

所以：**先定位正文，再在正文里找日期**，并且显式排除「后面紧跟星期几」的那种。

## 抽什么元数据

| 字段 | 用途 |
|---|---|
| `title` | 准则名称，检索结果的展示标题 |
| `doc_no` | **文号**（如「财会〔2026〕12号」）——让每条结论可溯源 |
| `issued` | 发布日期——支持按时间过滤，问 2026 年的问题不该召回 2014 年的旧文 |
| `effective_from` | **施行日期**——准则常有过渡期，这是判断"现在适不适用"的依据 |
| `issuer` | 发文机关 |
| `column` | 栏目：政策发布 / 政策解读——原文与解读要能区分，检索时能测出模型会不会混 |

`effective_from` 尤其重要：准则里常见「本准则自 2027 年 1 月 1 日起施行」，
检索层如果识别不出，就会把**还没生效的准则**当成现行准则回答。
这是财务域里最容易出、后果也最严重的一类错误。
"""

from __future__ import annotations

import html as html_mod
import re
from pathlib import Path

CONTENT_START_MARK = "当前位置"

END_MARKS = ("相关文章", "附件下载", "扫一扫", "分享到", "责任编辑", "上一篇", "下一篇")

NAV_LINES = {
    "财政部微信", "财政部视频号", "财政部", "官方抖音号",
    "移动客户端Android下载", "移动客户端iphone下载",
    "移动客户端 Android下载", "移动客户端 iphone下载",
    "会计司", "搜索", "高级搜索-->", "高级搜索", "返回主站",
    "中华人民共和国财政部", "-->", "--&gt;", "{", "}",
}

# 文号有两种括号写法：正式公文的「〔〕」和网页上常见的「[]」，都要认
_BR = r"[〔\[【]\s*(\d{4})\s*[〕\]】]"
DOC_NO_PATTERNS = (
    r"财会\s*" + _BR + r"\s*(\d+)\s*号",
    r"财办会\s*" + _BR + r"\s*(\d+)\s*号",
    r"财库\s*" + _BR + r"\s*(\d+)\s*号",
    r"财关税\s*" + _BR + r"\s*(\d+)\s*号",
    r"财政部令第\s*\d+\s*号",
    r"财政部\s*" + _BR + r"\s*(\d+)\s*号",
    # 公告体：财政部公告2020年第47号、财政部 税务总局公告2026年第18号。
    # 联合发文的机关名可能有两三段，用「公告YYYY年第N号」这个固定骨架兜住。
    r"[一-龥]{2,10}(?:\s+[一-龥]{2,10}){0,3}\s*公告\s*\d{4}\s*年第\s*\d+\s*号",
    r"第\s*\d{4}\s*年第\s*\d+\s*号",
)

ORG_NAMES = ("财政部", "国务院", "中国证监会", "国家税务总局", "国资委")

_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_WEEKDAY_AFTER = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*星期")

_BLOCK_RE = re.compile(r"</?(?:p|div|br|tr|li|h[1-6]|table|tbody|section)\b[^>]*>", re.I)


def html_to_text(raw: str) -> str:
    """HTML → 纯文本。块级标签转换行，保住段落结构。"""
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw, flags=re.S | re.I)
    s = _BLOCK_RE.sub("\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s)
    s = s.replace("　", " ").replace("\xa0", " ")
    return "\n".join(ln.strip() for ln in s.split("\n") if ln.strip())


def split_body(text: str) -> list[str]:
    """切出正文行：跳过模板导航，遇页脚标记即停。"""
    lines = text.split("\n")

    start = 0
    for i, ln in enumerate(lines):
        if CONTENT_START_MARK in ln:
            start = i + 1

    body: list[str] = []
    for ln in lines[start:]:
        if any(ln.startswith(m) for m in END_MARKS):
            break
        if ln in NAV_LINES or ln.startswith(("首页", "当前位置")):
            continue
        body.append(ln)
    return body


def extract_meta(body: list[str], fallback_title: str) -> dict:
    text = "\n".join(body)
    head = body[:8]

    title = head[0] if head else fallback_title
    title = re.sub(r"^[《\s]+|[》\s]+$", "", title)

    doc_no = ""
    for ln in body[:15]:
        for pat in DOC_NO_PATTERNS:
            m = re.search(pat, ln)
            if m:
                doc_no = re.sub(r"\s+", "", m.group(0))
                break
        if doc_no:
            break

    issued = ""
    for ln in head:
        if _WEEKDAY_AFTER.search(ln):
            continue          # 模板渲染时间戳，不是发布日期
        m = _DATE_RE.search(ln)
        if m:
            issued = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            break

    issuer = ""
    for ln in body[1:12]:
        if len(ln) <= 40 and any(o in ln for o in ORG_NAMES):
            issuer = ln
            break
    if issuer:
        issuer = re.sub(r"[（(].*?[)）]", "", issuer)
        issuer = re.sub(r"财会\s*〔.*$|财政部令.*$|公告.*$", "", issuer)
        issuer = issuer.strip(" ，,。、：:")

    effective_from = ""
    m = re.search(r"自\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日起(?:施行|执行)", text)
    if m:
        effective_from = f"{m.group(1)}-{int(m.group(2)):02d}"

    # 执行截止日。和 effective_from 是两件事：一个问"什么时候开始适用"，
    # 一个问"还能用到什么时候"。政策到期后不能再作为依据，靠的就是这个字段。
    valid_to = ""
    m = (
        re.search(r"(?:执行至|有效期至|截止至|截止到)\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
        or re.search(r"自\s*\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日起至\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日止", text)
    )
    if m:
        valid_to = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    return {
        "title": title, "doc_no": doc_no, "issued": issued,
        "issuer": issuer, "effective_from": effective_from, "valid_to": valid_to,
    }


def clean_document(path: Path, column: str = "") -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    body = split_body(html_to_text(raw))
    meta = extract_meta(body, fallback_title=path.stem)
    content = "\n".join(body)
    return {
        "doc_id": path.stem, "source_file": path.name, "column": column,
        "raw_chars": len(raw), "text": content, "chars": len(content),
        "kept_ratio": round(len(content) / max(len(raw), 1), 3),
        **meta,
    }
