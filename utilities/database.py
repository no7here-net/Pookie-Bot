# Pookie Bot - Discord bot for GYATatouille
# Copyright (C) 2026 no7here
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# ========================================================================

# Database handling script
# Checks / creates database
# Creates tables (if missing)
# Creates global variable accessible to other files for cursor access

import aiomysql
import warnings
import os
import re

from utilities.config import config
from utilities.output import Logger

# Global connection pool so other modules can access it
conn_pool = None

async def init_db():
    global conn_pool

    # Fetch database info from config
    auth = config.get("auth") or {}
    database = auth.get("database") or {}

    db_name = database.get("name", "pookie_bot")
    db_host = database.get("host", "localhost")
    db_username = database.get("username", "root")

    # Verify database name integrity to prevent SQL injection
    if not db_name or not isinstance(db_name, str) or not re.match(r"^[a-zA-Z0-9_]+$", db_name):
        Logger.error("Invalid database name in config.json.")
        raise SystemExit(1)

    # Fetch the actual password from the environment
    env_key = ((config.get("auth") or {}).get("database") or {}).get("password")

    # Connect to mariadb to check if database exists
    try:
        # Connect without specifying a database
        setup_conn = await aiomysql.connect(
            host=db_host,
            user=db_username,
            autocommit=True,
            # Add password attribute if it is set
            **({"password": os.environ.get(env_key)} if (env_key and os.environ.get(env_key)) else {})
        )

        # Create a massive warning in the terminal if passwordless login was successful
        try:
            if not env_key or not os.environ.get(env_key):
                no_password_warning()
        except Exception:
            no_password_warning()

        async with setup_conn.cursor() as cur:
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")

        setup_conn.close()
    except Exception as e:
        Logger.error("Failed to create/verify the MariaDB database. Check log.", str(e))
        return

    # Connect to specific database
    try:
        conn_pool = await aiomysql.create_pool(
            host=db_host,
            user=db_username,
            db=db_name,
            autocommit=True,
            pool_recycle=3600,
            # Add password attribute if it is set
            **({"password": os.environ.get(env_key)} if (env_key and os.environ.get(env_key)) else {})
        )
        Logger.info("Connected to MariaDB database.")
    except Exception as e:
        Logger.error("Failed to pool connections to database. Check log.", str(e))
        return

    # Verify database is not missing any tables
    try:
        # Silence warnings from already exists, expected here
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*already exists.*")

            async with conn_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # 1. Pre-Verified Users
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS pre_verified (
                            user_id BIGINT NOT NULL,
                            guild_id BIGINT NOT NULL,
                            added_by_id BIGINT NOT NULL,
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (user_id, guild_id)
                        )
                    """)

                    # 2. Pending Verifications
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS pending_verifications (
                            user_id BIGINT NOT NULL,
                            guild_id BIGINT NOT NULL,
                            message_id BIGINT NOT NULL,
                            join_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (user_id, guild_id)
                        )
                    """)

                    # 3. Minecraft Accounts Linking
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS mc_accounts (
                            user_id BIGINT PRIMARY KEY,
                            mc_uuid VARCHAR(36) NOT NULL UNIQUE,
                            linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # 4. Minecraft Bans
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS mc_bans (
                            mc_uuid VARCHAR(36) PRIMARY KEY,
                            user_id BIGINT,
                            added_by_id BIGINT NOT NULL,
                            reason TEXT,
                            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # 5. Discord Moderation Logs
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS mod_logs (
                            event_uuid VARCHAR(36) PRIMARY KEY,
                            guild_id BIGINT NOT NULL,
                            user_id BIGINT NOT NULL,
                            added_by_id BIGINT NOT NULL,
                            action VARCHAR(50) NOT NULL,
                            reason TEXT,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # 6. Message Logs (Year in Review)
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS message_logs (
                            event_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                            message_id BIGINT NOT NULL,
                            user_id BIGINT NOT NULL,
                            guild_id BIGINT NOT NULL,
                            channel_id BIGINT NOT NULL,
                            content TEXT NOT NULL,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # 7. Voice Channel Logs (Year in Review)
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS vc_logs (
                            event_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            guild_id BIGINT NOT NULL,
                            channel_id BIGINT NOT NULL,
                            action VARCHAR(10) NOT NULL,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # 8. Media Logs (Uploads from Discord CDN)
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS media_history (
                            event_uuid VARCHAR(36) PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            context VARCHAR(50) NOT NULL,
                            reference_id BIGINT,
                            original_filename VARCHAR(255) NOT NULL,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # 9. Quarantines (Rather than checking mod logs)
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS quarantine (
                            user_id BIGINT NOT NULL,
                            guild_id BIGINT NOT NULL,
                            added_by_id BIGINT NOT NULL,
                            reason TEXT,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (user_id, guild_id)
                        )
                    """)
    except Exception as e:
        Logger.error("Failed to create tables in the database. Check log.", str(e))
        raise SystemExit(1) from None

    Logger.info("Database tables verified.")

# Said massive warning
def no_password_warning():
    Logger.warning("############################################################################################")
    Logger.warning("#                                                                                          #")
    Logger.warning("#                 YOUR DATABASE IS NOT SECURE! Do NOT ignore this message.                 #")
    Logger.warning("#                                                                                          #")
    Logger.warning("#   Your password was detected as missing and successfully logged in without a password!   #")
    Logger.warning("#            The bot will continue for now, but this is a MAJOR security issue!            #")
    Logger.warning("#                                                                                          #")
    Logger.warning("############################################################################################")
