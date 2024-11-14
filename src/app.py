# app.py
import os
import uuid

import boto3
from botocore.config import Config
from dotenv import find_dotenv, load_dotenv
from flask import Flask, jsonify, request
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.models import ClassificationTask, db
from src.tasks import celery_app, classify_file

if find_dotenv():
    load_dotenv()

app = Flask(__name__)

# Initialize database
db.init_app(app)

# Create session factory
Session = sessionmaker(bind=db.engine)

# S3 client configuration
s3_client = boto3.client(
    "s3",
    endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_DEFAULT_REGION"),
    config=Config(signature_version="s3v4"),
)


@app.route("/classify_file", methods=["POST"])
def classify_file_route():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    try:
        # Generate task ID
        task_id = str(uuid.uuid4())

        # Upload file to S3
        bucket_name = "localstack-classify-files"
        file_key = f"uploads/{task_id}/{file.filename}"

        # Ensure bucket exists
        try:
            s3_client.head_bucket(Bucket=bucket_name)
        except:
            s3_client.create_bucket(Bucket=bucket_name)

        # Upload file
        s3_client.upload_fileobj(file, bucket_name, file_key)
        file_url = f"s3://{bucket_name}/{file_key}"

        # Create database entry
        session = Session()
        try:
            task = ClassificationTask(task_id=task_id, file_url=file_url)
            session.add(task)
            session.commit()
        finally:
            session.close()

        classify_file.delay(task_id, file_url)

        return (
            jsonify(
                {
                    "task_id": str(task_id),
                    "message": "File uploaded and processing started",
                }
            ),
            202,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/task_status/<task_id>", methods=["GET"])
def task_status(task_id):
    try:
        session = Session()
        try:
            task = (
                session.query(ClassificationTask)
                .filter_by(task_id=task_id)
                .first()
            )

            if task is None:
                return jsonify({"error": "Task not found"}), 404

            return jsonify(
                {
                    "task_id": str(task.task_id),
                    "status": task.status,
                    "result": task.result,
                    "error": task.error,
                    "created_at": task.created_at.isoformat(),
                    "updated_at": task.updated_at.isoformat(),
                }
            )
        finally:
            session.close()

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health_check():
    try:
        # Check database connection
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        # Check Redis connection
        celery_app.backend.ping()

        # Check S3 connection
        s3_client.list_buckets()

        return (
            jsonify(
                {
                    "status": "healthy",
                    "services": {
                        "database": "connected",
                        "redis": "connected",
                        "s3": "connected",
                    },
                }
            ),
            200,
        )
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
