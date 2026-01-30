from fastapi import FastAPI
from .database import engine
from .models import Base
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from fastapi import Depends
from .database import get_db
from .models import Round
from .schemas import RoundOut
from typing import Optional

app = FastAPI(title="Lottery Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kaybeecrypto.github.io",  # replace with your GitHub Pages domain root
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/rounds/current")
def get_current_round(db: Session = Depends(get_db)):
    round_obj = db.query(Round).order_by(Round.created_at.desc()).first()

    if round_obj is None:
        return {"round": None}

    return {"round": RoundOut.model_validate(round_obj)}