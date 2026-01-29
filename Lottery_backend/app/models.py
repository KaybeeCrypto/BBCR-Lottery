from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from .database import Base


class Round(Base):
    __tablename__ = "rounds"

    id = Column(Integer, primary_key=True, index=True)
    round_id = Column(String, unique=True, index=True)
    status = Column(String)  # scheduled / committed / revealed / paid

    snapshot_hash = Column(String, nullable=True)
    target_slot = Column(Integer, nullable=True)
    blockhash = Column(String, nullable=True)
    winner_wallet = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
