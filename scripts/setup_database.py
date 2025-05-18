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
        username VARCHAR(255) UNIQUE, -- Username for authentication
        email VARCHAR(255) NULL, -- Optional email for user contact
        full_name VARCHAR(255) NULL, -- Optional full name
        hashed_password VARCHAR(255) NULL, -- Bcrypt hashed password
        disabled BOOLEAN DEFAULT FALSE, -- Account status flag
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
        status ENUM('approved', 'rejected', 'error', 'Safe', 'Fraudulent') NOT NULL, -- Final status after processing
        description TEXT NULL,                -- Description of the transaction
        location VARCHAR(255) NULL,           -- Location where the transaction was made
        triggered_rules VARCHAR(255) NULL,    -- Comma-separated list of triggered rules, if any
        ml_score DECIMAL(5,4) NULL,           -- Fraud score from the ML model (e.g., 0.0000 to 1.0000)
        api_results TEXT NULL,                -- Results from external fraud detection API
        transaction_checksum VARCHAR(64) NULL, -- SHA-256 checksum for data integrity
        processed_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- When the decision engine processed it
        FOREIGN KEY (user_id) REFERENCES users(user_id) -- Optional: Link to users table if desired
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_metrics (
        date DATE PRIMARY KEY,
        total_transactions INT DEFAULT 0,
        fraud_attempts INT DEFAULT 0,
        risk_score DECIMAL(5,2) DEFAULT 0.0
    );
    """,
]

# Sample data for daily metrics - matching the frontend chart
SAMPLE_DATA_SQL = """
INSERT INTO daily_metrics (date, total_transactions, fraud_attempts, risk_score)
VALUES 
    (DATE_SUB(CURDATE(), INTERVAL 7 DAY), 120, 5, 12),
    (DATE_SUB(CURDATE(), INTERVAL 6 DAY), 132, 3, 8),
    (DATE_SUB(CURDATE(), INTERVAL 5 DAY), 101, 2, 5),
    (DATE_SUB(CURDATE(), INTERVAL 4 DAY), 134, 8, 17),
    (DATE_SUB(CURDATE(), INTERVAL 3 DAY), 90, 4, 10),
    (DATE_SUB(CURDATE(), INTERVAL 2 DAY), 230, 7, 15),
    (DATE_SUB(CURDATE(), INTERVAL 1 DAY), 210, 3, 8)
ON DUPLICATE KEY UPDATE
    total_transactions = VALUES(total_transactions),
    fraud_attempts = VALUES(fraud_attempts),
    risk_score = VALUES(risk_score);
"""

# Sample users data
SAMPLE_USERS_SQL = """
INSERT INTO users (user_id, usual_location) 
VALUES 
    ('user123', 'New York, USA'),
    ('user456', 'Los Angeles, USA'),
    ('user789', 'Chicago, USA'),
    ('guest_user', 'Unknown')
ON DUPLICATE KEY UPDATE usual_location = VALUES(usual_location);
"""


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
                
        # Add sample users first
        try:
            logger.info("Adding sample users...")
            cursor.execute(SAMPLE_USERS_SQL)
            logger.info("Sample users added successfully.")
        except mysql.connector.Error as err:
            logger.error(f"Failed to add sample users: {err}")
                
        # Add sample data for daily metrics chart
        try:
            logger.info("Adding sample data for daily metrics...")
            cursor.execute(SAMPLE_DATA_SQL)
            logger.info("Sample data added successfully.")
        except mysql.connector.Error as err:
            logger.error(f"Failed to add sample data: {err}")
            
        # Add sample transaction data if specific sample entries are missing
        try:
            logger.info("Checking for sample transaction data...")
            # Sample transaction IDs we want to ensure are present
            sample_transaction_ids = ['TX78965412', 'TX45632178', 'TX12398745', 'TX36987452', 'TX65478932']
            
            # First check which sample IDs are already in the database
            sample_ids_string = "', '".join(sample_transaction_ids)
            cursor.execute(f"SELECT id FROM transactions WHERE id IN ('{sample_ids_string}')")
            existing_ids = [row[0] for row in cursor.fetchall()]
            
            # Calculate which sample IDs need to be added
            missing_ids = set(sample_transaction_ids) - set(existing_ids)
            
            # If any sample data is missing, add only the missing entries
            if missing_ids:
                logger.info(f"Adding missing sample transaction data: {missing_ids}")
                # Full sample data set
                all_sample_data = [
                    ('TX78965412', 'user123', 1245.00, '2025-04-20 08:23:15', '192.168.1.1', 'Safe', 'Online purchase', 'New York, USA', '', 0.2),
                    ('TX45632178', 'user456', 3890.50, '2025-04-19 15:47:32', '203.0.113.1', 'Fraudulent', 'Electronics purchase', 'Unknown Location', 'rule_large_amount', 0.9),
                    ('TX12398745', 'user789', 750.25, '2025-04-18 11:05:47', '198.51.100.1', 'Safe', 'Grocery shopping', 'Chicago, USA', '', 0.1),
                    ('TX36987452', 'user123', 2100.00, '2025-04-17 19:32:10', '192.168.1.1', 'Safe', 'Hotel booking', 'New York, USA', '', 0.3),
                    ('TX65478932', 'user456', 5430.75, '2025-04-17 14:15:38', '203.0.113.1', 'Fraudulent', 'International transfer', 'Unknown Location', 'rule_suspicious_ip', 0.85)
                ]
                
                # Filter to only include the missing data
                data_to_add = [data for data in all_sample_data if data[0] in missing_ids]
                
                # Insert the missing sample data
                cursor.executemany("""
                INSERT INTO transactions 
                (id, user_id, amount, timestamp, ip_address, status, description, location, triggered_rules, ml_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, data_to_add)
                
                logger.info(f"Added {len(data_to_add)} missing sample transaction entries")
            else:
                logger.info("All sample transaction data already exists - no need to add")
        except mysql.connector.Error as err:
            logger.error(f"Failed to check/add sample transaction data: {err}")

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
