# fasfastmatcher

## Cross Compiling from macOS to Windows

```sh
rustup target add x86_64-pc-windows-gnu
brew install mingw-w64

uv python install 3.12

uv venv .venv312
source .venv312/bin/activate
maturin build --release --target x86_64-pc-windows-gnu -i python3.12
```
