import redis
import logging
import os
from datetime import datetime, timedelta
import redis
import logging
import json
import asyncio
from typing import Optional

import config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_redis_connection():
    """Establishes a Redis connection."""
    try:
        r = redis.Redis(**config.get_redis_connection_config())
        r.ping()
        logger.debug("Redis connection successful for Rule Engine.")
        return r
    except redis.exceptions.ConnectionError as e:
        logger.error(f"Error connecting to Redis for Rule Engine: {e}")
        return None


# Rabin-Karp Implementation Constants
D_RK = 256  # Number of characters in the input alphabet (ASCII)
Q_RK = 101  # A prime number for modulo operation


def check_category_based_amount(amount: float | None, description: str) -> tuple[bool, str]:
    """
    Uses Gemini LLM to determine if the amount is unusually high for the given description.
    Returns (is_suspicious, reason).
    """
    import time
    import math
    if amount is None or description is None or str(description).strip() == "":
        return False, "No amount or description provided"
    # Handle edge cases for amount
    if not isinstance(amount, (int, float)) or math.isnan(amount) or math.isinf(amount) or amount < 0 or amount > 1e8:
        return False, "Invalid or extreme amount value"
    if not config.USE_LLM_DETECTION or not config.GEMINI_API_KEY:
        return False, "LLM detection disabled"
    try:
        time.sleep(1)
        import google.generativeai as genai
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel(config.GEMINI_MODEL)
        prompt = f"""You are an expert financial fraud detection system. Your job is to decide if a transaction amount is suspiciously high for the described purchase or service. Use your knowledge of typical prices and context. Be strict for obvious mismatches, but do NOT flag reasonable or common transactions as fraud. Only flag as suspicious if the amount is clearly excessive for the description.
        Transaction Amount: {amount} USD
        Description: {description}

        IMPORTANT: Some items or services can be legitimately very expensive (e.g., high-end laptops, professional equipment, luxury goods, or business purchases). Do NOT flag these as suspicious if the amount is plausible for such cases, even if the number is high.

        Instructions:
        - If the amount is normal or plausible for the description, return is_suspicious: false.
        - If the amount is clearly excessive or implausible for the description, return is_suspicious: true.
        - If unsure, err on the side of not flagging as suspicious.

        Respond in JSON:
        {{
        "is_suspicious": true/false,
        "reason": "brief explanation"
        }}"""

        response = model.generate_content(prompt)
        if not response or not response.text:
            logger.error("LLM response is empty or invalid.")
            return False, "LLM response error"
        response_text = (response.text).replace("```json", "").replace("```", "").strip()
        try:
            result = json.loads(response_text)
        except Exception:
            # Try to extract JSON from text
            import re
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group(0))
                except Exception:
                    logger.error(f"LLM response could not be parsed: {response_text}")
                    return False, "LLM response parse error"
            else:
                logger.error(f"LLM response could not be parsed: {response_text}")
                return False, "LLM response parse error"
        return result.get('is_suspicious', False), result.get('reason', '')
    except Exception as e:
        logger.error(f"LLM category-based amount detection error: {e}")
        return False, f"LLM error: {str(e)}"


def search_rabin_karp(pattern: str, text: str) -> bool:
    """Searches for a pattern within text using the Rabin-Karp algorithm."""
    if not pattern or not text:
        return False
    M = len(pattern)
    N = len(text)
    if M > N:
        return False

    p_hash = 0  # hash value for pattern
    t_hash = 0  # hash value for text window
    h = pow(D_RK, M - 1, Q_RK)  # pow(D_RK, M-1) % Q_RK

    # Calculate initial hash values
    for i in range(M):
        p_hash = (D_RK * p_hash + ord(pattern[i])) % Q_RK
        t_hash = (D_RK * t_hash + ord(text[i])) % Q_RK

    # Slide the pattern over text
    for i in range(N - M + 1):
        # Check hash values. If match, verify character by character.
        if p_hash == t_hash:
            if text[i : i + M] == pattern:
                logger.debug(f"Rabin-Karp: Pattern '{pattern}' found.")
                return True

        # Calculate hash value for the next window
        if i < N - M:
            t_hash = (D_RK * (t_hash - ord(text[i]) * h) + ord(text[i + M])) % Q_RK
            # Ensure t_hash remains positive
            if t_hash < 0:
                t_hash += Q_RK

    logger.debug(f"Rabin-Karp: Pattern '{pattern}' not found.")
    return False


def check_high_amount(amount: float | None) -> bool:
    """Checks if the transaction amount exceeds the configured threshold."""
    if amount is None:
        return False
    is_high = amount > config.RULE_MAX_AMOUNT
    if is_high:
        logger.warning(
            f"Rule Triggered: High amount ({amount} > {config.RULE_MAX_AMOUNT})"
        )
    return is_high


def check_high_frequency(
    customer_id: str, transaction_timestamp: datetime, redis_conn
) -> bool:
    """Checks transaction frequency using Redis sorted sets (last hour)."""
    if not redis_conn or not customer_id:
        return False

    try:
        now_unix = transaction_timestamp.timestamp()
        one_hour_ago_unix = (transaction_timestamp - timedelta(hours=1)).timestamp()
        key = f"cust_freq:{customer_id}"
        member = f"{now_unix}:{transaction_timestamp.microsecond}"  # Unique member ID

        # Pipeline for atomic operations
        pipe = redis_conn.pipeline()
        pipe.zadd(key, {member: now_unix})  # Add current transaction
        pipe.zremrangebyscore(key, "-inf", one_hour_ago_unix)  # Remove old entries
        pipe.zcard(key)  # Count remaining entries
        pipe.expire(key, 7200)  # Set key expiry (2 hours)
        results = pipe.execute()

        count = results[2]  # Result of zcard
        logger.debug(f"Customer {customer_id} transaction count (last hour): {count}")

        is_frequent = count > config.RULE_MAX_TRANSACTIONS_PER_HOUR
        if is_frequent:
            logger.warning(
                f"Rule Triggered: High frequency for customer {customer_id} ({count} transactions/hour)"
            )
        return is_frequent

    except redis.exceptions.RedisError as e:
        logger.error(f"Redis error checking frequency for {customer_id}: {e}")
        return False  # Fail safe


def check_suspicious_description(description: str) -> bool:
    """
    Checks if the transaction description contains suspicious keywords.
    Uses Rabin-Karp string matching for efficiency.
    """
    if not description:
        return False

    # Normalize description text for matching
    desc_lower = description.lower()

    # Get suspicious keywords from file
    keywords = []
    try:
        keywords_file = os.path.join(os.path.dirname(__file__), "suspicious_keywords.txt")
        if os.path.exists(keywords_file):
            with open(keywords_file, "r") as f:
                keywords = [line.strip().lower() for line in f if line.strip()]
    except Exception as e:
        logger.error(f"Error loading suspicious keywords: {e}")
        keywords = ["bitcoin", "urgent", "money transfer", "gift card", "lottery"]

    # Check for suspicious keywords using Rabin-Karp
    for keyword in keywords:
        if search_rabin_karp(keyword, desc_lower):
            logger.warning(f"Rule Triggered: Suspicious description (keyword: {keyword})")
            return True

    return False


def apply_rules(processed_data: dict) -> list:
    """Applies defined rules to processed transaction data."""
    triggered_rules = []
    redis_conn = get_redis_connection()

    # Redis-dependent rules
    if not redis_conn:
        logger.error("Cannot apply Redis-dependent rules: No connection.")
    else:
        if check_high_frequency(
            customer_id=processed_data.get("Customer_ID"),
            transaction_timestamp=processed_data.get("timestamp_dt"),
            redis_conn=redis_conn,
        ):
            triggered_rules.append("high_frequency")


    # Category-based amount check (smart fraud detection)
    is_category_fraud, category_reason = check_category_based_amount(
        processed_data.get("Transaction_Amount"), 
        processed_data.get("description", "")
    )
    if is_category_fraud:
        triggered_rules.append("category_based_fraud")

    if check_suspicious_description(processed_data.get("description")):
        triggered_rules.append("suspicious_description")

    if processed_data.get("location_mismatch"):
        triggered_rules.append("location_mismatch")

    transaction_id = processed_data.get("Transaction_ID", "N/A")
    if triggered_rules:
        logger.info(
            f"Rules triggered for transaction {transaction_id}: {triggered_rules}"
        )
    else:
        logger.debug(f"No rules triggered for transaction {transaction_id}.")

    return triggered_rules
