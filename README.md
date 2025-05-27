# AI-Driven Fraud Detection System

This project implements a comprehensive fraud detection system with user authentication. It combines algorithms, rule-based checks and machine learning models to identify potentially fraudulent transactions in real-time. The system includes both frontend and backend components with a full dashboard for monitoring transaction statistics and history.

## Key Features

- **User Authentication**: Secure JWT-based authentication system with user registration and login
- **Multi-layered Fraud Detection**:
  - Rule-based checks with configurable thresholds
  - Machine learning models (ONNX format) for fraud prediction
- **Interactive Dashboard**:
  - Real-time statistics on transactions and fraud attempts
  - Transaction history with filtering and status-based views
  - Risk analysis charts and visualizations
  - Success rate and fraud prevention metrics
- **Transaction Analysis**:
  - Location verification for suspicious activity detection (with geolocation dialog)
  - IP address tracking with privacy considerations
  - Description analysis for suspicious keywords
  - User-specific transaction pattern analysis
- **Data Export**: Export transaction data in CSV, Excel, and PDF formats with date range and status filters
- **Recent History**: View recent transactions with detailed tooltips (triggered rules, risk score, ML confidence)
- **Session Management**: Persistent login, logout, and automatic dashboard refresh every 30 seconds
- **API Documentation**: Comprehensive FastAPI documentation
- **Frontend Enhancements**: Responsive UI, notification system, and local caching for transaction data
- **LLM Integration (Gemini API)**: Optional integration with Google Gemini for advanced language-based fraud detection (requires `GEMINI_API_KEY` and `USE_LLM_DETECTION` in `.env`).

## How the System Works

This section describes the typical flow of a transaction through the fraud detection system:

1.  **User Authentication**: Users register and login to the system using JWT-based authentication to secure access to the API.

2.  **Transaction Ingestion**: The FastAPI server (`api/main.py`) receives transaction details via a POST request to the `/check-transaction` endpoint, requiring user authentication.

3.  **Enhanced Fraud Detection**: The system uses `api/enhanced_check.py` to analyze the transaction with multiple methods:
    * **Rule-based checks**: Applies configurable rules to detect suspicious patterns
    * **ML model prediction**: Uses ONNX models for efficient fraud scoring
    * **User-specific analysis**: Checks against known user patterns and locations

4.  **Decision Process**:
    * Each detection method produces a risk score or triggered rules
    * The system combines these results using a weighted approach
    * A final "Safe" or "Fraudulent" decision is made based on combined risk

5.  **Result Storage**: Transaction details, decision, risk scores, and any triggered rules are stored in the MySQL database, associated with the authenticated user.

6.  **Dashboard Display**: Results are available on the frontend dashboard, showing transaction history, statistics, and risk analysis.

## Hashing Usage

Hashing algorithms are employed in the Decision Engine (`decision_engine.py`) for specific purposes:

*   **IP Address Hashing (SHA-256)**: To enhance user privacy, the original IP address associated with a transaction is hashed using SHA-256 before being stored in the `transactions` table in the MySQL database. This allows for potential analysis related to IPs without storing the raw, potentially sensitive, IP address directly.
*   **Transaction Checksum (SHA-256)**: A checksum is calculated using SHA-256 based on a concatenated string of key transaction fields (ID, user ID, amount, location, description, timestamp). This checksum is stored alongside the transaction record in the database. It serves as a data integrity check, allowing verification that the core transaction data hasn't been unintentionally altered during processing or storage.

## Algorithm Usage

*   **Rabin-Karp Algorithm**: Implemented in `processing/rule_engine.py`, the Rabin-Karp algorithm is used within the `check_suspicious_description` function. Its purpose is to efficiently search the transaction `description` field for occurrences of predefined suspicious keywords or phrases (e.g., "urgent payment required", "account verification"). This string-searching algorithm uses hashing to quickly find potential matches, making the rule evaluation process more performant than simple substring checks, especially with longer descriptions or more patterns.

## System Architecture

The Fraud Detection system follows a modern architecture pattern that separates concerns:

- **Frontend**: A responsive web interface built with HTML, JavaScript, and Tailwind CSS
- **Backend API**: FastAPI-based RESTful API with JWT authentication
- **Database**: MySQL database for storing users, transactions, and metrics
- **Caching**: Redis for high-performance caching and message queuing
- **ML Pipeline**: ONNX model integration for efficient inference

## File Structure

```
FraudDetection/
├── api/
│   ├── auth.py              # User authentication system with JWT
│   ├── enhanced_check.py    # Advanced fraud detection logic
│   └── main.py              # FastAPI server with endpoints
├── frontend/
│   └── frontend.html        # Web dashboard for monitoring and analysis
├── processing/
│   ├── preprocess.py        # Data cleaning & feature engineering
│   ├── rule_engine.py       # Rule-based checks & pattern matching
│   └── suspicious_keywords.txt # Database of suspicious terms
├── ml/
│   ├── train_model.ipynb    # Model training notebook
│   ├── model.onnx           # Exported ML model (generated by notebook)
│   └── scaler.joblib        # Exported feature scaler (generated by notebook)
├── scripts/
│   ├── load_risky_ips.py    # Helper script to load IPs to Redis
│   ├── setup_database.py    # Database initialization script
│   └── update_users_table.py # User table management script
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
# REDIS_PASSWORD = 
# REDIS_USERNAME=
# MYSQL_HOST=localhost
# MYSQL_USER=your_mysql_user         # REQUIRED - No default value
# MYSQL_PASSWORD=your_mysql_password # REQUIRED - No default value
# MYSQL_DATABASE=fraud_db
# ALERT_WEBHOOK_URL=https://your-webhook-receiver.com/alert # Optional
# JWT_SECRET_KEY=your_secure_secret_key # Secret key for JWT token generation
#
# # Optional - ML/Rule Configuration (Defaults are in config.py if not set here)
# MODEL_PATH=ml/model.onnx
# SCALER_PATH=ml/scaler.joblib
# RULE_MAX_AMOUNT=1000.00
# RULE_MAX_TRANSACTIONS_PER_HOUR=5
# ML_SCORE_THRESHOLD=0.7
#
# # Optional - LLM Integration (Gemini API)
# GEMINI_API_KEY=your_gemini_api_key   # Gemini API key for LLM integration
# USE_LLM_DETECTION=true                 # Enable LLM-based detection (default: true)
# --- end .env file ---

# 4. Initialize the database
python scripts/setup_database.py

# 5. Update user table schema (for authentication)
python scripts/update_users_table.py

# 6. Run the API server
uvicorn api.main:app --reload

# 7. Access the frontend
# Open frontend/frontend.html in your web browser
# Or run a simple HTTP server:
python -m http.server 8080
```

## API Endpoints

The system provides the following key API endpoints:

### Authentication Endpoints
- `POST /register` - Register a new user
- `POST /token` - Log in and get an access token
- `GET /users/me` - Get current user profile

### Transaction Endpoints
- `POST /check-transaction` - Check a transaction for fraud (authenticated)
- `POST /transaction` - Queue a transaction for processing (authenticated)
- `GET /api/transactions` - Get transaction history for the current user (authenticated)

### Dashboard Endpoints
- `GET /api/statistics` - Get overall fraud statistics
- `GET /api/risk-analysis` - Get risk analysis data for charts
- `POST /api/export` - Export transaction data in different formats

### System Endpoints
- `GET /health` - Check system health (Redis, MySQL connections)
- `GET /docs` - Interactive API documentation (Swagger UI)

## Environment Variables

The following environment variables are supported (see `.env`):
- `GEMINI_API_KEY`: API key for Gemini LLM (optional, enables LLM-based detection)
- `USE_LLM_DETECTION`: Set to `true` to enable LLM-based detection (default: true)
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_USERNAME`: Redis connection
- `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`: MySQL connection
- `ALERT_WEBHOOK_URL`: Webhook for fraud alerts (optional)
- `JWT_SECRET_KEY`: Secret for JWT authentication
- `MODEL_PATH`, `SCALER_PATH`: ML model/scaler paths (optional)
- `RULE_MAX_AMOUNT`, `RULE_MAX_TRANSACTIONS_PER_HOUR`, `ML_SCORE_THRESHOLD`: Rule/ML config (optional)

## Security Considerations

The system implements several security measures:

- **Authentication**: JWT tokens with expiration for secure API access
- **Password Security**: Bcrypt hashing for storing user passwords
- **Data Privacy**: Hashing of sensitive information like IP addresses
- **Transaction Integrity**: Checksums to verify transaction data hasn't been altered

## Database Schema

The system uses a MySQL database with the following key tables:

### Users Table
- `user_id` (VARCHAR): Primary key for user identification
- `username` (VARCHAR): Unique username for authentication
- `email` (VARCHAR): Optional email address
- `full_name` (VARCHAR): Optional user's full name
- `hashed_password` (VARCHAR): Bcrypt-hashed password
- `disabled` (BOOLEAN): Account status flag
- `usual_location` (VARCHAR): User's typical location for comparison

### Transactions Table
- `id` (VARCHAR): Transaction identifier
- `user_id` (VARCHAR): Foreign key to users table
- `amount` (DECIMAL): Transaction amount
- `timestamp` (DATETIME): When the transaction occurred
- `ip_address` (VARCHAR): Hashed IP for privacy
- `status` (ENUM): Transaction status (Safe/Fraudulent)
- `description` (TEXT): Transaction details
- `location` (VARCHAR): Geographic location
- `triggered_rules` (VARCHAR): Any fraud rules that were triggered
- `ml_score` (DECIMAL): ML model fraud probability
- `transaction_checksum` (VARCHAR): Data integrity verification

### Daily Metrics Table
- `date` (DATE): Date of metrics
- `total_transactions` (INT): Count of transactions
- `fraud_attempts` (INT): Count of fraudulent transactions
- `risk_score` (DECIMAL): Overall risk score for the day

## Conclusion

This fraud detection system provides a comprehensive solution for transaction monitoring and fraud prevention. With its multi-layered approach combining rule-based checks, machine learning, it offers robust protection against various fraud patterns. The addition of user authentication ensures that the system can be securely deployed in production environments.

The system is designed to be scalable and maintainable, with clear separation of concerns between components. It can be extended with additional detection methods, dashboard features, or integrations as needed.
