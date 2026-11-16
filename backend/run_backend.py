import uvicorn
from app.config import settings

if __name__ == "__main__":
    print(f"Starting BuildWise AI Backend on {settings.HOST}:{settings.PORT}...")
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=not settings.is_production)
