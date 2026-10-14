"""01 清洗财会准则语料 → data/processed/corpus.jsonl

用法：
    python scripts/01_clean_corpus.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from finrag.config import CORPUS_JSONL, RAW_DIR  # noqa: E402
from finrag.corpus.clean import clean_document  # noqa: E402


def load_columns() -> dict[str, str]:
    """从抓取索引里取每份文件的栏目（原始文件名 → 栏目）。"""
    idx = ROOT / "data" / "crawl_index.jsonl"
    if not idx.exists():
        return {}
    out: dict[str, str] = {}
    for line in idx.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        # 抓取时文件名由 rel 路径生成：202608_t20260805_3994927.htm → 202608_t20260805_3994927_html
        stem = r["url"].rstrip("/").split("/")
        key = "_".join(stem[-2:]).replace(".", "_")
        out[key] = r.get("column", "")
    return out


def main() -> None:
    files = sorted(RAW_DIR.glob("*.html"))
    if not files:
        raise SystemExit(f"未找到原始语料：{RAW_DIR}，请先运行 00_crawl_corpus.py")

    cols = load_columns()
    records = []
    for p in files:
        col = cols.get(p.stem, "")
        records.append(clean_document(p, column=col))

    CORPUS_JSONL.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8"
    )

    n = len(records)
    print(f"清洗完成：{n} 份 -> {CORPUS_JSONL}")
    print(
        f"  文号 {sum(1 for r in records if r['doc_no'])}/{n}"
        f" | 发布日期 {sum(1 for r in records if r['issued'])}/{n}"
        f" | 施行日期 {sum(1 for r in records if r['effective_from'])}/{n}"
    )
    avg_keep = sum(r["kept_ratio"] for r in records) / n
    avg_chars = sum(r["chars"] for r in records) / n
    print(f"  平均正文 {avg_chars:.0f} 字 | 平均去噪 {1 - avg_keep:.1%}")
    years = Counter((r["issued"] or "????")[:4] for r in records)
    print("  按年份:", dict(sorted(years.items(), key=lambda kv: -kv[1])[:6]))

    print("\n样例：")
    for r in records[:3]:
        print(f"  · {r['title'][:52]}")
        print(f"    文号 {r['doc_no'] or '—'} | 发布 {r['issued'] or '—'}"
              f" | 施行 {r['effective_from'] or '—'} | 栏目 {r['column'] or '—'}")


if __name__ == "__main__":
    main()
