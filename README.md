# Getting Started

## Prerequisites

### Install Docker
Follow the [Docker installation guide](https://docs.docker.com/engine/install/) for your system's requirements.

### Install awslocal
This package provides the `awslocal` command, which is a thin wrapper around the AWS command line interface for use with LocalStack.

```bash
pip install "awscli-local[ver2]"
```

### Install LocalStack

```bash
# MacOS
brew install localstack/tap/localstack-cli

# PyPI (MacOS, Windows, Linux)
python3 -m pip install localstack
```

## Running the Application

### Option 1: Using Docker Compose

```bash
# Build and run the containers
docker-compose build --no-cache
docker-compose up -d

# Note: You might need to manually restart Celery due to a known bug
```

### Option 2: Running Services Individually

```bash
# Start Redis
docker run --name redis_container -p 6379:6379 redis/redis-stack-server

# Start PostgreSQL
docker run -d --name postgres-container \
    -e POSTGRES_DB=document_classifier \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    -p 5432:5432 postgres

# Additional Services:
# - LocalStack creates a docker image after installation
# - Flask can be started via VSCode debugger
# - Celery can be started with: celery -A src.tasks worker --pool=solo --loglevel=info
```

## Usage Notes

### Development Recommendations
- It's recommended to run services individually instead of using docker-compose for testing:
  - Better visibility of changes and logs
  - Avoid potential LocalStack docker issues
  - The project has been tested and works fine locally

### Running the Application
1. Start the services using either method above
2. Access the application:
   - Docker Compose: `localhost:8000`
   - VSCode debugger: Custom port (e.g., Flask default `5000`)
3. Send requests to `/classify_file` with file payload
4. Monitor progress:
   - Watch Celery terminal output
   - Poll `/task_status/{task_id}` endpoint

## Architecture Notes

The project uses Celery+Redis for the following reasons:
- Immediate request acceptance and storage in Redis broker
- Asynchronous processing by workers
- Non-blocking `/classify_file` endpoint
- Results can be checked regularly for long-running tasks

### Potential Improvements
- Reduce task duration by:
  - Allocating more resources (CPU/GPU)
  - Using models trained for specific document types
  - These options can be discussed based on company needs

---
*Note: This solution demonstrates asynchronous processing capabilities while maintaining system responsiveness. Thank you for the opportunity!*