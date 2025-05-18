import time
import hashlib
import sys
import os
import numpy as np
from datetime import datetime
import logging
import mysql.connector

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import global config
import config

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

async def enhanced_check_transaction(transaction, logger, user_id=None):
    """
    Production-ready enhanced transaction checking that combines:
    1. Rule-based checks
    2. ML model prediction
    
    Returns a comprehensive fraud detection assessment.
    
    Parameters:
    - transaction: The transaction to check
    - logger: Logger instance
    - user_id: The ID of the user performing the transaction (from authentication)
    """
    try:
        # Import ML and processing components
        try:
            import onnxruntime as ort
            import joblib
            from processing.rule_engine import apply_rules, check_high_amount, check_suspicious_description
            ml_available = True
        except ImportError as e:
            logger.warning(f"Import error: {e}. Falling back to rule-based approach.")
            ml_available = False
            
        # Generate a transaction ID
        transaction_id = f"TX{int(time.time() * 1000)}"
        current_time = datetime.now()
        
        # Create a transaction object
        tx = {
            "transaction_id": transaction_id,
            "user_id": user_id,  # Use the authenticated user's ID
            "amount": transaction.amount,
            "description": transaction.description or "",
            "location": transaction.location or "Unknown",
            "ip_address": transaction.ip_address or "127.0.0.1",
            "timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_dt": current_time
        }
        
        # Track processing details for audit trail
        processing_details = {
            "start_time": time.time(),
            "methods_used": [],
            "decision_factors": [],
        }
        
        # 1. Apply basic rules
        triggered_rules = []
        
        # Check for high amount
        if check_high_amount(transaction.amount):
            triggered_rules.append("high_amount")
            
        # Check for suspicious description
        if transaction.description and check_suspicious_description(transaction.description):
            triggered_rules.append("suspicious_description")
            
        if triggered_rules:
            processing_details["methods_used"].append("rule_engine")
            processing_details["decision_factors"].append(f"Triggered rules: {', '.join(triggered_rules)}")
        
        # 2. ML Scoring if available
        ml_score = 0.0
        if ml_available:
            try:
                processing_details["methods_used"].append("ml_model")
                # Load ONNX model and scaler
                model_path = config.MODEL_PATH
                scaler_path = config.SCALER_PATH
                
                # Only load if not already loaded
                try:
                    onnx_session = ort.InferenceSession(model_path)
                    scaler = joblib.load(scaler_path)
                
                    # Prepare features for model
                    features = {
                        "Transaction_Amount": transaction.amount,
                        "user_transaction_count_24h": 0,  # Default value
                        "location_mismatch": 0  # Default value
                    }
                    
                    # Connect to the database to get user data and transaction history
                    conn = connect_to_mysql()
                    if conn:
                        try:
                            cursor = conn.cursor(dictionary=True)
                            
                            # If we have a user ID, get their transaction history
                            if user_id:
                                # Get transaction count for the last 24 hours
                                time_window_start = current_time - datetime.timedelta(hours=24)
                                ts_start_str = time_window_start.strftime("%Y-%m-%d %H:%M:%S")
                                ts_end_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
                                
                                query = """
                                    SELECT COUNT(*) as count FROM transactions
                                    WHERE user_id = %s AND timestamp >= %s AND timestamp < %s
                                """
                                cursor.execute(query, (user_id, ts_start_str, ts_end_str))
                                result = cursor.fetchone()
                                if result:
                                    features["user_transaction_count_24h"] = result["count"]
                                    processing_details["decision_factors"].append(
                                        f"User transaction count (24h): {result['count']}"
                                    )
                            
                            # Check location mismatch
                            if transaction.location:
                                user_query = "SELECT usual_location FROM users WHERE user_id = %s"
                                user_id_to_check = user_id if user_id else "guest_user"
                                cursor.execute(user_query, (user_id_to_check,))
                                user_data = cursor.fetchone()
                                if user_data and user_data["usual_location"] and user_data["usual_location"] != "Unknown":
                                    features["location_mismatch"] = 1 if transaction.location != user_data["usual_location"] else 0
                                    processing_details["decision_factors"].append(
                                        f"Location mismatch: {'Yes' if features['location_mismatch'] else 'No'}"
                                    )
                                    
                        except mysql.connector.Error as err:
                            logger.error(f"DB error getting user data: {err}")
                        finally:
                            cursor.close()
                            conn.close()
                    
                    # Format features for model
                    feature_array = np.array([[
                        features["Transaction_Amount"], 
                        features["user_transaction_count_24h"],
                        features["location_mismatch"]
                    ]]).astype(np.float32)
                    
                    # Scale features
                    scaled_features = scaler.transform(feature_array)
                    
                    # Run inference
                    input_name = onnx_session.get_inputs()[0].name
                    outputs = onnx_session.run(None, {input_name: scaled_features})
                    
                    # Extract probability score
                    if len(outputs) > 1:
                        ml_score = outputs[1][0][1]  # Probability of fraud (class 1)
                    else:
                        # If only one output, use the predicted class (0 or 1)
                        ml_score = float(outputs[0][0])
                    
                    processing_details["decision_factors"].append(f"ML score: {ml_score:.4f}")
                    
                except Exception as e:
                    logger.error(f"ML model inference failed: {e}")
                    ml_score = 0.0
            except Exception as e:
                logger.error(f"Error during ML scoring: {e}")
                ml_score = 0.0
        
        # Initialize variables 
        api_fraud_detected = False
        api_score = 0.0
        api_reason = None
        
        # 4. Make final decision - weighted ensemble of ML model and rules
        ml_weight = 0.6
        rules_weight = 0.4
        
        # Calculate weighted fraud score
        weighted_score = 0.0
        methods_used = len(processing_details["methods_used"])
        
        if "ml_model" in processing_details["methods_used"]:
            weighted_score += ml_weight * ml_score
            
        if "rule_engine" in processing_details["methods_used"]:
            rule_score = min(1.0, len(triggered_rules) * 0.5)  # Each rule contributes 0.5 to score, capped at 1.0
            weighted_score += rules_weight * rule_score
            
        # Normalize score if not all methods were used
        if methods_used > 0:
            used_weights = 0
            if "ml_model" in processing_details["methods_used"]: used_weights += ml_weight
            if "rule_engine" in processing_details["methods_used"]: used_weights += rules_weight
            
            if used_weights > 0:
                weighted_score = weighted_score / used_weights
                
        # Decision based on weighted score or any hard rules
        is_fraudulent = (weighted_score > 0.6) or (ml_score > config.ML_SCORE_THRESHOLD) or (len(triggered_rules) > 0)
        status = "Fraudulent" if is_fraudulent else "Safe"
        
        # 5. Calculate risk score for UI (0-100 scale)
        scaled_risk_score = int(min(weighted_score * 100, 100))
        
        # 6. Store in database
        conn = connect_to_mysql()
        if conn:
            cursor = conn.cursor()
            
            # First check if user exists, if not create one
            cursor.execute("SELECT user_id FROM users WHERE user_id = %s", ("guest_user",))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (user_id, usual_location) VALUES (%s, %s)",
                    ("guest_user", "Unknown")
                )
            
            # Hash IP address for privacy
            ip_hash = hashlib.sha256(tx["ip_address"].encode()).hexdigest() if tx["ip_address"] else None
            
            # Calculate transaction checksum for integrity
            checksum_data = f"{transaction_id}|{user_id}|{transaction.amount}|{tx['location']}|{tx['description']}|{tx['timestamp']}"
            transaction_checksum = hashlib.sha256(checksum_data.encode()).hexdigest()
            
            # Insert transaction with all scoring data
            # Add debugging output
            print(f"DEBUG: Saving transaction {transaction_id} for user_id: {user_id}")
            
            # Make sure user_id is included in the INSERT statement
            cursor.execute(
                """
                INSERT INTO transactions (id, amount, timestamp, status, description, location, ip_address, user_id) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    transaction_id,
                    transaction.amount,
                    tx["timestamp"],
                    status,
                    tx["description"],
                    tx["location"],
                    tx["ip_address"],
                    user_id  # Make sure user_id is used here and not hard-coded to something else
                )
            )
            
            # Update daily metrics
            today = current_time.strftime("%Y-%m-%d")
            cursor.execute(
                """
                INSERT INTO daily_metrics (date, total_transactions, fraud_attempts, risk_score) 
                VALUES (%s, 1, %s, %s)
                ON DUPLICATE KEY UPDATE 
                total_transactions = total_transactions + 1,
                fraud_attempts = fraud_attempts + %s,
                risk_score = (risk_score * total_transactions + %s) / (total_transactions + 1)
                """,
                (
                    today, 
                    1 if is_fraudulent else 0, 
                    scaled_risk_score,
                    1 if is_fraudulent else 0,
                    scaled_risk_score
                )
            )
            
            conn.commit()
            conn.close()
        
        # Calculate processing time
        processing_time = time.time() - processing_details["start_time"]
        
        # 7. Return comprehensive response
        return {
            "transaction_id": transaction_id,
            "status": status,
            "risk_score": scaled_risk_score,
            "ml_score": float(ml_score),
            "triggered_rules": triggered_rules,
            "processing_time_ms": int(processing_time * 1000),
            "methods_used": processing_details["methods_used"]
        }
        
    except Exception as e:
        logger.exception(f"Error in enhanced transaction check: {e}")
        raise e
