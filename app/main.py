from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import engine, SessionLocal, get_db
from .models import Base, Round, AdminConfig
from .schemas import RoundCreate, RoundOut
from .schemas import TokenConfigIn
from fastapi import Header, HTTPException
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from datetime import datetime, timedelta
import uuid
import hashlib

# --- Protocol v1 helpers ---

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def build_canonical(holders):
    holders_sorted = sorted(holders, key=lambda x: x[0])
    return "\n".join(f"{w}:{int(b)}" for w, b in holders_sorted)

def parse_canonical_wallets(canonical: str):
    if not canonical:
        return []
    wallets = []
    for line in canonical.split("\n"):
        if not line.strip():
            continue
        wallet, _ = line.split(":", 1)
        wallets.append(wallet)
    return wallets


app = FastAPI(title="Lottery Backend")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://kaybeecrypto.github.io"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()
    try:
        if db.query(Round).first() is None:
            db.add(Round(status="open"))

        if db.query(AdminConfig).first() is None:
            db.add(AdminConfig(round_state="IDLE"))

        db.commit()
    finally:
        db.close()

@app.get("/admin")
def admin_page():
    return FileResponse("static/admin.html")

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
    round_obj = db.query(Round).order_by(Round.id.desc()).first()
    if round_obj is None:
        return {"round": None}
    return {"round": RoundOut.model_validate(round_obj)}

def require_admin(x_admin_secret: str = Header(None)):
    expected = os.getenv("ADMIN_SECRET")
    if expected is None:
        raise HTTPException(status_code=500, detail="Admin secret not configured")
    if x_admin_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")

@app.get("/api/admin/state")
def get_admin_state(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    config = db.query(AdminConfig).first()
    return {
        "token": {
            "mint_address": config.mint_address,
            "min_hold_amount": config.min_hold_amount,
        },
        "snapshot": {
            "snapshot_id": config.snapshot_id,
            "snapshot_time": config.snapshot_time,
            "snapshot_slot": config.snapshot_slot,
            "eligible_holders": config.eligible_holders,
        },
        "round": {
            "state": config.round_state,
            "commit_deadline": config.commit_deadline,
            "reveal_deadline": config.reveal_deadline,
        },
    }

@app.post("/api/admin/token")
def save_token_config(payload: TokenConfigIn, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    config = db.query(AdminConfig).first()
    config.mint_address = payload.mint_address
    config.min_hold_amount = payload.min_hold_amount
    db.commit()
    return {
        "message": "Token configuration saved",
        "mint_address": config.mint_address,
        "min_hold_amount": config.min_hold_amount,
    }

@app.post("/api/admin/holders/preview")
def preview_holders(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    return {
        "token": "mock",
        "min_hold_amount": 0,
        "total_holders": 12482,
        "eligible_holders": 3194,
        "excluded": {"lp_accounts": 3, "burn_addresses": 1},
        "preview_time": datetime.utcnow().isoformat(),
    }

@app.post("/api/admin/snapshot")
def take_snapshot(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    config = db.query(AdminConfig).first()

    if config.round_state != "IDLE":
        raise HTTPException(status_code=400, detail="Snapshot already taken or round already started")

    snapshot_id = str(uuid.uuid4())
    snapshot_time = datetime.utcnow()
    snapshot_slot = 123456789

    mock_eligible = [
        ("WalletA", 100),
        ("WalletB", 50),
        ("WalletC", 25),
        ("WalletD", 10),
    ]

    canonical = build_canonical(mock_eligible)
    snapshot_root = sha256_hex(canonical)
    eligible_holders = len(mock_eligible)

    config.snapshot_id = snapshot_id
    config.snapshot_time = snapshot_time
    config.snapshot_slot = snapshot_slot
    config.eligible_holders = eligible_holders
    config.eligible_canonical = canonical
    config.snapshot_root = snapshot_root
    config.round_state = "SNAPSHOT_TAKEN"

    db.commit()

    return {
        "snapshot_id": snapshot_id,
        "snapshot_time": snapshot_time.isoformat(),
        "snapshot_slot": snapshot_slot,
        "eligible_holders": eligible_holders,
        "snapshot_root": snapshot_root,
        "state": config.round_state,
    }

@app.post("/api/admin/commit/start")
def start_commit_phase(commit_minutes: int = 30, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    config = db.query(AdminConfig).first()
    if config.round_state != "SNAPSHOT_TAKEN":
        raise HTTPException(status_code=400, detail="Cannot start commit phase in current state")

    config.commit_deadline = datetime.utcnow() + timedelta(minutes=commit_minutes)
    config.round_state = "COMMIT"
    db.commit()

    return {
        "state": config.round_state,
        "commit_deadline": config.commit_deadline.isoformat(),
    }

@app.post("/api/admin/reveal/start")
def start_reveal_phase(reveal_minutes: int = 15, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    config = db.query(AdminConfig).first()

    if config.round_state != "COMMIT":
        raise HTTPException(status_code=400, detail="Cannot start reveal phase in current state")

    if config.commit_deadline is None or datetime.utcnow() < config.commit_deadline:
        raise HTTPException(status_code=400, detail="Commit deadline not reached")

    config.target_slot = 999_999_999
    config.reveal_deadline = datetime.utcnow() + timedelta(minutes=reveal_minutes)
    config.round_state = "REVEAL"
    db.commit()

    return {
        "state": config.round_state,
        "target_slot": config.target_slot,
        "reveal_deadline": config.reveal_deadline.isoformat(),
    }

@app.post("/api/admin/finalize")
def finalize_winner(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    config = db.query(AdminConfig).first()

    if config.round_state != "REVEAL":
        raise HTTPException(status_code=400, detail="Cannot finalize in current state")

    if datetime.utcnow() < config.reveal_deadline:
        raise HTTPException(status_code=400, detail="Reveal deadline not reached")

    if config.winner_wallet:
        raise HTTPException(status_code=400, detail="Winner already finalized")

    blockhash = "PLACEHOLDER_BLOCKHASH"

    seed = f"{blockhash}|{config.snapshot_root}"
    digest = hashlib.sha256(seed.encode()).hexdigest()
    number = int(digest, 16)

    eligible_wallets = parse_canonical_wallets(config.eligible_canonical)
    winner_index = number % len(eligible_wallets)
    winner_wallet = eligible_wallets[winner_index]

    config.winner_wallet = winner_wallet
    config.winner_index = winner_index
    config.blockhash = blockhash
    config.round_state = "FINALIZED"

    db.commit()

    return {
        "state": config.round_state,
        "winner_wallet": winner_wallet,
        "blockhash": blockhash,
        "proof": {
            "snapshot_id": config.snapshot_id,
            "snapshot_root": config.snapshot_root,
            "winner_index": winner_index,
            "hash_algorithm": "sha256",
        },
    }
