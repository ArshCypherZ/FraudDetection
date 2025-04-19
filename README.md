# AI-Driven Fraud Detection MVP

This project implements a lightweight Minimum Viable Product (MVP) for a fraud detection system. It combines rule-based checks with a machine learning model (Logistic Regression) to identify potentially fraudulent transactions in real-time.

## How the System Works

This section describes the typical flow of a transaction through the fraud detection system:

1.  **Transaction Ingestion**: The FastAPI server (`api/main.py`) receives transaction details via a POST request to the `/transaction` endpoint.
2.  **Queueing**: The API validates the incoming data and pushes it onto a Redis list (`transaction_queue`), acting as a message broker for asynchronous processing.
3.  **Polling**: The Decision Engine (`decision_engine.py`), running as a separate process, continuously polls the Redis queue for new transactions.
4.  **Preprocessing**: For each transaction retrieved, the Decision Engine calls `processing/preprocess.py`. This script cleans the data and calculates additional features, such as the user's transaction count in the last 24 hours (from MySQL) and whether the transaction location matches the user's usual location (from MySQL).
5.  **Rule Evaluation**: The Decision Engine then calls `processing/rule_engine.py`. This script applies several predefined rules:
    *   Checks if the transaction amount exceeds `config.RULE_MAX_AMOUNT`.
    *   Checks if the user's transaction frequency in the last hour exceeds `config.RULE_MAX_TRANSACTIONS_PER_HOUR` (using Redis sorted sets).
    *   Uses the Rabin-Karp algorithm to search the transaction description for suspicious keywords/phrases.
    *   Checks if the transaction's IP address is present in the `high_risk_ips` set stored in Redis.
    *   Flags if the `location_mismatch` feature calculated during preprocessing is true.
    Any rules triggered are recorded.
6.  **ML Scoring**: The Decision Engine prepares the relevant features (e.g., `Transaction_Amount`, `user_transaction_count_24h`, `location_mismatch`). The feature scaler (`scaler.joblib`) is loaded, it scales the features. Then, the ONNX model (`model.onnx`) is loaded, it predicts a fraud probability score.
7.  **Hashing**: Before storing results, the Decision Engine calculates:
    *   A **SHA-256 hash** of the transaction's IP address for privacy.
    *   A **SHA-256 checksum** of key transaction fields (ID, user ID, amount, location, description, timestamp) for data integrity verification.
8.  **Final Decision**: A final decision (`approved` or `rejected`) is made based on:
    *   Whether any rules were triggered in step 5.
    *   Whether the ML score from step 6 exceeds the `config.ML_SCORE_THRESHOLD`.
    If either condition is met, the transaction is typically rejected.
9.  **Result Storage**: The Decision Engine stores the original transaction details, the final `status`, any `triggered_rules`, the `ml_score`, the hashed IP address, and the transaction checksum in the MySQL `transactions` table.
10. **Alerting**: If the transaction status is `rejected` and a webhook URL (`config.ALERT_WEBHOOK_URL`) is configured, an alert containing transaction details is sent to the specified endpoint.

## Hashing Usage

Hashing algorithms are employed in the Decision Engine (`decision_engine.py`) for specific purposes:

*   **IP Address Hashing (SHA-256)**: To enhance user privacy, the original IP address associated with a transaction is hashed using SHA-256 before being stored in the `transactions` table in the MySQL database. This allows for potential analysis related to IPs without storing the raw, potentially sensitive, IP address directly.
*   **Transaction Checksum (SHA-256)**: A checksum is calculated using SHA-256 based on a concatenated string of key transaction fields (ID, user ID, amount, location, description, timestamp). This checksum is stored alongside the transaction record in the database. It serves as a data integrity check, allowing verification that the core transaction data hasn't been unintentionally altered during processing or storage.

## Algorithm Usage

*   **Rabin-Karp Algorithm**: Implemented in `processing/rule_engine.py`, the Rabin-Karp algorithm is used within the `check_suspicious_description` function. Its purpose is to efficiently search the transaction `description` field for occurrences of predefined suspicious keywords or phrases (e.g., "urgent payment required", "account verification"). This string-searching algorithm uses hashing to quickly find potential matches, making the rule evaluation process more performant than simple substring checks, especially with longer descriptions or more patterns.

## File Structure

```
FraudDetection/
├── api/
│   └── main.py              # FastAPI server
├── processing/
│   ├── preprocess.py        # Data cleaning & feature engineering
│   └── rule_engine.py       # Rule-based checks & pattern matching
├── ml/
│   ├── train_model.ipynb    # Model training notebook
│   ├── model.onnx           # Exported ML model (generated by notebook)
│   └── scaler.joblib        # Exported feature scaler (generated by notebook)
├── scripts/
│   └── load_risky_ips.py    # Helper script to load IPs to Redis
├── config.py                # Database/Redis/Webhook/Rule/ML config
├── requirements.txt         # Python runtime dependencies
├── requirements-dev.txt     # Python development/training dependencies
└── README.md                # This file
```

## Setup and Run Instructions

Follow these steps in your terminal:

```bash
git clone https://github.com/ArshCypherZ/FraudDetection
cd FraudDetection

# 1. Create a Python virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Linux/macOS
# venv\Scripts\activate  # On Windows

# 2. Install Dependencies
# For running the application (API, Decision Engine):
pip install -r requirements.txt
# For development (including model training):
pip install -r requirements-dev.txt

# 3. Set up Environment Variables
# Create a file named .env in the fraud-detection directory.
# This file is REQUIRED and must contain your specific configurations:
# --- .env file content ---
# REDIS_HOST=localhost
# REDIS_PORT=6379
# MYSQL_HOST=localhost
# MYSQL_USER=your_mysql_user         # REQUIRED - No default value
# MYSQL_PASSWORD=your_mysql_password # REQUIRED - No default value
# MYSQL_DATABASE=fraud_db
# ALERT_WEBHOOK_URL=https://your-webhook-receiver.com/alert # REQUIRED - No default value
#
# # Optional - ML/Rule Configuration (Defaults are in config.py if not set here)
# MODEL_PATH=ml/model.onnx
# SCALER_PATH=ml/scaler.joblib
# RULE_MAX_AMOUNT=1000.00
# RULE_MAX_TRANSACTIONS_PER_HOUR=5
# ML_SCORE_THRESHOLD=0.7
# --- end .env file ---
# Ensure the .env file is present and correctly populated with REQUIRED values before running.

# 4. Set up Database
# - Ensure MySQL server is running and accessible with the credentials provided in .env.
# - Run the setup script which creates the database (if needed) and tables:
#   python3 scripts/setup_database.py
# - The script creates the 'users' and 'transactions' tables.

# 5. Start Redis
# (Requires Docker or a separate Redis instance running)
docker run --name fraud-redis -d -p 6379:6379 redis

# 6. Load High-Risk IPs into Redis (REQUIRED)
# This script requires a file containing the list of high-risk IPs (one per line).
# Then run the script, providing the file path:
python3 scripts/load_risky_ips.py --file risky_ips.txt
# Use --clear to remove existing IPs first (optional):
# python3 scripts/load_risky_ips.py --file risky_ips.txt --clear

# 7. Train ML Model
# - The provided 'ml/train_model.ipynb' uses the Kaggle dataset for demonstration.

# 8. Run the Decision Engine (Background Process)
# This process listens to the Redis queue. Open a NEW terminal/tab for this.
# Ensure the virtualenv is active and .env is configured.
python3 decision_engine.py

# 9. Run the API Server (Foreground Process)
# Open another NEW terminal/tab.
# Ensure the virtualenv is active and .env is configured.
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 10. Test the System
# Send transaction data via POST request to http://localhost:8000/transaction.
# Ensure the 'user_id' exists in your 'users' table for location checks to work correctly.
# Example using curl (replace values with your actual test data):

curl -X POST "http://localhost:8000/transaction" \
    -H "Content-Type: application/json" \
    -d '{
    "transaction_id": "TX_REAL_789",
    "user_id": "YOUR_EXISTING_USER_ID",
    "amount": 120.50,
    "location": "User Location",
    "description": "Purchase description",
    "timestamp": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'",
    "ip_address": "Transaction IP"
}'