# Minecraft functions
# Handles RCON check, whitelist, blacklist (when done) and RCON commands

import discord
import asyncio
import aiohttp
import uuid
import os
import re

from urllib.parse import urlparse
from typing import Literal
from mcrcon import MCRcon

import utilities.database as db

from utilities.output import Logger
from utilities.helpers import config, fetch_username

# Check Minecraft host(s)
async def check_rcon(task: bool = False) -> dict:
    # Fetch Minecraft server list from config
    mc_servers = (config.get("minecraft") or {}).get("servers") or {}

    # If there are no servers, return nothing
    if not mc_servers:
        return {}

    # Create list of server names
    server_names = []

    # Create list of tasks
    rcon_tasks = []

    # Iterates through all servers in config
    for name, info in mc_servers.items():
        # Fetch non-sensitive key name
        env_key = info.get("rcon_password")

        # If the config is missing the key, or the environment is missing the password
        if not env_key or not os.environ.get(env_key):
            Logger.warning(f"Failed to fetch RCON password for \"{name}\" from config.json / environment variables.", task=task)
            continue

        # Check config data is not missing
        missing_keys = []

        if not info.get("address"):
            missing_keys.append("address")

        if not info.get("rcon_port"):
            missing_keys.append("rcon_port")

        if missing_keys:
            # Joins the list with " and ", so it handles 1 or 2 items perfectly
            Logger.warning(f"Failed to fetch \"{"\" and \"".join(missing_keys)}\" for \"{name}\" from config.json.", task=task)
            continue

        # Append server name if checks pass
        server_names.append(name)

        # Queue a background task using internal rcon function
        rcon_tasks.append(asyncio.to_thread(_sync_check_rcon, info.get("address"), info.get("rcon_port"), os.environ.get(env_key), task=task))

    # Run RCON connections simultaneously
    results = await asyncio.gather(*rcon_tasks)

    # Return a KV dictionary
    return dict(zip(server_names, results))

# Fetches and either links or unlinks a Minecraft and Discord account
async def whitelist_logic(client: discord.Client, action: Literal["Add", "Remove"], user_id: int, mc_username: str) -> dict:
    # Fetch Discord username from ID provided in attributes. Safe to do here as its value is guarded by the functions that trigger this one.
    username = await fetch_username(client, user_id)

    # Validate Minecraft username
    mc_uuid, error_response = await _validate_and_fetch_uuid("whitelist", mc_username, username, user_id)

    if error_response: return error_response

    # Perform global Minecraft security checks on database
    db_state = await _fetch_database_state(mc_uuid, user_id)

    # These checks are the same across both adding and removing from whitelist

    # If an error occurs when checking the database, abort
    if not db_state.get("success"):
        Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from modifying the whitelist due to a database exception.")

        return {
            "success": False,
            "error": "Failed to connect to database to perform checks."
        }

    # Check if the result from DB check indicated it is a banned MC account
    if db_state.get("mc_ban_reason"):
        Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from modifying the whitelist as the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) is banned.")

        return {
            "success": False,
            "error": "This Minecraft account is banned."
        }

    # Check if the result from DB check indicated their Discord account is tied to a banned MC account
    if db_state.get("discord_ban_reason"):
        Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from modifying the whitelist as the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) is banned from linking accounts.")

        return {
            "success": False,
            "error": "This Discord account is linked to a banned Minecraft account."
        }

    if action == "Add":
        # Check if the Discord account is already connected to an MC account
        if db_state.get("discord_linked_uuid"):
            linked_mc_uuid = db_state.get("discord_linked_uuid")
            linked_mc_username = await _fetch_mc_username(linked_mc_uuid)

            # Catch broken username lookups
            if linked_mc_username in ("failed", "unknown"):
                return {
                    "success": False,
                    "error": "Failed to reach Mojang's API for account information."
                }

            Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from whitelisting the account \"{mc_username}\" (UUID: {mc_uuid}) as the Minecraft account \"{linked_mc_username}\" (UUID: {linked_mc_uuid}) as it is already linked.")

            return {
                "success": False,
                "error": "Your Discord account is already linked to a Minecraft account."
            }

        # Check if the MC account is connected to another Discord account
        if db_state.get("mc_linked_user_id"):
            linked_user_id = db_state.get("mc_linked_user_id")
            linked_username = await fetch_username(client, linked_user_id)

            Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from whitelisting the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) as it is already connected to another user \"{linked_username}\" (ID: {linked_user_id}).")

            return {
                "success": False,
                "error": "This Minecraft account is already linked to another Discord account."
            }

    if action == "Remove":
        # Check if the Discord account isn't connected to an MC account
        if not db_state.get("discord_linked_uuid"):
            Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from unwhitelisting the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) as it is not linked to any Minecraft account.")

            return {
                "success": False,
                "error": "Your Discord account is not linked to a Minecraft account."
            }

        # Check if the MC account is connected to another Discord account
        if db_state.get("mc_linked_user_id") != user_id:
            Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from unwhitelisting \"{mc_username}\" (UUID: {mc_uuid}) as it is not linked to them.")

            return {
                "success": False,
                "error": "Your Discord account is not linked to this Minecraft account."
            }

    # Checks passed, so send command to server
    response = await _send_velocity_command(f"whitelist {action.lower()} {mc_username}")

    # Catch if response errored out
    if f"{"added" if action == "Add" else "removed"} player" not in response.lower():
        Logger.warning(f"\"{username}\" (ID: {user_id}) failed to execute whitelist {action.lower()} command for the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}).")

        return {
            "success": False,
            "error": "Failed to execute whitelist command on the server."
        }

    # Update the database
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                if action == "Add":
                    await cur.execute("INSERT INTO mc_accounts (user_id, mc_uuid) VALUES (%s, %s)", (user_id, mc_uuid,))
                elif action == "Remove":
                    await cur.execute("DELETE FROM mc_accounts WHERE user_id = %s AND mc_uuid = %s", (user_id, mc_uuid,))
    except Exception:
        Logger.warning(f"\"{username}\" (ID: {user_id}) passed whitelist logic and has been {"added to" if action == "Add" else "removed from"} the whitelist, but an error occurred when updating the database.")

    # Fetch the avatar associated with the username
    mc_avatar = await _fetch_mc_avatar(mc_username, mc_uuid)

    # Return success for either add or remove
    Logger.info(f"\"{username}\" (ID: {user_id}) successfully {"whitelisted" if action == "Add" else "unlinked"} \"{mc_username}\" (UUID: {mc_uuid}).")

    return {
        "success": True,
        "uuid": mc_uuid,
        "avatar": mc_avatar,
    }

# Fetch and ban Minecraft (and Discord if linked) account
async def blacklist_logic(client: discord.Client, action: Literal["Add", "Remove"], guild_id: int, added_by_id: int, mc_username: str, reason: str) -> dict:
    # Fetch Discord username from ID provided in attributes. Safe to do here as its value is guarded by the functions that trigger this one.
    added_by_username = await fetch_username(client, added_by_id)

    # Validate Minecraft username
    mc_uuid, error_response = await _validate_and_fetch_uuid("blacklist", mc_username, added_by_username, added_by_id)

    if error_response: return error_response

    # Perform global Minecraft security checks on database
    db_state = await _fetch_database_state(mc_uuid)

    # Defined early outside of if block so it can be referenced in rest of logic
    user_id = None
    existing_added_by_id = None

    # Some of these checks are the same across both adding and removing from blacklist

    # If an error occurs when checking the database, abort
    if not db_state.get("success"):
        Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) was blocked from modifying the blacklist due to a database exception.")

        return {
            "success": False,
            "error": "Failed to connect to database to perform checks."
        }

    if db_state.get("mc_ban_reason") and action == "Add":
        Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) was blocked from blacklisting the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) as it is already blacklisted (Reason: {db_state.get("mc_ban_reason")}).")

        return {
            "success": False,
            "error": "This Minecraft account is already blacklisted."
        }

    if db_state.get("mc_linked_user_id"):
        if action == "Remove":
            Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) was blocked from unblacklisting the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) as it is already whitelisted.")

            return {
                "success": False,
                "error": "The Minecraft account is currently whitelisted."
            }
        else:
            user_id = db_state.get("mc_linked_user_id")
            username = await fetch_username(client, user_id)

            # Checks passed, so send command to server
            response = await _send_velocity_command(f"whitelist remove {mc_username}")

            # Catch if response errored out
            if "removed player" not in response.lower() and "is not in the whitelist" not in response.lower():
                Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) failed to execute whitelist remove command for the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) so it can be added to blacklist.")

                return {
                    "success": False,
                    "error": "Failed to execute whitelist removal command on the server."
                }

    if not db_state.get("mc_ban_reason") and action == "Remove":
        Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) was blocked from unblacklisting the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) as it is not currently blacklisted.")

        return {
            "success": False,
            "error": "This Minecraft account is not blacklisted."
        }

    # Checks passed, so send command to server
    response = await _send_velocity_command(f"blacklist {action.lower()} {mc_username}")

    # Catch if response errored out
    if f"{"added" if action == "Add" else "removed"} player" not in response.lower():
        Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) failed to execute blacklist {action.lower()} command for the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}).")

        return {
            "success": False,
            "error": "Failed to execute blacklist command on the server."
        }

    # Update database & handle any possible issues
    if action == "Add":
        try:
            async with db.conn_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Indicate the start of a transaction group so that rather than executing each one instantly one at a time which could result in de-synced requests, they all happen together
                    await conn.begin()

                    try:
                        if user_id:
                            # Delete existing connected account from database
                            await cur.execute("DELETE FROM mc_accounts WHERE user_id = %s AND mc_uuid = %s", (user_id, mc_uuid,))

                            # Add MC account to ban database and link with its Discord account
                            await cur.execute("INSERT INTO mc_bans (mc_uuid, user_id, added_by_id, reason) VALUES (%s, %s, %s, %s)", (mc_uuid, user_id, added_by_id, reason,))

                            # Add to mod log
                            await cur.execute("INSERT INTO mod_logs (event_uuid, guild_id, user_id, added_by_id, action, reason) VALUES (%s, %s, %s, %s, %s, %s)", (str(uuid.uuid4()), guild_id, user_id, added_by_id, "mc_ban", reason,))
                        else:
                            Logger.info(f"\"{added_by_username}\" (ID: {added_by_id}) is blacklisting the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}), which is not connected to a Discord account.")

                            # Add MC account to ban database but leave Discord ID blank
                            await cur.execute("INSERT INTO mc_bans (mc_uuid, added_by_id, reason) VALUES (%s, %s, %s)", (mc_uuid, added_by_id, reason,))

                            # No mod log can be added, as there is no associated Discord account, which is a required column in the database

                        # Save simultaneously
                        await conn.commit()
                    except Exception:
                        # If an error occurs executing the transactions in bulk, roll them back to prevent weird bugs with future database transactions
                        await conn.rollback()
                        raise
        except Exception:
            Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) successfully blacklisted the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) server-side, but an error occurred when updating the database.")

            return {
                "success": False,
                "error": "Failed to update the database."
            }

    elif action == "Remove":
        user_id = db_state.get("mc_ban_user_id")
        existing_added_by_id = db_state.get("mc_ban_added_by_id")
        existing_reason = db_state.get("mc_ban_reason")

        # Used for the logs
        username = await fetch_username(client, user_id) if user_id else None
        existing_added_by_username = await fetch_username(client, existing_added_by_id) if existing_added_by_id else None

        try:
            async with db.conn_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Indicate the start of a transaction group so that rather than executing each one instantly one at a time which could result in de-synced requests, they all happen together
                    await conn.begin()

                    try:
                        # Remove ban
                        await cur.execute("DELETE FROM mc_bans WHERE mc_uuid = %s", (mc_uuid,))

                        if user_id:
                            await cur.execute("INSERT INTO mod_logs (event_uuid, guild_id, user_id, added_by_id, action, reason) VALUES (%s, %s, %s, %s, %s, %s)", (str(uuid.uuid4()), guild_id, user_id, added_by_id, "mc_unban", reason,))

                        # Save simultaneously
                        await conn.commit()
                    except Exception:
                        # If something went wrong, clean the connection before letting it go
                        await conn.rollback()
                        raise
        except Exception:
            # If an error occurs executing the transactions in bulk, roll them back to prevent weird bugs with future database transactions
            Logger.warning(f"\"{added_by_username}\" (ID: {added_by_id}) failed to execute blacklist removal from database for the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}), who was banned by \"{existing_added_by_username}\" (ID: {existing_added_by_id}) for {existing_reason}.")

            return {
                "success": False,
                "error": "Failed to update the database to remove the ban."
            }

    # Fetch MC avatar from skin
    mc_avatar = await _fetch_mc_avatar(mc_username, mc_uuid)

    Logger.info(f"\"{added_by_username}\" (ID: {added_by_id}) successfully {"un" if action == "Remove" else ""}blacklisted \"{mc_username}\" (UUID: {mc_uuid}){f" and its associated Discord account \"{username}\" (ID: {user_id})" if user_id else ""}.")

    # Return info
    return {
        "success": True,
        "uuid": mc_uuid,
        "avatar": mc_avatar,
        **({"added_by_id": existing_added_by_id} if existing_added_by_id else {}),
        **({"user_id": user_id} if user_id else {})
    }

# ================
# INTERNAL HELPERS
# ================

# Fetches the entire database state for an MC UUID and a Discord User ID
async def _fetch_database_state(mc_uuid: str, user_id: int = None) -> dict:
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Build a single query to fetch all states simultaneously
                query = """
                    SELECT
                        (SELECT reason FROM mc_bans WHERE mc_uuid = %s),
                        (SELECT user_id FROM mc_accounts WHERE mc_uuid = %s),
                        (SELECT user_id FROM mc_bans WHERE mc_uuid = %s),
                        (SELECT added_by_id FROM mc_bans WHERE mc_uuid = %s)
                """
                params = [mc_uuid, mc_uuid, mc_uuid, mc_uuid]

                # Append Discord checks if an ID was provided
                if user_id:
                    query += """,
                        (SELECT reason FROM mc_bans WHERE user_id = %s),
                        (SELECT mc_uuid FROM mc_accounts WHERE user_id = %s)
                    """
                    params.extend([user_id, user_id])

                # Execute one round-trip to the database
                await cur.execute(query, tuple(params))
                result = await cur.fetchone()

                return {
                    "success": True,
                    "mc_ban_reason": result[0],
                    "mc_linked_user_id": result[1],
                    "mc_ban_user_id": result[2],
                    "mc_ban_added_by_id": result[3],
                    "discord_ban_reason": result[4] if user_id else None,
                    "discord_linked_uuid": result[5] if user_id else None
                }
    except Exception:
        return { "success": False }

# Validates, fetches, and handles all error logging for a Minecraft UUID
async def _validate_and_fetch_uuid(action: str, mc_username: str, username: str, user_id: int) -> tuple[str | None, dict | None]:
    mc_uuid = await _fetch_mc_uuid(mc_username)

    # Error key containing both logger & embed messages
    uuid_errors = {
        "invalid": (
            "due to invalid characters in the Minecraft username",
            "Invalid Minecraft username. Usernames can only contain letters, numbers, and underscores."
        ),
        "failed": (
            "as communication with Mojang servers failed",
            "Failed to communicate with Mojang servers to find the account."
        ),
        "unknown": (
            "as their UUID could not be found",
            "Failed to find Minecraft account."
        )
    }

    if mc_uuid in uuid_errors:
        log_reason, embed_msg = uuid_errors[mc_uuid]

        # Pass action_context dynamically so the log makes sense for both whitelist and blacklist
        Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from modifying the {action} for the Minecraft account \"{mc_username}\" {log_reason}.")

        # Return None for the UUID, and the error dictionary to pass back to Discord
        return None, {
            "success": False,
            "error": embed_msg
        }
    # If successful, return the UUID and None for the error
    return mc_uuid, None

# Fetches UUID from username using official API
async def _fetch_mc_uuid(mc_username: str) -> str:
    if not re.match(r"^[a-zA-Z0-9_]{2,16}$", mc_username):
        # Logging handled at function call end
        return "invalid"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://api.mojang.com/users/profiles/minecraft/{mc_username}", timeout=aiohttp.ClientTimeout(total=2)) as response:
                if response.status == 200:
                    data = await response.json()
                    # Would be extremely weird for ID to be missing, but it is caught here anyway.
                    return data.get("id", "unknown")
                return "unknown"
        except Exception:
            Logger.warning(f"Failed to fetch UUID for Minecraft username \"{mc_username}\".")
            return "failed"

# Fetches username from UUID using official API
async def _fetch_mc_username(mc_uuid: str) -> str:
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://sessionserver.mojang.com/session/minecraft/profile/{mc_uuid}", timeout=aiohttp.ClientTimeout(total=2)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("name", "unknown")
                Logger.warning(f"Failed to fetch username for Minecraft UUID \"{mc_uuid}\" as response was not \"OK\" (Status: {response.status}).")
                return "failed"
        except Exception:
            Logger.warning(f"Failed to fetch username for Minecraft UUID \"{mc_uuid}\".")
            return "failed"

# Fetches avatar by trying multiple 3rd party services
async def _fetch_mc_avatar(mc_username: str, mc_uuid: str) -> str:
    # APIs in order of preference
    apis = [
        f"https://minotar.net/avatar/{mc_uuid}",
        f"https://mc-heads.net/avatar/{mc_uuid}"
    ]

    async with aiohttp.ClientSession() as session:
        for url in apis:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as response:
                    if response.status == 200:
                        return url
            except Exception:
                Logger.warning(f"Failed to fetch avatar using API \"{urlparse(url).netloc}\" for \"{mc_username}\" (UUID: {mc_uuid}).")
    Logger.warning(f"Failed to fetch avatar via any API for \"{mc_username}\" (UUID: {mc_uuid}).")
    return ""

# Send a command to Velocity
async def _send_velocity_command(command: str, task: bool = False) -> str:
    # Find velocity info from config
    velocity = ((config.get("minecraft") or {}).get("servers") or {}).get("velocity")

    # If there isn't a velocity entry in the config, return nothing
    if not velocity:
        Logger.warning("Velocity proxy not found in config.json.", task=task)
        return "ERROR"

    # Fetch non-sensitive key name
    env_key = velocity.get("rcon_password")

    # If the config is missing the key, or the environment is missing the password
    if not env_key or not os.environ.get(env_key):
        Logger.warning("Failed to fetch RCON password for \"velocity\" from config.json / environment variables.", task=task)
        return "ERROR"

    # Return direct result from _rcon_send function
    return await asyncio.to_thread(_sync_send_rcon, velocity.get("address"), velocity.get("rcon_port"), os.environ.get(env_key), command, task=task)

# Internal RCON broadcast helpers
def _sync_send_rcon(host: str, port: int, password: str, command: str, task: bool = False) -> str:
    try:
        with MCRcon(host, password, port=port) as mcr:
            response = mcr.command(command)
            return response
    except Exception as e:
        Logger.warning(f"Failed to broadcast command \"{command}\" to \"{host}:{port}\".", str(e), task=task)
        return "ERROR"

# Internal RCON helper function
def _sync_check_rcon(host: str, port: int, password: str, task: bool = False) -> bool:
    try:
        with MCRcon(host, password, port=port):
            return True
    except Exception as e:
        Logger.warning(f"RCON check failed for \"{host}:{port}\".", str(e), task=task)
        return False
