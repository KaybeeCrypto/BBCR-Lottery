from fastapi import FastAPI
from .database import engine
from .models import Base

app = FastAPI(title="Lottery Backend")

@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"status": "ok"}
