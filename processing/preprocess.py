import mysql.connector
import logging
from datetime import datetime, timedelta
import mysql.connector
import logging
from datetime import datetime, timedelta

import config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Preprocessing")


def get_db_connection():
    """Establishes and returns a new MySQL database connection."""
    try:
        conn = mysql.connector.connect(**config.get_mysql_connection_config())
        logger.debug("Database connection established.")
        return conn
    except mysql.connector.Error as err:
        logger.error(f"Error connecting to database: {err}")
        return None


def get_user_location(db_conn, user_id):
    """Fetches the usual location for a given user ID."""
    cursor = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        query = "SELECT usual_location FROM users WHERE user_id = %s"
        cursor.execute(query, (user_id,))
        result = cursor.fetchone()
        if result:
            logger.debug(
                f"Usual location for user {user_id}: {result['usual_location']}"
            )
            return result["usual_location"]
        else:
            logger.warning(f"User ID {user_id} not found.")
            return None
    except mysql.connector.Error as err:
        logger.error(f"DB error fetching location for {user_id}: {err}")
        return None
    finally:
        if cursor:
            cursor.close()


def get_transaction_count_24h(db_conn, user_id, transaction_timestamp):
    """Counts transactions for the user in the 24 hours prior."""
    cursor = None
    try:
        cursor = db_conn.cursor()
        time_window_start = transaction_timestamp - timedelta(hours=24)
        ts_start_str = time_window_start.strftime("%Y-%m-%d %H:%M:%S")
        ts_end_str = transaction_timestamp.strftime("%Y-%m-%d %H:%M:%S")

        query = """
            SELECT COUNT(*) FROM transactions
            WHERE user_id = %s AND timestamp >= %s AND timestamp < %s
        """
        cursor.execute(query, (user_id, ts_start_str, ts_end_str))
        count = cursor.fetchone()[0]
        logger.debug(f"User {user_id} transaction count (last 24h): {count}")
        return count
    except mysql.connector.Error as err:
        logger.error(f"DB error counting transactions for {user_id}: {err}")
        return 0  # Default to 0 on error
    finally:
        if cursor:
            cursor.close()


def create_user(db_conn, user_id):
    """Creates a new user entry with NULL location."""
    cursor = None
    try:
        cursor = db_conn.cursor()
        query = "INSERT INTO users (user_id, usual_location) VALUES (%s, NULL)"
        cursor.execute(query, (user_id,))
        db_conn.commit()
        logger.info(f"Created new user entry for ID: {user_id}")
        return True
    except mysql.connector.Error as err:
        logger.error(f"DB error creating user {user_id}: {err}")
        db_conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()


def preprocess_transaction(raw_data: dict) -> dict | None:
    """
    Cleans raw transaction data and calculates features.
    Returns a dictionary with processed data or None on critical failure.
    """
    transaction_id = raw_data.get("transaction_id", "N/A")
    logger.info(f"Preprocessing transaction {transaction_id}")
    db_conn = None
    processed_data = {}

    try:
        db_conn = get_db_connection()
        if not db_conn:
            logger.error(
                f"Failed to get DB connection for transaction {transaction_id}."
            )
            return None

        # Extract and clean basic fields
        processed_data["Transaction_ID"] = transaction_id
        processed_data["Customer_ID"] = raw_data.get("user_id")
        processed_data["Transaction_Amount"] = float(raw_data.get("amount", 0.0))
        processed_data["location"] = raw_data.get("location")
        processed_data["description"] = raw_data.get("description")
        processed_data["ip_address"] = raw_data.get("ip_address")

        # Parse timestamp
        timestamp_str = raw_data.get("timestamp")
        try:
            processed_data["timestamp_dt"] = datetime.fromisoformat(
                timestamp_str.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            logger.warning(
                f"Could not parse timestamp '{timestamp_str}' for {transaction_id}. Using current time."
            )
            processed_data["timestamp_dt"] = datetime.now()

        # Calculate features requiring DB lookups
        user_id = processed_data["Customer_ID"]
        transaction_location = processed_data["location"]
        usual_location = None
        user_exists = False

        if user_id:
            usual_location = get_user_location(db_conn, user_id)
            if usual_location is not None:
                user_exists = True
            else:
                # User not found, try creating them
                if create_user(db_conn, user_id):
                    user_exists = True  # User now exists (with NULL location)
                # else: Error logged in create_user

            # Calculate location mismatch
            if user_exists and transaction_location and usual_location:
                processed_data["location_mismatch"] = (
                    transaction_location != usual_location
                )
            else:
                processed_data["location_mismatch"] = (
                    False  # Default if comparison not possible
                )

            # Calculate transaction count
            processed_data["user_transaction_count_24h"] = get_transaction_count_24h(
                db_conn, user_id, processed_data["timestamp_dt"]
            )
        else:
            # No user_id provided
            logger.warning(
                f"Missing user_id for transaction {transaction_id}. Features requiring user_id will be defaulted."
            )
            processed_data["location_mismatch"] = False
            processed_data["user_transaction_count_24h"] = 0

        # Ensure required features have default values if calculation failed
        processed_data.setdefault("location_mismatch", False)
        processed_data.setdefault("user_transaction_count_24h", 0)

        logger.info(f"Preprocessing complete for {transaction_id}.")
        return processed_data

    except Exception as e:
        logger.exception(
            f"Unexpected error during preprocessing transaction {transaction_id}: {e}"
        )
        return None
    finally:
        if db_conn and db_conn.is_connected():
            try:
                db_conn.close()
                logger.debug(
                    f"Database connection closed for transaction {transaction_id}."
                )
            except mysql.connector.Error as err:
                logger.error(
                    f"Error closing database connection for {transaction_id}: {err}"
                )
