"""
投资大师 PDF/HTML -&gt; 纯文本数据清洗脚本

分类逻辑：
  - >5MB PDF  -&gt; 直接标记为扫描件（段永平书籍），走 MinerU API
  - <=5MB PDF -&gt; PyMuPDF 先提取，文字量 < 200 字回退 MinerU
  - HTML      -&gt; BeautifulSoup 提取正文

MinerU 通过 mineru.net API 调用，需要设置环境变量 MINERU_TOKEN。
输出目录：资源搜索/data/investment_masters_parsed/{master_name}/{filename}.md
"""
import os
import sys
import hashlib
import io
from pathlib import Path

# Windows 下强制 stdout/stderr 使用 UTF-8，避免 MinerU API 的 emoji 编码报错
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 将 MinerU skill 脚本目录加入 sys.path，以便 import
MINERU_SCRIPTS = Path(os.path.expanduser("~")) / ".claude" / "skills" / "mineru" / "scripts"
if str(MINERU_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MINERU_SCRIPTS))

# ── 配置 ──
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "资源搜索" / "data" / "investment_masters"
OUTPUT_DIR = BASE_DIR / "资源搜索" / "data" / "investment_masters_parsed"

SCAN_SIZE_THRESHOLD = 5 * 1024 * 1024   # 5MB，超过则认为扫描件
MIN_TEXT_LENGTH = 200                    # PyMuPDF 提取短于此值则回退 MinerU


def classify_files():
    """
    遍历 DATA_DIR，分类所有文件。

    返回: {master_name: [(file_path, file_type)]}
      file_type: 'text' | 'scan' | 'html'
    """
    result = {}
    for master_dir in sorted(DATA_DIR.iterdir()):
        if not master_dir.is_dir():
            continue
        master_name = master_dir.name
        files = []

        # 使用 rglob 递归搜索子目录（部分 PDF 在子文件夹中）
        for f in sorted(master_dir.rglob("*")):
            if not f.is_file():
                continue
            suffix = f.suffix.lower()
            # 跳过隐藏文件（.hash 等）、系统文件
            if f.name.startswith(".") or f.name.startswith("~"):
                continue

            if suffix == ".pdf":
                if f.stat().st_size > SCAN_SIZE_THRESHOLD:
                    files.append((f, "scan"))
                else:
                    files.append((f, "text"))
            elif suffix in (".html", ".htm"):
                files.append((f, "html"))

        if files:
            result[master_name] = files

    return result


# ── 解析器 ──

def get_output_name(master_dir: Path, file_path: Path) -> str:
    """
    生成唯一的输出文件名。

    若文件在子目录中，用相对路径（把 / 替换为 __）避免同名冲突。
    例如: "段永平传 -- 孙力科/段永平传 -- 孙力科.pdf" -> "段永平传 -- 孙力科__段永平传 -- 孙力科"
    """
    rel = file_path.relative_to(master_dir)
    if rel.parent != Path("."):
        # 文件在子目录中，拼接父目录名和文件名
        return str(rel.parent / rel.stem).replace("/", "__").replace("\\", "__")
    return file_path.stem


def parse_text_pdf(file_path: Path) -> str:
    """
    用 PyMuPDF 提取 PDF 文本层。
    若文本量不足 MIN_TEXT_LENGTH，抛出 ValueError，由上层回退 MinerU。
    """
    import fitz  # PyMuPDF — import 名是 fitz，不是 pymupdf

    doc = fitz.open(str(file_path))
    pages_text = []
    for page in doc:                # doc 可迭代，每次 yield 一页
        text = page.get_text()      # 提取当前页全部文本
        if text.strip():
            pages_text.append(text)
    doc.close()

    full_text = "\n\n".join(pages_text)
    if len(full_text.strip()) < MIN_TEXT_LENGTH:
        raise ValueError(f"文字量不足 ({len(full_text)} 字符)")
    return full_text


def parse_html(file_path: Path) -> str:
    """用 BeautifulSoup 提取 HTML 正文。"""
    from bs4 import BeautifulSoup
    import re

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "img"]):
        tag.decompose()

    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_scans_with_mineru(file_paths: list[Path], output_dir: Path, master_name: str) -> dict:
    """
    调用 MinerU API 批量解析扫描件 PDF。

    mineru_api.py 的 parse_local_files() 流程：
      1. 上传 PDF 到 mineru.net
      2. 轮询等待 VLM 解析完成
      3. 下载结果 ZIP，解压后含 full.md

    Returns: {file_stem: markdown_text}
    """
    from mineru_api import parse_local_files

    token = os.environ.get("MINERU_TOKEN")
    if not token:
        raise RuntimeError("未设置 MINERU_TOKEN 环境变量，无法调用 MinerU API")

    print(f"  上传 {len(file_paths)} 个文件到 MinerU，等待 VLM 解析...")
    print(f"  (扫描件较大，可能需要 10-30 分钟)")

    # MinerU API 输出到一个临时目录
    mineru_out = output_dir / "_mineru_raw"
    mineru_out.mkdir(parents=True, exist_ok=True)

    results = parse_local_files(
        token=token,
        file_paths=[str(p) for p in file_paths],
        output_dir=mineru_out,
        model_version="vlm",
        is_ocr=True,                # 启用 OCR，扫描件必须
        enable_formula=True,
        enable_table=True,
        timeout=1800,               # 单个文件最长等 30 分钟
        poll_interval=10,
        verbose=True,
    )

    # 从 MinerU 输出中提取 md 文本
    texts = {}
    for extract_dir in results:     # extract_dir 是 Path 对象，指向解压目录
        # 找 extract_dir 下的 .md 文件（可能是 full.md 或 {filename}.md）
        md_files = list(extract_dir.glob("*.md"))
        if md_files:
            text = md_files[0].read_text(encoding="utf-8")
            stem = extract_dir.name
            texts[stem] = text
        else:
            print(f"  [WARN] {extract_dir.name} 未生成 .md 文件")

    return texts


def get_file_hash(file_path: Path) -> str:
    """计算文件 MD5，用于增量处理判断。"""
    return hashlib.md5(file_path.read_bytes()).hexdigest()


# ── 主流程 ──

def main():
    files_by_master = classify_files()

    # 汇总
    total_text = sum(1 for files in files_by_master.values() for _, t in files if t == "text")
    total_scan = sum(1 for files in files_by_master.values() for _, t in files if t == "scan")
    total_html = sum(1 for files in files_by_master.values() for _, t in files if t == "html")
    print(f"分类结果: {total_text} 文本型 PDF, {total_scan} 扫描件, {total_html} HTML\n")

    for master_name, files in files_by_master.items():
        print(f"{'='*60}")
        print(f"  {master_name} ({len(files)} 文件)")
        print(f"{'='*60}")

        master_out = OUTPUT_DIR / master_name
        master_out.mkdir(parents=True, exist_ok=True)

        # 先处理 text + html，最后批量处理 scan
        text_files = [(f, t) for f, t in files if t in ("text", "html")]
        scan_files = [f for f, t in files if t == "scan"]

        # 获取 master 根目录（用于计算相对路径）
        master_root = DATA_DIR / master_name

        # ── 文本型 PDF + HTML ──
        for file_path, ftype in text_files:
            out_name = get_output_name(master_root, file_path)
            out_path = master_out / (out_name + ".md")
            file_hash = get_file_hash(file_path)
            hash_file = master_out / f".{out_name}.hash"

            # 增量跳过
            if out_path.exists() and hash_file.exists():
                if hash_file.read_text().strip() == file_hash:
                    print(f"  [SKIP] {file_path.name} (已解析)")
                    continue

            print(f"  [{ftype.upper()}] {file_path.name} ({file_path.stat().st_size / 1024:.0f} KB)")

            try:
                if ftype == "html":
                    text = parse_html(file_path)
                    print(f"    -&gt; BS4 提取 ({len(text)} 字符)")
                else:
                    try:
                        text = parse_text_pdf(file_path)
                        print(f"    -&gt; PyMuPDF 提取 ({len(text)} 字符)")
                    except ValueError as e:
                        # 回退 MinerU，单独处理
                        print(f"    -> {e}，回退 MinerU...")
                        results = parse_scans_with_mineru([file_path], master_out, master_name)
                        text = results.get(file_path.stem, "")
                        print(f"    -&gt; MinerU 提取 ({len(text)} 字符)")

                if text.strip():
                    out_path.write_text(text, encoding="utf-8")
                    hash_file.write_text(file_hash, encoding="utf-8")
                    print(f"    [OK] 已保存: {out_path.name}")
                else:
                    print(f"    [FAIL] 空文本，跳过")

            except Exception as e:
                print(f"    [FAIL] 失败: {e}")
                continue

        # ── 扫描件 PDF（批量走 MinerU）──
        if scan_files:
            print(f"\n  ── 扫描件：批量 MinerU VLM 解析 ({len(scan_files)} 文件) ──")
            # 过滤已处理过的
            to_process = []
            for fp in scan_files:
                out_name = get_output_name(master_root, fp)
                out_path = master_out / (out_name + ".md")
                file_hash = get_file_hash(fp)
                hash_file = master_out / f".{out_name}.hash"
                if out_path.exists() and hash_file.exists() and hash_file.read_text().strip() == file_hash:
                    print(f"  [SKIP] {fp.name} (已解析)")
                else:
                    to_process.append(fp)

            if not to_process:
                print(f"  全部已解析，跳过 MinerU")
                continue

            for fp in to_process:
                print(f"  [SCAN] {fp.name} ({fp.stat().st_size / 1024:.0f} KB)")

            try:
                results = parse_scans_with_mineru(to_process, master_out, master_name)
                for fp in to_process:
                    text = results.get(fp.stem, "")
                    out_name = get_output_name(master_root, fp)
                    out_path = master_out / (out_name + ".md")
                    file_hash = get_file_hash(fp)
                    hash_file = master_out / f".{out_name}.hash"
                    if text.strip():
                        out_path.write_text(text, encoding="utf-8")
                        hash_file.write_text(file_hash, encoding="utf-8")
                        print(f"    [OK] 已保存: {out_path.name} ({len(text)} 字符)")
                    else:
                        print(f"    [FAIL] MinerU 返回空文本: {fp.name}")
            except Exception as e:
                print(f"    [FAIL] MinerU 批量解析失败: {e}")
                continue

    print(f"\n{'='*60}")
    print(f"完成！解析结果在: {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
