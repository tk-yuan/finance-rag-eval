"""00 抓取财政部会计司的政策文件 —— 语料采集

用法：
    python scripts/00_crawl_corpus.py              # 全量抓（约 700 份，10-20 分钟）
    python scripts/00_crawl_corpus.py 3            # 只抓前 3 页（试跑）

## 为什么从财政部官网抓

这是**权威来源**：企业会计准则、准则解释、管理会计应用指引、会计制度
都由财政部会计司发布，这里的文本就是准则本身，不是二手转述。
做检索评测最怕语料来源不干净——用官网原文，每个结论都能溯源。

## 抓什么

| 栏目 | 内容 | 用途 |
|---|---|---|
| 政策发布 | 准则原文、解释、制度 | **主语料** |
| 政策解读 | 官方解读、答记者问 | 补充：同一问题常有"原文 + 解读"两个版本，正好用来测检索能不能分清 |

## 两个工程细节

1. **可断点续跑**：已经下过的文件跳过，中断了重跑不用从头来。
2. **限速**：每次请求间隔 0.6 秒。官网是公共资源，抓崩了不体面，
   而且容易被封——尊重对方服务器是基本要求。
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw_docs"
INDEX_LOG = ROOT / "data" / "crawl_index.jsonl"

BASE = "https://kjs.mof.gov.cn"
COLUMNS = {
    "zhengcefabu": "政策发布",
    "zhengcejiedu": "政策解读",
}
DELAY = 0.6
TIMEOUT = 30.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# 详情页形如 ./202608/t20260805_3994927.htm
DETAIL_RE = re.compile(r'href=["\']\.?/?(\d{6}/t\d{8}_\d+\.htm)["\']')
# 翻页控件 createPageHTML(37, 0, "index", "htm")
PAGES_RE = re.compile(r"createPageHTML\(\s*(\d+)")


def _get(client: httpx.Client, url: str, retries: int = 3) -> str | None:
    for i in range(retries):
        try:
            r = client.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r.text
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.5 ** i)
    return None


def list_column(client: httpx.Client, col: str, max_pages: int | None) -> list[str]:
    """列出某栏目下所有详情页的相对路径。"""
    first = _get(client, f"{BASE}/{col}/")
    if not first:
        print(f"  [{col}] 列表页打不开，跳过")
        return []

    m = PAGES_RE.search(first)
    total = int(m.group(1)) if m else 1
    if max_pages:
        total = min(total, max_pages)
    print(f"  [{COLUMNS.get(col, col)}] 共 {total} 页")

    found: list[str] = []
    for p in range(total):
        url = f"{BASE}/{col}/" if p == 0 else f"{BASE}/{col}/index_{p}.htm"
        html = _get(client, url)
        if not html:
            continue
        found.extend(DETAIL_RE.findall(html))
        if p % 5 == 0:
            print(f"    第 {p + 1}/{total} 页，累计 {len(found)} 条")
        time.sleep(DELAY)

    return sorted(set(found))


def fetch_detail(client: httpx.Client, rel: str, col: str) -> dict | None:
    url = f"{BASE}/{col}/{rel}"
    html = _get(client, url)
    if not html:
        return None

    title = ""
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()

    date = ""
    m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", html)
    if m:
        date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 存原始 HTML：清洗是下一步的事，先把原始证据留全
    return {"url": url, "title": title, "date": date, "column": col, "html": html}


def main() -> None:
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    if INDEX_LOG.exists():
        import json

        for line in INDEX_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["url"])
        print(f"已有 {len(done)} 份，本次跳过这些（断点续跑）\n")

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        rels: list[tuple[str, str]] = []
        for col in COLUMNS:
            for rel in list_column(client, col, max_pages):
                rels.append((col, rel))
        print(f"\n待抓取 {len(rels)} 份\n")

        ok = skip = fail = 0
        for i, (col, rel) in enumerate(rels, 1):
            url = f"{BASE}/{col}/{rel}"
            if url in done:
                skip += 1
                continue
            rec = fetch_detail(client, rel, col)
            if rec is None:
                fail += 1
                continue

            slug = re.sub(r"[^\w\-]", "_", rel.replace("/", "_"))
            (RAW_DIR / f"{slug}.html").write_text(rec["html"], encoding="utf-8")
            with INDEX_LOG.open("a", encoding="utf-8") as f:
                import json

                f.write(json.dumps(
                    {k: v for k, v in rec.items() if k != "html"}, ensure_ascii=False
                ) + "\n")
            ok += 1

            if i % 25 == 0:
                print(f"  {i}/{len(rels)}  成功 {ok} 跳过 {skip} 失败 {fail}")
            time.sleep(DELAY)

    print(f"\n完成：新增 {ok} 份，跳过 {skip} 份，失败 {fail} 份")
    print(f"原始文件 → {RAW_DIR}")


if __name__ == "__main__":
    main()
