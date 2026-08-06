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

# Handles invite logic
# - pre-verify
# - verify
# - verification via buttons
# - auto-ban logic

import aiomysql
import discord

from typing import Literal

import utilities.database as db

from utilities.output import Logger
from utilities.config import get_guild_config
from utilities.helpers import fetch_username
from utilities.database import is_quarantined, log_action, clear_preverified, clear_verification_state, fetch_pending_by_message

# Add or remove a user from pre-verified list to bypass the gatekeeper on join
async def preverify_logic(client: discord.Client, action: Literal["Add", "Remove"], guild_id: int, user_id: int, added_by_id: int) -> dict:
    # Fetch usernames through their ID for logger
    username = await fetch_username(client, user_id)
    added_by_username = await fetch_username(client, added_by_id)

    async with db.conn_pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                if action == "Add":
                    await cur.execute("INSERT INTO pre_verified (user_id, guild_id, added_by_id) VALUES (%s, %s, %s)", (user_id, guild_id, added_by_id,))
                else:
                    # A rowcount of 0 means there was nothing to delete
                    if await clear_preverified(guild_id, user_id, cur=cur) == 0:
                        Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) failed to remove pre-verification for \"{username}\" (ID: {user_id}) as they are not in the pre_verified table.")

                        return {
                            "success": False,
                            "error": "This user is not pre-verified."
                        }

                Logger.info(f"\"{added_by_username}\" (ID: {added_by_id}) {"pre-verified" if action == "Add" else "removed pre-verification for"} \"{username}\" (ID: {user_id}).")

                return {
                    "success": True,
                    "error": None
                }
            except aiomysql.IntegrityError:
                # Only the INSERT can raise this - the primary key means they're already pre-verified
                Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) failed to pre-verify \"{username}\" (ID: {user_id}) as they are already in the pre_verified table.")

                return {
                    "success": False,
                    "error": "This user is already pre-verified."
                }
            except Exception as e:
                Logger.error(f"\"{added_by_username}\" (ID: {added_by_id}) failed to {"pre-verify" if action == "Add" else "remove pre-verification for"} \"{username}\" (ID: {user_id}) due to database failure. Check log.", str(e))

                return {
                    "success": False,
                    "error": "Unknown error occurred whilst interacting with the database."
                }

# Fetch all pre-verified users for a guild, oldest first
async def preverify_list(guild_id: int) -> dict:
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT user_id, added_by_id, added_at FROM pre_verified WHERE guild_id = %s ORDER BY added_at ASC", (guild_id,))
                entries = await cur.fetchall()

        return {
            "success": True,
            "entries": entries
        }
    except Exception as e:
        Logger.error(f"Failed to fetch the pre-verified list for server (ID: {guild_id}). Check log.", str(e))

        return {
            "success": False,
            "error": "Unknown error occurred whilst interacting with the database."
        }

# Verifies join state for a user in one trip
async def fetch_join_state(guild_id: int, user_id: int) -> dict:
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT
                        p.added_by_id,
                        pv.message_id,
                        pv.join_time
                    FROM (SELECT %s AS user_id, %s AS guild_id) AS target
                    LEFT JOIN pre_verified p ON p.user_id = target.user_id AND p.guild_id = target.guild_id
                    LEFT JOIN pending_verifications pv ON pv.user_id = target.user_id AND pv.guild_id = target.guild_id
                """, (user_id, guild_id,))
                result = await cur.fetchone()

                # Contains information to resolve whether a user was pre-verified (and by who) and any pending verification message left over from a previous join
                return {
                    "success": True,
                    "preverified_by_id": result[0],
                    "pending_message_id": result[1],
                    "pending_join_time": result[2]
                }
    except Exception as e:
        Logger.error(f"Failed to fetch join state for user (ID: {user_id}) in server (ID: {guild_id}). Check log.", str(e))

        return { "success": False }

# Registers a pending verification for a user, refreshing existing entry if they rejoined whilst still pending so the 24h timer restarts and the buttons on the newest join message become the live one
async def register_pending(guild_id: int, user_id: int, message_id: int) -> bool:
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Upsert on the (user_id, guild_id) primary key
                await cur.execute("""
                    INSERT INTO pending_verifications (user_id, guild_id, message_id)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE message_id = VALUES(message_id), join_time = CURRENT_TIMESTAMP
                """, (user_id, guild_id, message_id,))
        return True
    except Exception as e:
        Logger.error(f"Failed to register pending verification for user (ID: {user_id}) in server (ID: {guild_id}). Check log.", str(e))

        return False

# Non-pre-verified user verification
async def verify_member(member: discord.Member, task: bool = False) -> bool:
    # Find verified role and remove them from pending
    server_config = get_guild_config(member.guild.id)

    username = member.name
    user_id = member.id

    # If guild not found error
    if not server_config:
        Logger.warning(f"\"{username}\" (ID: {user_id}) failed verification as the server was not in the config.", task=task)
        return False

    # Find role in guild
    role = member.guild.get_role((server_config.get("roles") or {}).get("verified"))

    if not role:
        Logger.warning(f"\"{username}\" (ID: {user_id}) will not be automatically verified or removed, as verified role cannot be found.", task=task)
        return False

    # Find if they are quarantined
    quarantine = await is_quarantined(member.guild.id, user_id)

    # Catch quarantine check failures
    if quarantine is None:
        Logger.warning(f"\"{username}\" (ID: {user_id}) could not be checked against quarantine list.", task=task)
        return False
    # They're quarantined, block
    if quarantine:
        Logger.warning(f"\"{username}\" (ID: {user_id}) could not be verified as they are quarantined.", task=task)
        return False

    if role in member.roles:
        Logger.warning(f"\"{username}\" (ID: {user_id}) will not be given the verified role as they are already verified.", task=task)
        return False

    # Grant role
    try:
        await member.add_roles(role)
        Logger.info(f"\"{username}\" (ID: {user_id}) was successfully given the verified role.", task=task)
    except Exception:
        Logger.warning(f"\"{username}\" (ID: {user_id}) could not be given the verified role.", task=task)
        return False

    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Remove & clear pending / preverified lists
                await clear_verification_state(member.guild.id, user_id, cur=cur)
    except Exception:
        # Incase database update fails
        Logger.warning(f"\"{username}\" (ID: {user_id}) received the verified role but database failed to update. Manual correction required.", task=task)
    return True

# Accept verification logic for verification buttons
async def process_verification(client: discord.Client, guild: discord.Guild, message_id: int):
    # Fetch user ID from message ID
    user_id = await fetch_pending_by_message(message_id)

    # If it doesn't exist, return none
    if not user_id:
        return (None, None)

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
    # Fetch user ID from message ID
    user_id = await fetch_pending_by_message(message_id)

    # If it doesn't exist, return none
    if not user_id:
        return (None, None)

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

    # Clear from pending list, pre-verified & add discord mod log
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await clear_verification_state(guild.id, user_id, cur=cur)
                # Log the ban action using the bot's own ID as the added_by_id
                await log_action(guild.id, user_id, added_by_id, "ban", reason, cur)
    except Exception:
        Logger.warning(f"\"{username}\" (ID: {user_id}) was banned, but the database failed to update. Manual correction required.", task=task)
        return True
    return True
