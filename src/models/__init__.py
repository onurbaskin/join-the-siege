import os
import uuid
from dataclasses import dataclass
from typing import Dict, Set

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

if find_dotenv():
    load_dotenv()


@dataclass
class DocumentValidation:
    is_valid: bool
    confidence: float
    detected_fields: Dict[str, str]
    missing_fields: Set[str]
    metadata: Dict


Base = declarative_base()


class ClassificationTask(Base):
    __tablename__ = "classification_tasks"
    __table_args__ = {"schema": "public"}

    task_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    status = Column(String(20), nullable=False, default="PENDING")
    file_url = Column(Text, nullable=False)
    result = Column(JSONB)
    error = Column(Text)

    __table_args__ = (
        Index("idx_status", status),
        Index("idx_created_at", created_at),
    )


class Database:
    def __init__(self):
        self.engine = None
        self.Session = None  # Add this line to define Session

    def init_app(self, app):
        database_url = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}/{os.getenv('POSTGRES_DB')}"
        self.engine = create_engine(database_url)

        # Create sessionmaker and bind it to the engine
        self.Session = sessionmaker(bind=self.engine)  # Define Session

        # Create all tables if they don't exist
        Base.metadata.create_all(self.engine)

        # Create trigger function and trigger
        with self.engine.connect() as conn:
            # Create trigger function
            conn.execute(
                text(
                    """
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ language 'plpgsql';
                """
                )
            )

            # Check if trigger exists and create if it doesn't
            result = conn.execute(
                text(
                    """
                SELECT 1 FROM pg_trigger WHERE tgname = 'update_tasks_updated_at';
                """
                )
            )
            trigger_exists = result.fetchone() is not None

            if not trigger_exists:
                conn.execute(
                    text(
                        """
                        CREATE TRIGGER update_tasks_updated_at
                        BEFORE UPDATE ON classification_tasks
                        FOR EACH ROW
                        EXECUTE FUNCTION update_updated_at_column();
                        """
                    )
                )

            conn.commit()


db = Database()
