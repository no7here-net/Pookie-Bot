import os
import aiomysql
from utilities.output import Logger
from utilities.helpers import config

# Global connection pool so other modules can access it
pool = None

async def init_db():
    global pool

    # Fetch database info from config
    db_host = config.get("auth", {}).get("database", {}).get("host", "localhost")
    db_user = config.get("auth", {}).get("database", {}).get("username", "root")
    db_name = "pookie_bot"

    # Fetch the actual password from the environment
    db_password = os.environ.get(config.get("auth", {}).get("database", {}).get("password", ""), "")

    # Connect to mariadb to check if database exists
    try:
        # Connect without specifying a database
        setup_conn = await aiomysql.connect(
            host=db_host,
            user=db_user,
            password=db_password,
            autocommit=True
        )

        async with setup_conn.cursor() as cur:
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")

        setup_conn.close()
    except Exception as e:
        Logger.error("Failed to create/verify the MariaDB database. Check log.", str(e))
        return

    # Connect to specific database
    try:
        pool = await aiomysql.create_pool(
            host=db_host,
            user=db_user,
            password=db_password,
            db=db_name,
            autocommit=True
        )
        Logger.success(f"Connected to MariaDB database successfully.")
    except Exception as e:
        Logger.error(f"Failed to pool connections to database. Check log.", str(e))
        return

    # Verify database is not missing any tables
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 1. Pre-Verified Users
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS pre_verified (
                    user_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    added_by BIGINT NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Pending Verifications
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_verifications (
                    user_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    join_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. Minecraft Accounts Linking
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS mc_accounts (
                    discord_id BIGINT PRIMARY KEY,
                    mc_uuid VARCHAR(36) NOT NULL UNIQUE,
                    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 4. Minecraft Bans
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS mc_bans (
                    mc_uuid VARCHAR(36) PRIMARY KEY,
                    discord_id BIGINT,
                    moderator_id BIGINT NOT NULL,
                    reason TEXT,
                    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (mc_uuid) REFERENCES mc_accounts(mc_uuid) ON DELETE CASCADE
                )
            """)

            # 5. Discord Moderation Logs
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS mod_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    target_id BIGINT NOT NULL,
                    moderator_id BIGINT NOT NULL,
                    action VARCHAR(50) NOT NULL,
                    reason TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 6. Message Logs (Year in Review)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS message_logs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
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
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
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
                    id VARCHAR(36) PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    context VARCHAR(50) NOT NULL,
                    reference_id BIGINT,
                    original_filename VARCHAR(255) NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    Logger.info("Database tables verified.")
