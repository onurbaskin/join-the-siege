import asyncio
import os
import tempfile
from typing import Dict

import boto3
import psycopg2
from botocore.config import Config
from celery import Celery
from dotenv import find_dotenv, load_dotenv
from sqlalchemy.orm import sessionmaker
from werkzeug.datastructures import FileStorage

from src.classifier import DocumentClassifierFactory
from src.classifiers.bank_statement_classifier import BankStatementClassifier
from src.classifiers.drivers_license_classifier import DriversLicenseClassifier
from src.classifiers.invoice_classifier import InvoiceClassifier
from src.models import ClassificationTask, db

if find_dotenv():
    load_dotenv()

# Initialize Celery with the correct import paths
celery_app = Celery("document_classifier")

db.init_app(celery_app)

# Celery Configuration
celery_app.conf.update(
    broker_url=os.getenv("REDIS_URL"),
    result_backend=os.getenv("REDIS_URL"),
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    worker_concurrency=1,
    worker_pool="solo",
    worker_prefetch_multiplier=1,
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
)

# S3 client configuration
s3_client = boto3.client(
    "s3",
    endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_DEFAULT_REGION"),
    config=Config(signature_version="s3v4"),
)


# Database connection
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


# Create session factory
Session = sessionmaker(bind=db.engine)


def run_async(coro):
    """Helper function to run async code in sync context"""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


@celery_app.task(name="src.tasks.classify_file")
def classify_file(task_id: str, file_url: str) -> Dict:
    try:
        # Parse the S3 URL
        bucket, key = file_url.split("/", 3)[2:]

        # Download file from S3 to a temporary file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            # Save the temporary file path for later use
            temp_file_path = temp_file.name

            # Download the file from S3 to the temporary file
            s3_client.download_file(bucket, key, temp_file_path)

            # Create a FileStorage object with the correct filename for the classifier
            file_storage = FileStorage(
                open(temp_file_path, "rb"),
                filename=key.split("/")[
                    -1
                ],  # Set filename from S3 key (i.e., file name)
            )

            # Initialize classifier
            classifier = DocumentClassifierFactory()
            classifier.register_classifier(DriversLicenseClassifier())
            classifier.register_classifier(BankStatementClassifier())
            classifier.register_classifier(InvoiceClassifier())

            # Process file using the classifier
            result = run_async(classifier.classify_document(file_storage))

            # Optional: Clean up temporary file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

            # Update database with result
            session = db.Session()
            try:
                task = (
                    session.query(ClassificationTask)
                    .filter_by(task_id=task_id)
                    .first()
                )
                if task:
                    task.status = "COMPLETED"
                    task.result = result
                    session.commit()
            finally:
                session.close()

            return result

    except Exception as e:
        # Update database with error
        session = db.Session()
        try:
            task = (
                session.query(ClassificationTask)
                .filter_by(task_id=task_id)
                .first()
            )
            if task:
                task.status = "FAILED"
                task.error = str(e)
                session.commit()
        finally:
            session.close()
        raise
