import redis
import logging
import sys
import os
import argparse

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    import config
except ImportError:
    logging.error("Failed to import config.py. Make sure it's in the project root.")
    sys.exit(1)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("LoadRiskyIPs")


def load_ips_to_redis(ip_list: list):
    """Connects to Redis and loads the given IP list into the configured set."""
    redis_conn = None
    loaded_count = 0
    try:
        redis_conn = redis.Redis(**config.get_redis_connection_config())
        redis_conn.ping()  # Verify connection
        logger.info(f"Connected to Redis at {config.REDIS_HOST}:{config.REDIS_PORT}")

        # Use Redis pipeline for efficiency if loading many IPs
        pipe = redis_conn.pipeline()
        for ip in ip_list:
            if ip:  # Ensure IP is not empty
                pipe.sadd(config.REDIS_HIGH_RISK_IPS_SET, ip.strip())

        results = pipe.execute()
        # results contains the number of elements added for each SADD command (1 if added, 0 if already existed)
        loaded_count = sum(results)

        logger.info(
            f"Attempted to load {len(ip_list)} IPs into Redis set '{config.REDIS_HIGH_RISK_IPS_SET}'."
        )
        logger.info(f"Successfully added {loaded_count} new unique IPs.")
        logger.info(
            f"Total IPs in set now: {redis_conn.scard(config.REDIS_HIGH_RISK_IPS_SET)}"
        )

    except redis.exceptions.ConnectionError as e:
        logger.error(f"Failed to connect to Redis: {e}")
    except redis.exceptions.RedisError as e:
        logger.error(f"Redis error during IP loading: {e}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
    finally:
        if redis_conn:
            redis_conn.close()
            logger.debug("Redis connection closed.")


def load_ips_from_file(filepath: str) -> list:
    """Loads IPs from a text file (one IP per line)."""
    try:
        with open(filepath, "r") as f:
            ips = [line.strip() for line in f if line.strip()]
        logger.info(f"Loaded {len(ips)} IPs from file: {filepath}")
        return ips
    except FileNotFoundError:
        logger.error(f"IP list file not found: {filepath}")
        return []
    except Exception as e:
        logger.error(f"Error reading IP list file {filepath}: {e}")
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Load high-risk IP addresses into the Redis set '{config.REDIS_HIGH_RISK_IPS_SET}'."
    )
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        required=True,  # Make file argument mandatory
        help="Path to a text file containing IPs (one per line). This argument is required.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help=f"Clear the existing Redis set '{config.REDIS_HIGH_RISK_IPS_SET}' before loading new IPs.",
    )

    args = parser.parse_args()

    ips_to_load = []
    ips_to_load = load_ips_from_file(args.file)

    if args.clear:
        logger.warning(
            f"Clearing existing IPs from Redis set '{config.REDIS_HIGH_RISK_IPS_SET}'..."
        )
        redis_conn = None
        try:
            redis_conn = redis.Redis(**config.get_redis_connection_config())
            redis_conn.ping()
            deleted_count = redis_conn.delete(config.REDIS_HIGH_RISK_IPS_SET)
            logger.info(
                f"Cleared set '{config.REDIS_HIGH_RISK_IPS_SET}'. Result: {deleted_count}"
            )
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to Redis for clearing: {e}")
        except Exception as e:
            logger.error(f"Error clearing Redis set: {e}")
        finally:
            if redis_conn:
                redis_conn.close()

    if ips_to_load:
        load_ips_to_redis(ips_to_load)
    else:
        logger.warning(
            "No IPs specified or loaded from file. Nothing loaded into Redis."
        )

    logger.info("Script finished.")
