import subprocess
import sys
from pathlib import Path

# ---------------- 配置 ----------------
PROJECT_DIR = Path(__file__).parent.resolve()
PYTHON_EXECUTABLE = sys.executable  # 使用当前 Python 解释器
RELEASE = True                       # 是否用 release 模式
# -------------------------------------

def run_command(cmd, cwd=None):
    """执行 shell 命令"""
    result = subprocess.run(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}")

def build_whl():
    """使用 maturin 构建 wheel"""
    print("Building Python wheel with maturin...")
    cmd = f"{PYTHON_EXECUTABLE} -m maturin build"
    if RELEASE:
        cmd += " --release"
    run_command(cmd, cwd=PROJECT_DIR)
    wheels_dir = PROJECT_DIR / "target" / "wheels"
    whls = list(wheels_dir.glob("*.whl"))
    if not whls:
        raise FileNotFoundError("Wheel file not found after build.")
    whl_path = whls[0]
    print(f"Wheel built at: {whl_path}")
    return whl_path

def install_whl(whl_path: Path):
    """安装生成的 wheel"""
    print(f"Installing {whl_path} ...")
    cmd = f"{PYTHON_EXECUTABLE} -m pip install --force-reinstall {whl_path}"
    run_command(cmd)
    print("Installation complete.")

def test_installation():
    """简单测试是否能 import 和调用"""
    print("Testing installed fastmatcher module...")
    import fastmatcher
    matcher = fastmatcher.ACMatcher(["测试", "关键字"], ignore_case=True)
    text = "这是一个测试文本，包含关键字"
    matches = matcher.search(text)
    print("Test search result:", matches)

if __name__ == "__main__":
    whl_path = build_whl()
    install_whl(whl_path)
    test_installation()
