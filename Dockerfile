# 把整条评测流水线打包进镜像。
#
# 本项目不是常驻服务，所以这个镜像的用法是"进去跑脚本"：
#   docker build -t finance-rag-eval .
#   docker run --rm --env-file .env -v "$PWD/reports:/app/reports" finance-rag-eval
#
# 好处是别人不用装 Python 和一堆依赖就能复现评测——
# 评测这东西，跑不起来就等于没有。
FROM python:3.13-slim

# numpy 的 wheel 不自带 BLAS，运行时链接系统 libblas/liblapack/libgfortran，
# python:slim 基础镜像不保证有 → 缺了 `import numpy` 直接失败。
# 注意 01 清洗不 import numpy，所以只跑清洗的冒烟用例看不出这个问题；
# 但默认 CMD 里的建索引 / 跑消融都要用，必须在镜像里补上这几个库。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libblas3 liblapack3 libgfortran5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

LABEL org.opencontainers.image.title="finance-rag-eval" \
      org.opencontainers.image.description="财会准则 RAG 检索质量与评测系统" \
      org.opencontainers.image.source="https://github.com/tk-yuan/finance-rag-eval"

# 默认把「清洗 → 建索引 → 建评测集 → 跑消融」整条跑一遍。
# 需要单独跑某一步就覆盖 CMD，例如：
#   docker run --rm --env-file .env finance-rag-eval python scripts/05_ask.py "问题"
CMD ["sh", "-c", "python scripts/01_clean_corpus.py && python scripts/02_build_index.py && python scripts/03_build_evalset.py 180 && python scripts/04_run_ablation.py"]
