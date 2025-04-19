import mysql.connector
import sys
import os
import logging

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    import config
except ImportError:
    logging.error(
        "Failed to import config.py. Make sure it's in the project root and the Python path is correct."
    )
    sys.exit(1)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- SQL Commands ---
SQL_COMMANDS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id VARCHAR(255) PRIMARY KEY,
        usual_location VARCHAR(255) NULL, -- Allow NULL for auto-created users
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id VARCHAR(255) PRIMARY KEY,          -- Transaction ID from the source
        amount DECIMAL(10,2) NOT NULL,        -- Transaction amount
        user_id VARCHAR(255) NOT NULL,        -- User ID associated with the transaction
        timestamp DATETIME NOT NULL,          -- Timestamp of the transaction
        ip_address VARCHAR(64) NULL,          -- Hashed IP address (SHA-256)
        status ENUM('approved', 'rejected', 'error') NOT NULL, -- Final status after processing
        triggered_rules VARCHAR(255) NULL,    -- Comma-separated list of triggered rules, if any
        ml_score DECIMAL(5,4) NULL,           -- Fraud score from the ML model (e.g., 0.0000 to 1.0000)
        transaction_checksum VARCHAR(64) NULL, -- SHA-256 checksum for data integrity
        processed_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- When the decision engine processed it
        FOREIGN KEY (user_id) REFERENCES users(user_id) -- Optional: Link to users table if desired
    );
    """,
]


def setup_database():
    connection = None
    cursor = None
    try:
        db_config = config.get_mysql_connection_config()
        db_name = db_config.pop("database")

        logger.info(
            f"Connecting to MySQL server at {db_config['host']}:{db_config['port']}..."
        )
        connection = mysql.connector.connect(**db_config)
        # Use buffered cursor to automatically fetch all results
        cursor = connection.cursor(buffered=True)
        logger.info("Successfully connected to MySQL server.")

        logger.info(f"Creating database '{db_name}' if it doesn't exist...")
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
        cursor.execute(f"USE {db_name}")
        logger.info(f"Using database '{db_name}'.")

        # Execute SQL commands
        for command in SQL_COMMANDS:
            try:
                logger.info(f"Executing SQL: {command.strip().splitlines()[0]}...")
                cursor.execute(command)
                # Ensure any extra results are cleared
                while cursor.nextset():
                    pass
                logger.info("Command executed successfully.")
            except mysql.connector.Error as err:
                logger.error(f"Failed to execute SQL command: {err}")

        connection.commit()
        logger.info("Database setup completed successfully.")

    except mysql.connector.Error as err:
        logger.error(f"Database connection or setup failed: {err}")
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
            logger.info("MySQL connection closed.")


if __name__ == "__main__":
    setup_database()
