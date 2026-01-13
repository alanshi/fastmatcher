from pathlib import Path
from fastmatcher import ACMatcher


def iter_files(root: str):
    """
    递归遍历目录下所有文件
    """
    root = Path(root)
    for p in root.rglob("*"):
        if p.is_file():
            yield str(p)


if __name__ == "__main__":
    matcher = ACMatcher(
        patterns=["ip_address"],
        ignore_case=False,
        context=1,
    )

    files = list(iter_files("./test_data"))

    print(f"扫描文件数: {len(files)}")

    for m in matcher.search_files_iter(files):
        print("=" * 60)
        print("文件命中")
        print("行号:", m.line_no)
        print("关键词:", ", ".join(m.keywords))
        print("上下文:")
        for line in m.lines:
            print("  ", line.rstrip())
