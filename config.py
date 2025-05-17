import os
from dotenv import load_dotenv

load_dotenv()

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_TRANSACTION_QUEUE = "transaction_queue"
REDIS_HIGH_RISK_IPS_SET = "high_risk_ips"

# MySQL Configuration
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "fraud_db")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))  # Default MySQL port

# Alerting Configuration
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL")

# ML Model Configuration
MODEL_PATH = os.getenv("MODEL_PATH", "ml/model.onnx")
SCALER_PATH = os.getenv("SCALER_PATH", "ml/scaler.joblib")

# Rule Engine Configuration
RULE_MAX_AMOUNT = float(os.getenv("RULE_MAX_AMOUNT", 10000.00))
RULE_MAX_TRANSACTIONS_PER_HOUR = int(os.getenv("RULE_MAX_TRANSACTIONS_PER_HOUR", 5))

# Decision Engine Configuration
ML_SCORE_THRESHOLD = float(os.getenv("ML_SCORE_THRESHOLD", 0.7))

# --- Helper Functions ---


def get_mysql_connection_config():
    """Returns MySQL connection details as a dictionary."""
    return {
        "host": MYSQL_HOST,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "database": MYSQL_DATABASE,
        "port": MYSQL_PORT,
    }


def get_redis_connection_config():
    """Returns Redis connection details as a dictionary."""
    return {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "password": REDIS_PASSWORD,
        "db": REDIS_DB,
        "decode_responses": True,  # Decode responses to strings
    }
