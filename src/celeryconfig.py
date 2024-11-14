import os

broker_url = os.getenv("REDIS_URL")
result_backend = os.getenv("REDIS_URL")

task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "UTC"
enable_utc = True

task_routes = {"src.tasks.classify_file": {"queue": "default"}}

imports = ("src.tasks",)
