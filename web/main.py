import asyncio
import os
import json
import time
from pathlib import Path
from itertools import islice
from typing import Iterable, List, Optional, Dict, Any
from uuid import uuid4
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
from fastmatcher import ACMatcher

# ========== 初始化配置 ==========
app = FastAPI(title="FastMatcher API", version="1.0")

# 模板和静态文件配置
templates = Jinja2Templates(directory="web/templates")
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# 全局存储 - 搜索任务和结果（带过期机制）
search_tasks: Dict[str, asyncio.Event] = {}  # 取消事件
search_results: Dict[str, Dict[str, Any]] = {}  # 存储完整结果
SEARCH_RESULT_EXPIRE = 3600  # 结果保留1小时

# ========== 数据模型 ==========
class SearchRequest(BaseModel):
    """搜索请求参数模型"""
    directory: str
    keywords: List[str]
    context: int = 1
    batch_size: int = 2000

    @field_validator('directory')
    def validate_directory(cls, v):
        if not v:
            raise ValueError("目录路径不能为空")
        path = Path(v)
        if not path.exists():
            raise ValueError(f"目录不存在: {v}")
        if not path.is_dir():
            raise ValueError(f"不是有效的目录: {v}")
        if not os.access(v, os.R_OK):
            raise ValueError(f"没有读取目录的权限: {v}")
        return v

    @field_validator('keywords')
    def validate_keywords(cls, v):
        if not v or len(v) == 0:
            raise ValueError("关键词列表不能为空")
        cleaned = [kw.strip() for kw in v if kw.strip()]
        if not cleaned:
            raise ValueError("关键词不能全为空")
        return cleaned

    @field_validator('context')
    def validate_context(cls, v):
        if v < 0 or v > 10:
            raise ValueError("上下文行数必须在0-10之间")
        return v

    @field_validator('batch_size')
    def validate_batch_size(cls, v):
        if v < 100 or v > 10000:
            raise ValueError("批处理大小必须在100-10000之间")
        return v

class CancelRequest(BaseModel):
    """取消搜索请求模型"""
    search_id: str

# ========== 工具函数 ==========
def remove_file(file_path: str):
    """删除临时文件"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"已删除临时文件: {file_path}")
    except Exception as e:
        print(f"删除临时文件失败 {file_path}: {e}")

# ========== 核心业务逻辑 ==========
async def cleanup_expired_results():
    """后台清理过期的搜索结果"""
    while True:
        now = time.time()
        expired_ids = []
        for search_id, result_data in search_results.items():
            if now - result_data["create_time"] > SEARCH_RESULT_EXPIRE:
                expired_ids.append(search_id)

        for search_id in expired_ids:
            search_results.pop(search_id, None)
            print(f"清理过期结果: {search_id}")

        await asyncio.sleep(600)  # 每10分钟检查一次

async def iter_files_async(root: str) -> Iterable[str]:
    """异步遍历目录下的所有文件"""
    root_path = Path(root)
    for path in root_path.rglob("*"):
        if path.is_file() and os.access(path, os.R_OK):
            yield str(path)
        await asyncio.sleep(0)

def batched(iterable: Iterable[str], size: int = 1000) -> Iterable[List[str]]:
    """将可迭代对象分批处理"""
    it = iter(iterable)
    while True:
        batch = list(islice(it, size))
        if not batch:
            break
        yield batch

async def search_files_batch(matcher: ACMatcher, files: List[str]) -> List[dict]:
    """异步搜索一批文件"""
    loop = asyncio.get_running_loop()

    def search_sync():
        results = []
        for match in matcher.search_files_iter(files):
            # 确保 keywords 是数组
            match_keywords = match.keywords
            if isinstance(match_keywords, str):
                match_keywords = [match_keywords]
            elif not isinstance(match_keywords, list):
                match_keywords = []
            results.append({
                "file": match.file_path,
                "line_no": match.line_no,
                "keywords": match_keywords,  # 确保是数组
                "lines": match.lines
            })
        return results

    try:
        return await loop.run_in_executor(None, search_sync)
    except Exception as e:
        print(f"搜索批处理失败: {e}")
        return []

async def run_full_search(req: SearchRequest, search_id: str, cancel_event: asyncio.Event):
    """执行完整搜索并存储结果"""
    try:
        # 初始化匹配器
        matcher = ACMatcher(
            patterns=req.keywords,
            ignore_case=True,
            context=req.context
        )

        # 获取所有文件
        files = [file async for file in iter_files_async(req.directory)]
        total_files = len(files)
        all_matches = []
        processed_files = 0

        # 分批搜索
        for batch in batched(files, req.batch_size):
            if cancel_event.is_set():
                break

            matches = await search_files_batch(matcher, batch)
            all_matches.extend(matches)
            processed_files += len(batch)

            # 更新进度（供前端轮询）
            search_results[search_id]["progress"] = processed_files / total_files if total_files else 0
            search_results[search_id]["processed"] = processed_files
            search_results[search_id]["total"] = total_files
            await asyncio.sleep(0)

        # 存储完整结果
        search_results[search_id].update({
            "progress": 1.0,
            "completed": True,
            "results": all_matches,
            "count": len(all_matches),
            "search_params": req.model_dump()
        })

    except Exception as e:
        search_results[search_id]["error"] = str(e)
        search_results[search_id]["completed"] = True
        print(f"搜索出错 {search_id}: {e}")

# ========== API路由 ==========
@app.on_event("startup")
async def startup_event():
    """启动时启动清理任务"""
    asyncio.create_task(cleanup_expired_results())

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页（搜索页面）"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/results/{search_id}", response_class=HTMLResponse)
async def results_page(request: Request, search_id: str):
    """结果展示页面"""
    # 检查结果是否存在
    if search_id not in search_results:
        raise HTTPException(status_code=404, detail="搜索结果不存在或已过期")

    result_data = search_results[search_id]
    if not result_data.get("completed"):
        # 如果还在搜索中，重定向回首页并提示
        return templates.TemplateResponse("index.html", {
            "request": request,
            "search_id": search_id,
            "searching": True
        })

    return templates.TemplateResponse("results.html", {
        "request": request,
        "search_id": search_id,
        "result_data": result_data
    })

@app.post("/api/start-search")
async def start_search(req: SearchRequest, background_tasks: BackgroundTasks):
    """启动搜索（返回search_id，供前端轮询进度）"""
    search_id = str(uuid4())

    # 初始化结果存储
    search_results[search_id] = {
        "create_time": time.time(),
        "progress": 0.0,
        "completed": False,
        "processed": 0,
        "total": 0,
        "results": [],
        "count": 0,
        "error": None
    }

    # 创建取消事件
    cancel_event = asyncio.Event()
    search_tasks[search_id] = cancel_event

    # 后台执行搜索
    background_tasks.add_task(run_full_search, req, search_id, cancel_event)

    return {
        "search_id": search_id,
        "status": "started"
    }

@app.get("/api/search-status/{search_id}")
async def get_search_status(search_id: str):
    """获取搜索状态（供前端轮询）"""
    if search_id not in search_results:
        raise HTTPException(status_code=404, detail="搜索任务不存在")

    result_data = search_results[search_id]
    return {
        "progress": result_data.get("progress", 0.0),
        "completed": result_data.get("completed", False),
        "error": result_data.get("error"),
        "processed": result_data.get("processed", 0),
        "total": result_data.get("total", 0),
        "count": result_data.get("count", 0)
    }

@app.post("/api/cancel-search")
async def cancel_search(req: CancelRequest):
    """取消搜索"""
    cancel_event = search_tasks.get(req.search_id)
    if not cancel_event:
        raise HTTPException(status_code=404, detail="搜索任务不存在或已完成")

    cancel_event.set()
    # 标记为已取消
    if req.search_id in search_results:
        search_results[req.search_id]["error"] = "用户取消了搜索"
        search_results[req.search_id]["completed"] = True

    # 清理任务
    asyncio.create_task(_cleanup_task(req.search_id))
    return {"status": "cancelled", "search_id": req.search_id}

@app.get("/api/download-json/{search_id}")
async def download_json(search_id: str, background_tasks: BackgroundTasks):
    """下载JSON格式的搜索结果（修复BackgroundTasks使用方式）"""
    if search_id not in search_results:
        raise HTTPException(status_code=404, detail="搜索结果不存在或已过期")

    result_data = search_results[search_id]
    if not result_data.get("completed"):
        raise HTTPException(status_code=400, detail="搜索尚未完成，无法下载")

    # 准备JSON数据
    json_data = {
        "search_id": search_id,
        "create_time": datetime.fromtimestamp(result_data["create_time"]).isoformat(),
        "search_params": result_data.get("search_params", {}),
        "total_files": result_data.get("total", 0),
        "matched_count": result_data.get("count", 0),
        "results": result_data.get("results", []),
        "completed": result_data.get("completed", False),
        "error": result_data.get("error")
    }

    # 生成临时JSON文件
    filename = f"search_result_{search_id}.json"
    filepath = Path(f"temp/{filename}")

    # 创建temp目录
    filepath.parent.mkdir(exist_ok=True)

    # 写入文件（确保中文/特殊字符正常）
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    # 修复：正确使用BackgroundTasks添加删除文件任务
    background_tasks.add_task(remove_file, str(filepath))

    # 返回文件下载响应
    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/json"
    )

async def _cleanup_task(search_id: str, delay: float = 1.0):
    """延迟清理任务"""
    await asyncio.sleep(delay)
    search_tasks.pop(search_id, None)

# ========== 异常处理 ==========
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """参数验证异常处理"""
    return JSONResponse(
        status_code=400,
        content={"error": str(exc)}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)