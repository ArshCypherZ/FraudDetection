import redis
from fastapi import FastAPI, HTTPException, Query, Response, Depends, status
from pydantic import BaseModel, Field
import logging
import sys
import os
import mysql.connector 
import json
from datetime import datetime, timedelta
from typing import List, Optional
import csv
import io
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    import config
    # Import from the local auth module
    from api.auth import (
        authenticate_user, create_access_token, get_current_active_user,
        ACCESS_TOKEN_EXPIRE_MINUTES, Token, User, UserCreate, create_user
    )
except ImportError as e:
    logging.error(
        f"Failed to import modules: {str(e)}. Make sure the Python path is correct."
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


# --- Pydantic Models ---
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

class TransactionCheck(BaseModel):
    amount: float = Field(..., gt=0, description="Transaction amount")
    description: str = Field(default="", description="Transaction description")
    location: Optional[str] = Field(None, description="Transaction location")
    ip_address: Optional[str] = Field(None, description="IP address")

class TransactionResponse(BaseModel):
    transaction_id: str
    amount: float
    timestamp: str
    status: str

class ExportRequest(BaseModel):
    format: str = Field(..., description="Export format (csv, excel, pdf)")
    start_date: str = Field(..., description="Start date for export")
    end_date: str = Field(..., description="End date for export")
    status: str = Field(..., description="Filter by status (all, safe, fraudulent)")


# --- FastAPI App Initialization ---
app = FastAPI(title="Fraud Detection API", version="0.1.0")

# Add CORS middleware to allow frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production, replace with actual origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
async def receive_transaction(transaction: Transaction, current_user: User = Depends(get_current_active_user)):
    """
    Receives transaction data via POST request, validates it using the Transaction model,
    and queues it in Redis for processing. Requires authentication.
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
        # Associate the transaction with the authenticated user
        transaction.user_id = current_user.user_id
        
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


@app.post("/check-transaction")
async def check_transaction(transaction: TransactionCheck, current_user: User = Depends(get_current_active_user)):
    """
    Check a transaction for fraud.
    """
    try:
        # Import the enhanced check function
        from api.enhanced_check import enhanced_check_transaction
        
        # Pass the user_id to the function
        result = await enhanced_check_transaction(transaction, logger, current_user.user_id)
        return result
    except Exception as e:
        logger.exception(f"Error checking transaction: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze transaction: {str(e)}"
        )


@app.get("/api/statistics")
async def get_statistics(current_user: User = Depends(get_current_active_user)):
    """
    Returns dashboard statistics: total transactions, frauds detected, and success rate
    Requires authentication.
    """
    try:
        conn = connect_to_mysql()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        cursor = conn.cursor(dictionary=True)
        
        # Get total transactions
        cursor.execute("SELECT COUNT(*) as total FROM transactions")
        total_transactions = cursor.fetchone()['total']
        
        # Get fraudulent transactions 
        cursor.execute("SELECT COUNT(*) as frauds FROM transactions WHERE status IN ('rejected', 'Fraudulent')")
        frauds_detected = cursor.fetchone()['frauds']
        
        # Calculate success rate
        success_rate = 0
        if total_transactions > 0:
            success_rate = round(((total_transactions - frauds_detected) / total_transactions) * 100, 1)
        
        conn.close()
        
        return {
            "total_transactions": total_transactions,
            "frauds_detected": frauds_detected,
            "success_rate": success_rate
        }
        
    except mysql.connector.Error as e:
        logger.error(f"MySQL error in statistics endpoint: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@app.get("/api/transactions", response_model=List[TransactionResponse])
async def get_transactions(
    limit: int = Query(10, description="Number of transactions to return"),
    status: Optional[str] = Query(None, description="Filter by status (Safe or Fraudulent)"),
    days: int = Query(30, description="Number of days to look back"),
    current_user: User = Depends(get_current_active_user)
):
    """
    Returns recent transaction history with optional filtering for the authenticated user
    """
    try:
        conn = connect_to_mysql()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        cursor = conn.cursor(dictionary=True)
        
        query = """
        SELECT id, amount, timestamp, status
        FROM transactions
        WHERE timestamp >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        AND user_id = %s
        """
        params = [days, current_user.user_id]
        
        if status:
            query += " AND status = %s"
            params.append(status)
        
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        transactions = cursor.fetchall()
        
        # Format response
        result = []
        for tx in transactions:
            result.append({
                "transaction_id": tx["id"],
                "amount": float(tx["amount"]),
                "timestamp": tx["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                "status": tx["status"]
            })
        
        conn.close()
        return result
        
    except mysql.connector.Error as e:
        logger.error(f"MySQL error in transactions endpoint: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@app.get("/api/risk-analysis")
async def get_risk_analysis(days: int = Query(7, description="Number of days to include")):
    """
    Returns risk analysis data for the chart
    """
    try:
        conn = connect_to_mysql()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        cursor = conn.cursor(dictionary=True)
        
        query = """
        SELECT date, total_transactions, fraud_attempts, risk_score 
        FROM daily_metrics
        WHERE date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        ORDER BY date
        """
        
        cursor.execute(query, (days,))
        metrics = cursor.fetchall()
        
        # Format for chart data
        dates = []
        transactions = []
        fraud_attempts = []
        risk_scores = []
        
        for m in metrics:
            dates.append(m["date"].strftime("%b %d"))
            transactions.append(m["total_transactions"])
            fraud_attempts.append(m["fraud_attempts"])
            risk_scores.append(float(m["risk_score"]))
        
        conn.close()
        
        return {
            "dates": dates,
            "transactions": transactions,
            "fraud_attempts": fraud_attempts,
            "risk_scores": risk_scores
        }
        
    except mysql.connector.Error as e:
        logger.error(f"MySQL error in risk analysis endpoint: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@app.post("/api/export")
async def export_data(request: ExportRequest):
    """
    Exports transaction data in the requested format
    """
    try:
        conn = connect_to_mysql()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        cursor = conn.cursor(dictionary=True)
        
        query = """
        SELECT id, user_id, amount, timestamp, ip_address, status, description, location
        FROM transactions
        WHERE timestamp BETWEEN %s AND %s
        """
        params = [request.start_date, request.end_date]
        
        if request.status != "all":
            query += " AND status = %s"
            params.append(request.status.capitalize())  # Convert to "Safe" or "Fraudulent"
        
        cursor.execute(query, params)
        transactions = cursor.fetchall()
        
        # For now, we'll only implement CSV export
        if request.format.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(["Transaction ID", "User ID", "Amount", "Timestamp", "IP Address", "Status", "Description", "Location"])
            
            # Write data
            for tx in transactions:
                writer.writerow([
                    tx["id"],
                    tx["user_id"],
                    tx["amount"],
                    tx["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                    tx["ip_address"],
                    tx["status"],
                    tx["description"],
                    tx["location"]
                ])
            
            output.seek(0)
            conn.close()
            
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=transactions_{datetime.now().strftime('%Y%m%d')}.csv"}
            )
            
        else:
            conn.close()
            return {"message": f"Export format '{request.format}' not implemented yet. Try 'csv'."}
        
    except mysql.connector.Error as e:
        logger.error(f"MySQL error in export endpoint: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Get an access token using username and password
    """
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.user_id, "username": user.username},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.user_id, "username": user.username}


@app.post("/register", status_code=201)
async def register_user(user_data: UserCreate):
    """
    Register a new user
    """
    try:
        user = create_user(user_data)
        return {"status": "success", "message": "User registered successfully", "user_id": user["user_id"]}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        raise HTTPException(status_code=500, detail="Error registering user")


@app.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """
    Get information about the currently authenticated user
    """
    return current_user


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