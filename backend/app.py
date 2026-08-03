import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.graph import workflow

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
TEMPLATE_DIR = FRONTEND_DIR / "template"
DATA_DIR = BASE_DIR / "data"

class ChatRequest(BaseModel):
    query: str
    thread_id: str

# 1. Primary Root Route
@app.get("/")
async def read_root():
    index_file = TEMPLATE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"status": "error", "message": f"Looking for {index_file} but not found."}

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Shubham Fashion Assistant API is running"}

# 2. Chat API Endpoint
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    config = {
        "configurable": {
            "thread_id": request.thread_id
        }
    }
    result = workflow.invoke(
        {
            "query": request.query
        },
        config=config
    )
    return {
        "response": result.get("response", "Sorry, something went wrong."),
        "displayed_products": result.get("displayed_products", []),
        "similar_products": result.get("similar_products", [])
    }

# 3. Mount Data and Static Directories
if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# 4. Specific HTML Page Handler (Strictly targeting .html files to avoid hijacking /data requests)
@app.get("/{page_name}")
async def read_page(page_name: str):
    # Skip routing if requesting static resources
    if page_name.startswith("data") or page_name.startswith("static") or page_name.startswith("api"):
        return {"status": "error", "message": "Not found"}

    if not page_name.endswith(".html"):
        page_name = f"{page_name}.html"
        
    page_file = TEMPLATE_DIR / page_name
    if page_file.exists():
        return FileResponse(str(page_file))
    return FileResponse(str(TEMPLATE_DIR / "index.html"))