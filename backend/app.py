from fastapi import FastAPI

app = FastAPI(
    title="AI Shopping Assistant",
    version="1.0"
)

@app.get("/")
def home():
    return {
        "status": "Running",
        "project": "AI Shopping Assistant"
    }