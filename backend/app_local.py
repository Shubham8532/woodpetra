import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.graph import workflow

app = FastAPI(title="Shubham Fashion Assistant - Local Dev")

# Enable CORS for local testing (Live Server / Uvicorn)
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

# 1. API Endpoints
@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Running locally on http://127.0.0.1:8000"}

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    result = workflow.invoke({"query": request.query}, config=config)
    return {
        "response": result.get("response", "Sorry, something went wrong."),
        "displayed_products": result.get("displayed_products", []),
        "similar_products": result.get("similar_products", [])
    }

# 2. Local Mounts
if (FRONTEND_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")

if (FRONTEND_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

# 3. HTML Page Handlers with No-Cache Headers for Local Debugging
NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0"
}

@app.get("/")
async def read_root():
    index_file = TEMPLATE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), headers=NO_CACHE_HEADERS)
    return {"status": "error", "message": f"Looking for {index_file} but not found."}

@app.get("/{page_name}")
async def read_page(page_name: str):
    if page_name.startswith(("data", "static", "css", "js", "api")):
        return {"status": "error", "message": "Not found"}

    if not page_name.endswith(".html"):
        page_name = f"{page_name}.html"
        
    page_file = TEMPLATE_DIR / page_name
    if page_file.exists():
        return FileResponse(str(page_file), headers=NO_CACHE_HEADERS)
    return FileResponse(str(TEMPLATE_DIR / "index.html"), headers=NO_CACHE_HEADERS)