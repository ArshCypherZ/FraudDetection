from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Create a separate FastAPI app for serving static files
app = FastAPI(title="Static File Server")

# Mount static files from frontend directory
app.mount("/frontend", StaticFiles(directory=os.path.join(project_root, "frontend")), name="frontend")

@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect to the frontend file"""
    frontend_path = os.path.join(project_root, "frontend", "frontend.html")
    if not os.path.exists(frontend_path):
        raise HTTPException(status_code=404, detail="Frontend file not found")
    
    with open(frontend_path, "r") as f:
        content = f.read()
    
    return HTMLResponse(content=content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("static_file_server:app", host="0.0.0.0", port=8081, reload=True)
