import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import logging
import sys
import os
import mysql.connector 

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    import config
except ImportError:
    logging.error(
        "Failed to import config.py. Make sure it's in the project root "
        "and the Python path is correct."
    )
    sys.exit(1)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# --- MySQL Connection Helper ---
def connect_to_mysql():
    """Connects to the MySQL database and returns a connection object."""
    try:
        db_config = config.get_mysql_connection_config()
        connection = mysql.connector.connect(**db_config)
        logger.info("Successfully connected to MySQL database.")
        return connection
    except mysql.connector.Error as e:
        logger.error(f"Failed to connect to MySQL database: {e}")
        return None


# --- Pydantic Model for Transaction Data ---
class Transaction(BaseModel):
    transaction_id: str = Field(
        ..., description="Unique identifier for the transaction"
    )
    user_id: str = Field(
        ..., description="Identifier for the user making the transaction"
    )
    amount: float = Field(..., gt=0, description="Transaction amount, must be positive")
    location: str = Field(..., description="Location where the transaction occurred")
    description: str = Field(..., description="Description of the transaction")
    timestamp: str = Field(
        ..., description="Timestamp of the transaction (e.g., ISO 8601 format)"
    )
    ip_address: str = Field(
        ..., description="IP address from which the transaction originated"
    )


# --- FastAPI App Initialization ---
app = FastAPI(title="Fraud Detection API", version="0.1.0")

# --- Redis Connection ---
try:
    redis_client = redis.Redis(**config.get_redis_connection_config())
    redis_client.ping()  # Verify connection
    logger.info(
        f"Successfully connected to Redis at "
        f"{config.REDIS_HOST}:{config.REDIS_PORT}"
    )
except redis.exceptions.ConnectionError as e:
    logger.error(f"Failed to connect to Redis: {e}")
    redis_client = None  # Indicate connection failure

# --- API Endpoints ---


@app.post("/transaction", status_code=202)
async def receive_transaction(transaction: Transaction):
    """
    Receives transaction data via POST request, validates it using the Transaction model,
    and queues it in Redis for processing.
    """
    if not redis_client:
        logger.error("Redis client not available. Cannot queue transaction.")
        raise HTTPException(
            status_code=503,
            detail=(
                "Service temporarily unavailable due to Redis connection " "issue."
            ),
        )

    try:
        # Data is already validated by FastAPI using the Transaction model
        logger.info(f"Received validated transaction data: {transaction.dict()}")

        transaction_json = transaction.json()

        # Push to Redis queue
        redis_client.rpush(config.REDIS_TRANSACTION_QUEUE, transaction_json)
        logger.info(f"Transaction {transaction.transaction_id} queued successfully.")

        return {"status": "queued", "transaction_id": transaction.transaction_id}

    except redis.exceptions.RedisError as e:
        logger.error(
            f"Redis error while queueing transaction "
            f"{transaction.transaction_id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to queue transaction due to Redis error.",
        )
    except Exception as e:
        transaction_id = transaction.transaction_id if transaction else "N/A"
        logger.exception(
            "An unexpected error occurred processing transaction "
            f"{transaction_id}: {e}"
        )
        raise HTTPException(
            status_code=500, detail="An internal server error occurred."
        )


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    redis_status = (
        "connected" if redis_client and redis_client.ping() else "disconnected"
    )
    mysql_connection = connect_to_mysql()
    mysql_status = "connected" if mysql_connection else "disconnected"
    if mysql_connection:
        mysql_connection.close()
    return {
        "status": "ok",
        "redis_status": redis_status,
        "mysql_status": mysql_status,
    }


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting FastAPI server with Uvicorn...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
