# Handles invite logic
# - pre-verify
# - verify
# - verification via buttons
# - auto-ban logic

import aiomysql
import discord
import uuid

import utilities.database as db

from utilities.helpers import config, fetch_username
from utilities.output import Logger

# Add a user to pre-verified list to bypass the gatekeeper on join
async def add_preverify(client: discord.Client, guild_id: int, user_id: int, added_by_id: int) -> dict:
    # Fetch usernames through their ID for logger
    target_username = await fetch_username(client, user_id)
    added_by_username = await fetch_username(client, added_by_id)

    async with db.conn_pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("INSERT INTO pre_verified (user_id, guild_id, added_by_id) VALUES (%s, %s, %s)", (user_id, guild_id, added_by_id,))

                Logger.info(f"\"{added_by_username}\" (ID: {added_by_id}) pre-verified \"{target_username}\" (ID: {user_id}).")

                return {
                    "success": True,
                    "error": None
                }
            except aiomysql.IntegrityError:
                Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) failed to pre-verify \"{target_username}\" (ID: {user_id}) as they are already in the pre_verified table.")

                return {
                    "success": False,
                    "error": "This user is already pre-verified."
                }
            except Exception as e:
                Logger.error(f"\"{added_by_username}\" (ID: {added_by_id}) failed to pre-verify \"{target_username}\" (ID: {user_id}) due to database failure. Check log.", str(e))

                return {
                    "success": False,
                    "error": "Unknown error occurred whilst interacting with the database."
                }

# Non-pre-verified user verification
async def verify_member(member: discord.Member) -> bool:
    # Find verified role and remove them from pending
    server_config = next((s for s in config.get("servers") or [] if s.get("guild_id") == member.guild.id), {}) or {}

    username = member.name
    user_id = member.id

    # If guild not found error
    if not server_config:
        Logger.warning(f"\"{username}\" (ID: {user_id}) failed verification (server not in config).")
        return False

    # Find role in guild
    role = member.guild.get_role((server_config.get("roles") or {}).get("verified"))

    if not role:
        Logger.warning(f"\"{username}\" (ID: {user_id}) will not be automatically verified or removed, as verified role cannot be found.")
        return False

    # Grant role
    try:
        await member.add_roles(role)
        Logger.info(f"\"{username}\" (ID: {user_id}) was successfully given the verified role.")
    except Exception:
        Logger.warning(f"\"{username}\" (ID: {user_id}) could not be given the verified role.")
        return False

    try:
        # Delete from pending verifications in DB
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Remove from pending list
                await cur.execute("DELETE FROM pending_verifications WHERE user_id = %s AND guild_id = %s", (user_id, member.guild.id,))
                # Clear from pre-verified
                await cur.execute("DELETE FROM pre_verified WHERE user_id = %s AND guild_id = %s", (user_id, member.guild.id,))
    except Exception:
        # Incase database update fails
        Logger.warning(f"\"{username}\" (ID: {user_id}) received the verified role but database failed to update. Manual correction required.")
    return True

# Accept verification logic for verification buttons
async def process_verification(client: discord.Client, guild: discord.Guild, message_id: int):
    async with db.conn_pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Fetch verification message ID
            await cur.execute("SELECT user_id FROM pending_verifications WHERE message_id = %s", (message_id,))
            result = await cur.fetchone()

    # If it doesn't exist, return none
    if not result:
        return (None, None)

    user_id = result[0]
    username = await fetch_username(client, user_id)

    try:
        # Find member in server
        member = await guild.fetch_member(user_id)
    except Exception:
        Logger.warning(f"\"{username}\" (ID: {user_id}) could not be fetched as a member in server \"{guild.name}\" (ID: {guild.id}).")
        return (None, None)

    # If they exist, verify
    success = await verify_member(member)

    if not success:
        return (None, None)

    # return user ID
    return (user_id, username)

# Decline / ban logic for verification buttons
async def process_ban(client: discord.Client, guild: discord.Guild, message_id: int, added_by_id: int, reason: str):
    async with db.conn_pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Fetch verification message ID
            await cur.execute("SELECT user_id FROM pending_verifications WHERE message_id = %s", (message_id,))
            result = await cur.fetchone()

    # If it doesn't exist, return none
    if not result:
        return (None, None)

    user_id = result[0]
    username = await fetch_username(client, user_id)

    # Ban the user
    success = await ban_user(client, guild, user_id, username, added_by_id, reason)

    # If successful, return user ID
    if success:
        return (user_id, username)

    # Else return none
    return (None, None)

# Bans a user & clears pending verifications
async def ban_user(client: discord.Client, guild: discord.Guild, user_id: int, username: str, added_by_id: int = None, reason: str = "", task: bool = False) -> bool:
    # Assign added_by_id to bot ID if not set
    added_by_id = added_by_id if added_by_id is not None else client.user.id

    try:
        # discord.Object works even if user is no longer in server
        await guild.ban(discord.Object(id=user_id), reason=reason)
    except Exception:
        Logger.warning(f"\"{username}\" (ID: {user_id}) could not be banned.", task=task)
        return False

    # Clear from pending list & add discord mod log
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM pending_verifications WHERE user_id = %s AND guild_id = %s", (user_id, guild.id,))
                await cur.execute("DELETE FROM pre_verified WHERE user_id = %s AND guild_id = %s", (user_id, guild.id,))
                # Log the ban action using the bot's own ID as the added_by_id
                await cur.execute("INSERT INTO mod_logs (event_uuid, guild_id, user_id, added_by_id, action, reason) VALUES (%s, %s, %s, %s, %s, %s)", (str(uuid.uuid4()), guild.id, user_id, added_by_id, "ban", reason,))
    except Exception:
        Logger.warning(f"\"{username}\" (ID: {user_id}) was banned, but the database failed to update. Manual correction required.", task=task)
        return True
    return True
