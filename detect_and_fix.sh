#!/usr/bin/env bash

set -e

echo "======================================="
echo " Rust + Python + Maturin 环境自动检测工具"
echo "======================================="
echo

# -------------------------------
# 1. 检测 Linux 发行版
# -------------------------------
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO=$ID
    else
        DISTRO=$(uname -s)
    fi
}

detect_distro
echo "[INFO] 检测到系统: $DISTRO"
echo

# -------------------------------
# 2. 定义安装函数
# -------------------------------
install_packages() {
    case "$DISTRO" in
        ubuntu|debian)
            sudo apt update
            sudo apt install -y build-essential gcc clang python3-dev python3-venv python3-pip
            ;;
        centos|rocky|almalinux|rhel)
            sudo yum groupinstall -y "Development Tools"
            sudo yum install -y clang python3-devel
            ;;
        arch)
            sudo pacman -Sy --noconfirm base-devel gcc clang python
            ;;
        *)
            echo "[ERROR] 未支持的系统，请手动安装依赖."
            exit 1
    esac
}

# -------------------------------
# 3. 检测并安装 C 工具链
# -------------------------------
echo "[CHECK] 检查 gcc..."
if ! command -v gcc >/dev/null; then
    echo "[WARN] gcc 不存在，正在安装..."
    install_packages
else
    echo "[OK] gcc 已存在: $(gcc --version | head -n 1)"
fi

echo "[CHECK] 检查 clang..."
if ! command -v clang >/dev/null; then
    echo "[WARN] clang 不存在，正在安装..."
    install_packages
else
    echo "[OK] clang 已存在: $(clang --version | head -n 1)"
fi

echo "[CHECK] 检查 cc..."
if ! command -v cc >/dev/null; then
    echo "[WARN] cc 不存在，尝试软链接..."
    if command -v gcc >/dev/null; then
        sudo ln -s "$(which gcc)" /usr/bin/cc
        echo "[OK] 已创建 cc → gcc"
    else
        echo "[ERROR] 无法创建 cc，gcc 不存在！"
    fi
else
    echo "[OK] cc 已存在: $(cc --version | head -n 1)"
fi

# -------------------------------
# 4. 检查 Python 环境
# -------------------------------
echo
echo "[CHECK] 检查 Python3..."
if ! command -v python3 >/dev/null; then
    echo "[ERROR] Python3 不存在，请手动安装!"
    exit 1
else
    echo "[OK] Python3: $(python3 --version)"
fi

echo "[CHECK] 检查 pip..."
if ! command -v pip3 >/dev/null; then
    echo "[WARN] pip3 不存在，正在安装..."
    python3 -m ensurepip --upgrade
else
    echo "[OK] pip3 存在"
fi

echo "[CHECK] 检查 Python3 头文件..."
PY_DEV=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('CONFINCLUDEPY'))")
if [ ! -d "$PY_DEV" ]; then
    echo "[WARN] python3-dev 缺失，正在安装..."
    install_packages
else
    echo "[OK] Python 头文件已安装: $PY_DEV"
fi

# -------------------------------
# 5. 检查 Rust
# -------------------------------
echo
echo "[CHECK] 检查 Rust..."
if ! command -v cargo >/dev/null; then
    echo "[WARN] cargo 不存在，正在安装 Rust..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
else
    echo "[OK] Rust 已安装: $(rustc --version)"
fi

# -------------------------------
# 6. 检测是否能编译 Rust 程序
# -------------------------------
echo
echo "[CHECK] 测试编译 Rust 示例程序..."

cat <<EOF > test.rs
fn main() {
    println!("Rust 测试成功!");
}
EOF

if rustc test.rs 2>/dev/null; then
    echo "[OK] Rust 编译正常 ✔"
    ./test
else
    echo "[ERROR] Rust 编译失败！可能依赖未完整安装。"
fi

rm -f test test.rs

# -------------------------------
# 7. 检查 maturin
# -------------------------------
echo
echo "[CHECK] 是否已安装 maturin..."

if ! command -v maturin >/dev/null; then
    echo "[WARN] maturin 不存在，正在安装..."
    pip3 install maturin
else
    echo "[OK] maturin 已安装: $(maturin --version)"
fi

echo
echo "======================================="
echo "   ✔ 所有依赖已检测并自动修复完成！"
echo "   现在你可以构建你的 whl 包了："
echo "      maturin build --release"
echo "======================================="
