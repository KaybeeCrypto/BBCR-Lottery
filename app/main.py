from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import engine, SessionLocal, get_db
from .models import Base, Round
from .schemas import RoundCreate, RoundOut


app = FastAPI(title="Lottery Backend")

# Allow frontend to call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kaybeecrypto.github.io",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# Runs once when the server starts
@app.on_event("startup")
def startup_event():
    # Create database tables if missing
    Base.metadata.create_all(bind=engine)

    # Ensure at least one round exists
    db: Session = SessionLocal()
    try:
        existing_round = db.query(Round).first()
        if existing_round is None:
            first_round = Round(status="open")
            db.add(first_round)
            db.commit()
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/rounds", response_model=RoundOut)
def create_round(payload: RoundCreate, db: Session = Depends(get_db)):
    new_round = Round(status=payload.status)
    db.add(new_round)
    db.commit()
    db.refresh(new_round)
    return new_round


@app.get("/rounds/current")
def get_current_round(db: Session = Depends(get_db)):
    # Treat the newest round as the current round
    round_obj = db.query(Round).order_by(Round.id.desc()).first()

    if round_obj is None:
        return {"round": None}

    return {"round": RoundOut.model_validate(round_obj)}
