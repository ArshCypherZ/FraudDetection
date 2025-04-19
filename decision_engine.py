import redis
import mysql.connector
import json
import logging
import time
import sys
import os
import requests
from datetime import datetime
import numpy as np
import hashlib

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    import config
    from processing.preprocess import preprocess_transaction
    from processing.rule_engine import (
        apply_rules,
        get_redis_connection as get_rule_redis_connection,
    )
except ImportError as e:
    logging.error(
        f"Failed to import project modules: {e}. "
        "Ensure all files are present and PYTHONPATH is correct."
    )
    sys.exit(1)

try:
    import onnxruntime as ort
    import joblib

    ml_libs_available = True
except ImportError:
    logging.warning(
        "onnxruntime or joblib not found. " "ML model inference will be skipped/mocked."
    )
    ml_libs_available = False
    ort = None
    joblib = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("DecisionEngine")

# --- Global Variables ---
onnx_session = None
scaler = None
# Features expected by the model, matching the output of preprocess.py and train_model.ipynb
model_features = [
    "Transaction_Amount",
    "user_transaction_count_24h",
    "location_mismatch",
]

# --- Helper Functions ---


def load_model_and_scaler():
    """Loads the ONNX model and the scaler if available."""
    global onnx_session, scaler
    if not ml_libs_available:
        logger.info("ML libraries not available. Skipping model/scaler loading.")
        return

    model_path = config.MODEL_PATH
    scaler_path = config.SCALER_PATH  # Use configured scaler path

    # Load Scaler
    if os.path.exists(scaler_path):
        try:
            scaler = joblib.load(scaler_path)
            logger.info(f"Scaler loaded successfully from {scaler_path}")
        except Exception as e:
            logger.error(f"Error loading scaler from {scaler_path}: {e}")
            scaler = None  # Ensure scaler is None if loading fails
    else:
        logger.warning(
            f"Scaler file not found at {scaler_path}. ML inference will use "
            "unscaled data or fail if model expects scaling."
        )
        scaler = None

    # Load ONNX Model
    if os.path.exists(model_path):
        try:
            onnx_session = ort.InferenceSession(model_path)
            logger.info(f"ONNX model loaded successfully from {model_path}")
            # Log input/output names for debugging
            input_name = onnx_session.get_inputs()[0].name
            output_names = [output.name for output in onnx_session.get_outputs()]
            logger.info(f"Model Input: {input_name}, Model Outputs: {output_names}")
        except Exception as e:
            logger.error(f"Error loading ONNX model from {model_path}: {e}")
            onnx_session = None  # Ensure session is None if loading fails
    else:
        logger.warning(
            f"ONNX model file not found at {model_path}. "
            "ML inference will be skipped/mocked."
        )
        onnx_session = None


def get_ml_score(processed_data: dict) -> float | None:
    """
    Prepares features, scales them (if scaler loaded), and gets prediction from the ONNX model.
    Returns the fraud probability score (float) or None if model/scaler missing or error occurs.
    """
    if not onnx_session:
        logger.warning("ONNX model not loaded. Returning None for ML score.")
        return None

    try:
        feature_values = [
            processed_data.get(feature, 0.0) for feature in model_features
        ]  # Use 0.0 default for float features

        # 2. Convert to NumPy array of type float32
        # Reshape for single prediction (1 sample, N features)
        features_np = np.array(feature_values, dtype=np.float32).reshape(1, -1)
        logger.debug(f"Features for ML model (raw): {features_np}")

        # 3. Scale features if scaler is available
        if scaler:
            try:
                features_scaled = scaler.transform(features_np)
                logger.debug(f"Features for ML model (scaled): {features_scaled}")
            except Exception as e:
                logger.error(f"Error applying scaler: {e}. Using unscaled features.")
                features_scaled = features_np  # Fallback to unscaled
        else:
            logger.warning("Scaler not loaded. Using unscaled features for prediction.")
            features_scaled = features_np

        # 4. Predict using ONNX model
        input_name = onnx_session.get_inputs()[0].name
        output_name = onnx_session.get_outputs()[1].name

        result = onnx_session.run([output_name], {input_name: features_scaled})
        fraud_probability = None
        if isinstance(result[0], list) and isinstance(result[0][0], dict):
            # Probability of class '1'
            fraud_probability = result[0][0].get(1, 0.0)
        elif isinstance(result[0], np.ndarray) and result[0].shape == (1, 2):
            # Probability of the second class
            fraud_probability = result[0][0, 1]
        else:
            logger.warning(
                f"Unexpected ONNX output format: {result[0]}. "
                "Cannot extract fraud probability."
            )
            return None

        logger.info(f"ML Model Prediction (Fraud Probability): {fraud_probability:.4f}")
        return float(fraud_probability)

    except Exception as e:
        logger.exception(f"Error during ML model inference: {e}")
        return None


def store_result_in_db(
    db_conn,
    processed_data: dict,
    status: str,
    triggered_rules: list,
    ml_score: float | None,
):
    """Stores the transaction details and decision outcome in the MySQL database, including hashed IP and checksum."""
    cursor = None
    try:
        cursor = db_conn.cursor()

        # --- Hashing ---
        # 1. Hash IP Address (Privacy)
        original_ip = processed_data.get("ip_address", "")  # Get original IP
        hashed_ip = (
            hashlib.sha256(original_ip.encode("utf-8")).hexdigest()
            if original_ip
            else None
        )

        # 2. Calculate Transaction Checksum (Integrity)
        # Define fields to include in the checksum
        checksum_fields = [
            str(processed_data.get("Transaction_ID", "")),
            str(processed_data.get("Customer_ID", "")),
            str(processed_data.get("Transaction_Amount", "")),
            str(processed_data.get("location", "")),
            str(processed_data.get("description", "")),
            str(processed_data.get("timestamp_dt", "")),
        ]
        # Create a consistent string representation
        checksum_string = "|".join(checksum_fields)
        transaction_checksum = hashlib.sha256(
            checksum_string.encode("utf-8")
        ).hexdigest()

        # --- Database Insertion ---
        sql = """
            INSERT INTO transactions
            (id, amount, user_id, timestamp, ip_address, status, triggered_rules, ml_score, transaction_checksum, processed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                amount = VALUES(amount),
                user_id = VALUES(user_id),
                timestamp = VALUES(timestamp),
                ip_address = VALUES(ip_address),
                status = VALUES(status),
                triggered_rules = VALUES(triggered_rules),
                ml_score = VALUES(ml_score),
                transaction_checksum = VALUES(transaction_checksum),
                processed_at = VALUES(processed_at);
        """
        ts = processed_data.get("timestamp_dt", datetime.now())
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        rules_str = ",".join(triggered_rules) if triggered_rules else None
        score_to_store = ml_score if ml_score is not None else None

        values = (
            processed_data.get("Transaction_ID"),
            processed_data.get("Transaction_Amount"),
            processed_data.get("Customer_ID"),
            ts_str,
            hashed_ip,
            status,
            rules_str,
            score_to_store,
            transaction_checksum,
            datetime.now(),  # processed_at
        )
        cursor.execute(sql, values)
        db_conn.commit()
        logger.info(
            f"Transaction {processed_data.get('Transaction_ID')} result stored (Status: {status})."
        )
    except mysql.connector.Error as err:
        logger.error(
            f"Database error storing transaction "
            f"{processed_data.get('Transaction_ID')}: {err}"
        )
        if db_conn:
            db_conn.rollback()
    except Exception as e:
        logger.exception(
            f"Unexpected error storing result for transaction "
            f"{processed_data.get('Transaction_ID')}: {e}"
        )
        if db_conn:
            db_conn.rollback()
    finally:
        if cursor:
            cursor.close()


def send_alert(transaction_data: dict, triggered_rules: list, ml_score: float | None):
    """Sends a notification via webhook if a transaction is rejected."""
    if not config.ALERT_WEBHOOK_URL:
        logger.warning("ALERT_WEBHOOK_URL not configured. Skipping alert.")
        return

    payload = {
        "message": "Fraud Alert: Transaction Rejected",
        "transaction_id": transaction_data.get("Transaction_ID"),
        "customer_id": transaction_data.get("Customer_ID"),
        "amount": transaction_data.get("Transaction_Amount"),
        "timestamp": transaction_data.get("timestamp_dt", datetime.now()).isoformat(),
        "triggered_rules": triggered_rules,
        "ml_score": f"{ml_score:.4f}" if ml_score is not None else "N/A",
        "alert_time": datetime.now().isoformat(),
    }
    try:
        response = requests.post(config.ALERT_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(
            f"Alert sent for rejected transaction {transaction_data.get('Transaction_ID')}"
        )
    except requests.exceptions.RequestException as e:
        logger.error(
            f"Failed to send alert for transaction "
            f"{transaction_data.get('Transaction_ID')}: {e}"
        )
    except Exception as e:
        logger.exception(f"Unexpected error sending alert: {e}")


def main_loop():
    """Main loop to poll Redis, process transactions, and make decisions."""
    logger.info("Starting Decision Engine...")
    load_model_and_scaler()

    redis_conn = None
    db_conn = None

    while True:
        try:
            # Ensure connections are alive
            if redis_conn is None or not redis_conn.ping():
                logger.info("Connecting to Redis...")
                redis_conn = get_rule_redis_connection()  # Use the imported alias
                if redis_conn is None:
                    logger.error("Failed to connect to Redis. Retrying in 10s...")
                    time.sleep(10)
                    continue

            if db_conn is None or not db_conn.is_connected():
                logger.info("Connecting to MySQL...")
                db_conn = mysql.connector.connect(
                    **config.get_mysql_connection_config()
                )
                # Should raise exception, but check anyway
                if db_conn is None:
                    logger.error("Failed to connect to MySQL. Retrying in 10s...")
                    time.sleep(10)
                    continue

            logger.debug(
                f"Waiting for transaction on Redis queue '{config.REDIS_TRANSACTION_QUEUE}'..."
            )
            result = redis_conn.blpop(
                [config.REDIS_TRANSACTION_QUEUE], timeout=0
            )  # Block indefinitely

            if result:
                _queue_name, transaction_bytes = result
                start_time = time.time()
                transaction_id = "N/A"
                raw_data = {}  # Initialize raw_data

                try:
                    # Assuming decode_responses=True in Redis connection
                    raw_data = json.loads(transaction_bytes)
                    transaction_id = raw_data.get("Transaction_ID", "N/A")
                    logger.info(f"Processing transaction {transaction_id}...")

                    # 1. Preprocess Data
                    processed_data = preprocess_transaction(raw_data)
                    if not processed_data:
                        logger.error(
                            f"Preprocessing failed for transaction "
                            f"{transaction_id}. Storing error."
                        )
                        error_data = raw_data.copy()
                        # Ensure timestamp_dt
                        error_data["timestamp_dt"] = error_data.get(
                            "timestamp_dt", datetime.now()
                        )
                        # Ensure ip_address for hashing
                        error_data["ip_address"] = error_data.get("ip_address", None)
                        store_result_in_db(
                            db_conn,
                            error_data,
                            "error",
                            ["preprocessing_failed"],
                            None,
                        )
                        continue

                    # 2. Apply Rule Engine
                    triggered_rules = apply_rules(processed_data)

                    # 3. Get ML Score
                    ml_score = get_ml_score(processed_data)

                    # 4. Make Final Decision
                    is_rejected_by_rule = bool(triggered_rules)
                    is_rejected_by_ml = (
                        ml_score is not None and ml_score > config.ML_SCORE_THRESHOLD
                    )
                    status = (
                        "rejected"
                        if is_rejected_by_rule or is_rejected_by_ml
                        else "approved"
                    )

                    ml_score_str = f"{ml_score:.4f}" if ml_score is not None else "N/A"
                    log_level = (
                        logging.WARNING if status == "rejected" else logging.INFO
                    )
                    logger.log(
                        log_level,
                        f"Transaction {transaction_id} {status.upper()}. "
                        f"Rules: {triggered_rules}, ML Score: {ml_score_str}",
                    )

                    # 5. Store Result
                    store_result_in_db(
                        db_conn, processed_data, status, triggered_rules, ml_score
                    )

                    # 6. Send Alert if Rejected
                    if status == "rejected":
                        send_alert(processed_data, triggered_rules, ml_score)

                    processing_time = time.time() - start_time
                    logger.info(
                        f"Transaction {transaction_id} finished in {processing_time:.4f} seconds."
                    )

                except json.JSONDecodeError:
                    logger.error(f"Failed to decode JSON: {transaction_bytes}")
                    # Minimal data for error logging
                    error_data = {
                        "Transaction_ID": "unknown_decode_error",
                        "Customer_ID": "unknown",
                        "Transaction_Amount": 0.0,
                        "timestamp_dt": datetime.now(),
                        "ip_address": None,
                    }
                    store_result_in_db(
                        db_conn, error_data, "error", ["json_decode_error"], None
                    )
                except Exception as e:
                    logger.exception(
                        f"Error processing transaction {transaction_id}: {e}"
                    )
                    # Store 'error' status in DB using available data
                    error_data = raw_data.copy() if raw_data else {}
                    # Use ID if available
                    error_data["Transaction_ID"] = transaction_id
                    error_data.setdefault("Transaction_Amount", 0.0)
                    error_data.setdefault("Customer_ID", "unknown")
                    error_data.setdefault("timestamp_dt", datetime.now())
                    error_data.setdefault("ip_address", None)
                    store_result_in_db(
                        db_conn,
                        error_data,
                        "error",
                        ["processing_error"],
                        None,
                    )

        except redis.exceptions.ConnectionError as e:
            logger.error(f"Redis connection error: {e}. Reconnecting...")
            if redis_conn:
                try:
                    redis_conn.close()
                except Exception as close_err:  # Specify exception
                    logger.warning(
                        "Error closing potentially broken Redis connection: "
                        f"{close_err}"
                    )
            redis_conn = None
            time.sleep(5)
        except mysql.connector.Error as e:
            logger.error(f"MySQL connection error: {e}. Reconnecting...")
            if db_conn:
                try:
                    db_conn.close()
                except Exception as close_err:  # Specify exception
                    logger.warning(
                        "Error closing potentially broken MySQL connection: "
                        f"{close_err}"
                    )
            db_conn = None
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Shutdown signal received. Exiting...")
            break
        except Exception as e:
            logger.exception(f"Unexpected error in main loop: {e}. Continuing...")
            time.sleep(5)  # Prevent rapid looping

    logger.info("Closing connections...")
    if redis_conn:
        try:
            redis_conn.close()
        except Exception as e:
            logger.error(f"Error closing Redis: {e}")
    if db_conn and db_conn.is_connected():
        try:
            db_conn.close()
        except Exception as e:
            logger.error(f"Error closing MySQL: {e}")
    logger.info("Decision Engine stopped.")


if __name__ == "__main__":
    main_loop()
