#!/usr/bin/env python3
"""Bootstrap an admin API key for system operations.

This script creates an admin API key for:
- Cache clearing operations
- System administration tasks
- Deployment automation (CI/CD)

The admin key is NOT tied to a Cognito user - it uses a system user_id (0).
The secret is output ONCE to stdout for storage in AWS Secrets Manager.

Usage:
    # Create admin key and display secret
    python scripts/bootstrap_admin_key.py

    # Output as JSON (for automation)
    python scripts/bootstrap_admin_key.py --json

    # Custom name
    python scripts/bootstrap_admin_key.py --name "deploy-admin"

    # Check if admin key exists
    python scripts/bootstrap_admin_key.py --check

Environment Variables:
    MLPAL_DB_HOST     - Database host (required)
    MLPAL_DB_PORT     - Database port (default: 5432)
    MLPAL_DB_NAME     - Database name (default: postgres)
    MLPAL_DB_USER     - Database user (required)
    MLPAL_DB_PASSWORD - Database password (required)
    MLPAL_DB_SCHEMA   - Assistants schema (default: assistants)
"""

import argparse
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import psycopg2
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# API Key settings (matches config.py)
API_KEY_PREFIX = "mlpal_sk_"
API_KEY_BYTES = 32  # 256 bits of randomness

# System user ID for admin keys (not tied to any Cognito user)
SYSTEM_USER_ID = 0


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.

    Returns:
        Tuple of (full_key, key_hash, key_prefix)
        - full_key: The complete key to show to user once
        - key_hash: SHA-256 hash for storage
        - key_prefix: First part for identification
    """
    random_bytes = secrets.token_bytes(API_KEY_BYTES)
    random_part = random_bytes.hex()

    full_key = f"{API_KEY_PREFIX}{random_part}"
    key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
    key_prefix = f"{API_KEY_PREFIX}{random_part[:8]}..."

    return full_key, key_hash, key_prefix


def get_db_connection():
    """Get database connection from environment variables."""
    db_host = os.environ.get("MLPAL_DB_HOST")
    db_port = os.environ.get("MLPAL_DB_PORT", "5432")
    db_name = os.environ.get("MLPAL_DB_NAME", "postgres")
    db_user = os.environ.get("MLPAL_DB_USER")
    db_password = os.environ.get("MLPAL_DB_PASSWORD")

    if not all([db_host, db_user, db_password]):
        raise Exception(
            "Database settings required: MLPAL_DB_HOST, MLPAL_DB_USER, MLPAL_DB_PASSWORD"
        )

    return psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
    )


def check_admin_key_exists(schema: str = "assistants") -> dict | None:
    """
    Check if an admin key already exists.

    Returns:
        Admin key info if exists, None otherwise
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, name, key_prefix, is_active, created_at
                FROM {schema}.api_keys
                WHERE user_id = %s AND is_active = true
                  -- `?` matches both shapes: element of a JSONB array (new list
                  -- form) or top-level key of a JSONB object (legacy dict form).
                  AND permissions ? 'admin'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (SYSTEM_USER_ID,)
            )
            result = cur.fetchone()

            if result:
                return {
                    "id": result[0],
                    "name": result[1],
                    "key_prefix": result[2],
                    "is_active": result[3],
                    "created_at": str(result[4]),
                }
            return None
    finally:
        conn.close()


def create_admin_key(
    name: str = "system-admin",
    description: str = "System admin key for cache clearing and deployment operations",
    schema: str = "assistants",
) -> dict:
    """
    Create a new admin API key.

    Args:
        name: Name for the key
        description: Description for the key
        schema: Database schema for api_keys table

    Returns:
        API key object with secret (only shown once)
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Generate the API key
            secret, key_hash, key_prefix = generate_api_key()

            # Admin permissions — LIST form (the canonical shape APIKeyResponse
            # serializes; has_permission accepts it, and "*" grants full access).
            permissions = ["admin", "*"]

            # Insert into database
            cur.execute(
                f"""
                INSERT INTO {schema}.api_keys
                (user_id, key_hash, key_prefix, name, description, permissions, rate_limit_tier, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, 'unlimited', true)
                RETURNING id, created_at
                """,
                (SYSTEM_USER_ID, key_hash, key_prefix, name, description, json.dumps(permissions))
            )

            key_id, created_at = cur.fetchone()
            conn.commit()

            return {
                "id": key_id,
                "name": name,
                "description": description,
                "key_prefix": key_prefix,
                "permissions": permissions,
                "user_id": SYSTEM_USER_ID,
                "rate_limit_tier": "unlimited",
                "created_at": str(created_at),
                "secret": secret,
            }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap an admin API key for system operations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Create admin key, display secret
  %(prog)s --json                   # Output as JSON for automation
  %(prog)s --check                  # Check if admin key exists
  %(prog)s --name "deploy-admin"    # Custom name

The secret key is output to stdout ONCE. Store it securely in AWS Secrets Manager.
        """,
    )

    parser.add_argument(
        "--name", "-n",
        default="system-admin",
        help="Name for the admin key (default: system-admin)",
    )
    parser.add_argument(
        "--description", "-d",
        default="System admin key for cache clearing and deployment operations",
        help="Description for the admin key",
    )
    parser.add_argument(
        "--schema", "-s",
        default=os.environ.get("MLPAL_DB_SCHEMA", "assistants"),
        help="Database schema (default: assistants)",
    )
    parser.add_argument(
        "--check", "-c",
        action="store_true",
        help="Check if admin key exists (don't create)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output in JSON format",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Create new key even if one exists",
    )

    args = parser.parse_args()

    try:
        # Check if admin key already exists
        existing = check_admin_key_exists(schema=args.schema)

        if args.check:
            if existing:
                if args.json:
                    print(json.dumps({"exists": True, "key": existing}, indent=2, default=str))
                else:
                    print(f"Admin key exists: {existing['name']}")
                    print(f"  Prefix: {existing['key_prefix']}")
                    print(f"  Created: {existing['created_at']}")
                sys.exit(0)
            else:
                if args.json:
                    print(json.dumps({"exists": False}, indent=2))
                else:
                    print("No admin key found.")
                sys.exit(1)

        if existing and not args.force:
            print(f"Admin key already exists: {existing['name']}", file=sys.stderr)
            print(f"  Prefix: {existing['key_prefix']}", file=sys.stderr)
            print("Use --force to create a new one anyway.", file=sys.stderr)
            sys.exit(1)

        # Create admin key
        print(f"Creating admin key '{args.name}'...", file=sys.stderr)
        admin_key = create_admin_key(
            name=args.name,
            description=args.description,
            schema=args.schema,
        )

        if args.json:
            print(json.dumps(admin_key, indent=2, default=str))
        else:
            print("\n" + "=" * 70, file=sys.stderr)
            print("ADMIN API KEY CREATED SUCCESSFULLY", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            print(f"Name:        {admin_key['name']}", file=sys.stderr)
            print(f"Key Prefix:  {admin_key['key_prefix']}", file=sys.stderr)
            print(f"Permissions: admin=true, *=true", file=sys.stderr)
            print(f"Rate Limit:  unlimited", file=sys.stderr)
            print("-" * 70, file=sys.stderr)
            # Output secret to stdout (for piping to secrets manager)
            print(admin_key['secret'])
            print("-" * 70, file=sys.stderr)
            print("SAVE THIS KEY NOW - IT WILL NOT BE SHOWN AGAIN!", file=sys.stderr)
            print("Store in AWS Secrets Manager:", file=sys.stderr)
            print("  aws secretsmanager put-secret-value \\", file=sys.stderr)
            print("    --secret-id mlpal/admin-api-key \\", file=sys.stderr)
            print(f"    --secret-string '{admin_key['secret']}'", file=sys.stderr)
            print("=" * 70, file=sys.stderr)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
