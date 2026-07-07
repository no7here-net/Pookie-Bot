# Handles invite logic
# - pre-verify
# - verify
# - verification via buttons
# - auto-ban logic

import discord

from utilities.database import pool
from utilities.helpers import config, fetch_username
from utilities.output import Logger

# Add a user to pre-verified list to bypass the gatekeeper on join
async def add_preverify(guild_id: int, user_id: int, added_by: int) -> dict:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("INSERT INTO pre_verified (user_id, guild_id, added_by) VALUES (%s, %s, %s)", (user_id, guild_id, added_by,))

                return {
                    "success": True,
                    "error": None
                }
            except Exception:
                return {
                    "success": False,
                    "error": "This user is already pre-verified."
                }

# Non-pre-verified user verification
async def verify_user(member: discord.Member) -> bool:
    # Find verified role and remove them from pending
    server_config = next((s for s in config.get("servers", []) if s.get("guild") == member.guild.id), None)

    # If guild not found error
    if not server_config:
        Logger.warning(f"Failed to verify \"{member.global_name}\" (ID: {member.id}) - server not in config.")
        return False

    # Check issuer has role
    role = member.guild.get_role(server_config.get("roles", {}).get("verified"))

    if not role:
        Logger.info(f"Blocked non-verified member \"{member.global_name}\" (ID: {member.id}) from verifying.")
        return False

    # Grant role
    try:
        await member.add_roles(role)
        Logger.success(f"Granted verified role to \"{member.global_name}\" (ID: {member.id})")
    except Exception as e:
        Logger.warning(f"Failed to grant verified role to \"{member.global_name}\" (ID: {member.id})")
        return False

    # Delete from pending verifications in DB
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Remove from pending list
            await cur.execute("DELETE FROM pending_verifications WHERE user_id = %s AND guild_id = %s", (member.id, member.guild.id,))
            # Clear from pre-verified
            await cur.execute("DELETE FROM pre_verified WHERE user_id = %s AND guild_id = %s", (member.id, member.guild.id,))

    return True

# Accept verification logic for verification buttons
async def process_verification(guild: discord.Guild, message_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Fetch verification message ID
            await cur.execute("SELECT user_id FROM pending_verifications WHERE message_id = %s", (message_id,))
            result = await cur.fetchone()

    # If it doesn't exist, return none
    if not result:
        return None

    # Find member in server
    member = guild.get_member(result[0])

    if member:
        # If they exist, verify
        success = await verify_user(member)
        if success:
            # return member object
            return member

    # Else return none
    return None

# Decline / ban logic for verification buttons
async def process_ban(guild: discord.Guild, message_id: int, reason: str):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Fetch verification message ID
            await cur.execute("SELECT user_id FROM pending_verifications WHERE message_id = %s", (message_id,))
            result = await cur.fetchone()

    # If it doesn't exist, return none
    if not result:
        return None

    # Ban the user
    success = await ban_user(guild, result[0], reason)

    # If successful, return user ID
    if success:
        return result[0]

    # Else return none
    return None

# Bans a user & clears pending verifications
async def ban_user(guild: discord.Guild, user_id: int, reason: str) -> bool:
    # Fetch username through helper function
    username = fetch_username(discord.client, user_id)

    try:
        # discord.Object works even if user is no longer in server
        await guild.ban(discord.Object(id=user_id), reason=reason)

        Logger.info(f"Banned \"{username}\" (ID: {user_id}). Reason: \"{reason}\"")
    except Exception as e:
        Logger.error(f"Failed to ban \"{username}\" (ID: {user_id}). Check log.", str(e))
        return False

    # Clear from pending list
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM pending_verifications WHERE user_id = %s AND guild_id = %s", (user_id, guild.id))
            await cur.execute("DELETE FROM pre_verified WHERE user_id = %s AND guild_id = %s", (user_id, guild.id))

    return True
