import asyncio
from pathlib import Path
from itertools import islice
from typing import Iterable, List

from fastmatcher import ACMatcher


async def iter_files_async(root: str):
    """
    异步递归遍历目录下所有文件
    """
    root = Path(root)
    for path in root.rglob("*"):
        if path.is_file():
            yield str(path)


def batched(iterable: Iterable[str], size: int = 1000):
    """
    把迭代器分批
    """
    it = iter(iterable)
    while True:
        batch = list(islice(it, size))
        if not batch:
            break
        yield batch


async def search_async(matcher: ACMatcher, files: List[str]):
    """
    async 封装 Rust generator（线程池执行，不阻塞 event loop）
    """
    loop = asyncio.get_running_loop()

    def run_rust():
        for m in matcher.search_files_iter(files):
            yield m

    # 把生成器结果收集成列表（线程中执行）
    results = await loop.run_in_executor(None, lambda: list(run_rust()))
    for r in results:
        yield r


async def scan_dir_async(
    root: str,
    matcher: ACMatcher,
    batch_size: int = 2000,
):
    """
    async generator：逐条 yield MatchInfo
    """
    # 异步遍历目录
    files = [p async for p in iter_files_async(root)]

    # 分批扫描
    for batch in batched(files, batch_size):
        async for m in search_async(matcher, batch):
            yield m


# ------------------------
# CLI / 测试示例
# ------------------------

async def main():
    matcher = ACMatcher(
        patterns=["ERROR", "FATAL", "panic", "Exception"],
        ignore_case=True,
        context=1,
    )

    async for m in scan_dir_async("./test_data", matcher):
        print("=" * 60)
        print(f"行号: {m.line_no}")
        print("关键词:", ", ".join(m.keywords))
        print("上下文:")
        for line in m.lines:
            print(" ", line.rstrip())


if __name__ == "__main__":
    asyncio.run(main())
