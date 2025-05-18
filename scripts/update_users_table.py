#!/usr/bin/env python3
# filepath: /home/arsh/Desktop/FraudDetection/scripts/update_users_table.py
import mysql.connector
import sys
import os
import logging
import bcrypt

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

def get_password_hash(password):
    """Generate a bcrypt hash for a password"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def update_users_table():
    """Add authentication columns to the users table."""
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**config.get_mysql_connection_config())
        cursor = connection.cursor()
        
        # Define all the column alterations
        alter_queries = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(255) UNIQUE AFTER user_id",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255) NULL AFTER username",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255) NULL AFTER email",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password VARCHAR(255) NULL AFTER full_name",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled BOOLEAN DEFAULT FALSE AFTER hashed_password"
        ]
        
        # Execute each query and handle errors
        for query in alter_queries:
            try:
                logger.info(f"Executing: {query}")
                cursor.execute(query)
                logger.info("Query executed successfully.")
            except mysql.connector.Error as err:
                logger.error(f"Failed to execute {query}: {err}")
                # Continue with other alterations even if one fails
        
        # Commit the changes
        connection.commit()
        logger.info("All changes committed successfully.")
        
        # Check if there are any existing sample users without usernames
        cursor.execute("SELECT user_id FROM users WHERE username IS NULL")
        users_to_update = cursor.fetchall()
        
        if users_to_update:
            # Default password for sample users (in a real system, this would be randomly generated)
            default_password = "defaultpassword123"
            default_hashed_password = get_password_hash(default_password)
            
            logger.info(f"Found {len(users_to_update)} users to update with username and password")
            
            # Update each user individually to handle different username formats
            for (user_id,) in users_to_update:
                try:
                    # Create a username based on the user_id
                    if user_id.startswith("user_"):
                        # For user IDs that already start with user_
                        username = f"user_{user_id.split('_')[1][:8]}"
                    else:
                        # For other user IDs, use a prefix
                        username = f"user_{user_id[:8]}"
                    
                    # Make sure the username is unique
                    cursor.execute("SELECT COUNT(*) FROM users WHERE username = %s", (username,))
                    count = cursor.fetchone()[0]
                    if count > 0:
                        # If username exists, add a random suffix
                        import random
                        username = f"{username}_{random.randint(100, 999)}"
                    
                    # Update the user
                    cursor.execute(
                        "UPDATE users SET username = %s, hashed_password = %s WHERE user_id = %s",
                        (username, default_hashed_password, user_id)
                    )
                    logger.info(f"Updated user {user_id} with username {username}")
                    
                except mysql.connector.Error as err:
                    logger.error(f"Failed to update user {user_id}: {err}")
            
            connection.commit()
            logger.info("All sample users updated successfully.")
            
            # Print a summary of user accounts for testing
            cursor.execute("SELECT user_id, username FROM users LIMIT 5")
            users = cursor.fetchall()
            logger.info("Sample user accounts for testing:")
            for user_id, username in users:
                logger.info(f"User ID: {user_id}, Username: {username}, Password: {default_password}")
        else:
            logger.info("No users found that need username/password updates.")
        
    except mysql.connector.Error as err:
        logger.error(f"Database error: {err}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
            logger.info("Database connection closed.")

def create_admin_user():
    """Create an admin user if it doesn't exist"""
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**config.get_mysql_connection_config())
        cursor = connection.cursor()
        
        # Check if admin user exists
        cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
        count = cursor.fetchone()[0]
        
        if count == 0:
            # Create admin user
            admin_password = "admin123"  # In production, use a secure password
            hashed_password = get_password_hash(admin_password)
            admin_id = f"admin_{int(1747592371281158)}"
            
            cursor.execute(
                """
                INSERT INTO users 
                (user_id, username, email, full_name, hashed_password, disabled, usual_location)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    admin_id,
                    "admin",
                    "admin@frauddetection.com",
                    "System Administrator",
                    hashed_password,
                    False,
                    "System Location"
                )
            )
            connection.commit()
            logger.info(f"Admin user created with username 'admin' and password '{admin_password}'")
        else:
            logger.info("Admin user already exists")
            
    except mysql.connector.Error as err:
        logger.error(f"Database error while creating admin user: {err}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

if __name__ == "__main__":
    update_users_table()
    try:
        import bcrypt
        create_admin_user()
    except ImportError:
        logger.warning("bcrypt library not installed. Skipping admin user creation.")
        logger.info("Install bcrypt with: pip install bcrypt")
