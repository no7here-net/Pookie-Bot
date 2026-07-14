# Minecraft functions
# Handles RCON check, whitelist, blacklist (when done) and RCON commands

import discord
import asyncio
import aiohttp
import os
import re

from urllib.parse import urlparse
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

# Fetches and links Minecraft & Discord account together
async def whitelist_logic(client: discord.Client, user_id: int, mc_username: str) -> dict:
    # Fetch Discord username from ID provided in attributes. Safe to do here as its value is guarded by the functions that trigger this one.
    username = await fetch_username(client, user_id)

    if not re.match(r"^[a-zA-Z0-9_]{2,16}$", mc_username):
        Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from linking the Minecraft account \"{mc_username}\" due to invalid characters in their Minecraft username.")

        return {
            "success": False,
            "error": "Invalid Minecraft username. Usernames can only contain letters, numbers, and underscores."
        }

    # Fetch unique (and unchangeable) ID for the MC account
    mc_uuid = await _fetch_mc_uuid(mc_username)

    # If it fails to fetch the UUID, error out
    if mc_uuid in ("failed", "unknown"):
        Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from linking the Minecraft account \"{mc_username}\" as their UUID could not be found.")

        return {
            "success": False,
            "error": "Failed to find Minecraft account."
        }

    # Database security checks
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Is the Minecraft account banned
                await cur.execute("SELECT reason FROM mc_bans WHERE mc_uuid = %s", (mc_uuid,))

                mc_ban_reason = await cur.fetchone()

                if mc_ban_reason:
                    Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from linking the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) as it is banned.")

                    return {
                        "success": False,
                        "error": "This Minecraft account is banned."
                    }

                # Is the Discord account linked to a banned Minecraft account
                await cur.execute("SELECT reason FROM mc_bans WHERE user_id = %s", (user_id,))

                discord_ban_reason = await cur.fetchone()

                if discord_ban_reason:
                    Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from linking the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) as they are banned from linking accounts.")

                    return {
                        "success": False,
                        "error": "This Discord account is linked to a banned Minecraft account."
                    }

                # Has user already linked an account
                await cur.execute("SELECT mc_uuid FROM mc_accounts WHERE user_id = %s", (user_id,))

                result = await cur.fetchone()

                if result:
                    # Fetch linked account
                    linked_mc_uuid = result[0]
                    linked_mc_username = await _fetch_mc_username(linked_mc_uuid)

                    if linked_mc_username in ("failed", "unknown"):
                        return {
                            "success": False,
                            "error": "Failed to reach Mojang's API for account information."
                        }

                    Logger.warning(f"\"{username}\" (ID: {user_id}) is already linked to the Minecraft account \"{linked_mc_username}\" (UUID: {linked_mc_uuid}).")

                    return {
                        "success": False,
                        "error": "Your Discord account is already linked to a Minecraft account."
                    }

                # Is this account matched with someone else
                await cur.execute("SELECT user_id FROM mc_accounts WHERE mc_uuid = %s", (mc_uuid,))

                result = await cur.fetchone()

                if result:
                    # Fetch account details of the Discord account the Minecraft account is already linked to
                    linked_user_id = result[0]
                    linked_username = await fetch_username(client, linked_user_id)

                    Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from linking the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}) as it is already connected to another account \"{linked_username}\" (ID: {linked_user_id}).")

                    return {
                        "success": False,
                        "error": "This Minecraft account is already linked to another Discord account."
                    }
    except Exception:
        Logger.warning(f"\"{username}\" (ID: {user_id}) was blocked from linking the Minecraft account \"{mc_username}\" due to an exception when accessing the database.")

        return {
            "success": False,
            "error": "Failed to connect to database to perform checks."
        }

    # If checks pass
    response = await _send_velocity_command(f"whitelist add {mc_username}")

    Logger.info(f"\"{username}\" (ID: {user_id}) attempted to add the Minecraft account \"{mc_username}\" to the whitelist. Pushing response to log file.", response)

    # Check response
    if "Added " not in response:
        Logger.warning(f"\"{username}\" (ID: {user_id}) failed to execute whitelist command for the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}).")

        return {
            "success": False,
            "error": "Failed to execute whitelist command on the server."
        }

    # Update database & handle any possible issues
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO mc_accounts (user_id, mc_uuid) VALUES (%s, %s)", (user_id, mc_uuid,))
    except Exception:
        Logger.warning(f"\"{username}\" (ID: {user_id}) did pass whitelist logic and has been whitelisted, but an error occurred when updating the database with the Minecraft account \"{mc_username}\" (UUID: {mc_uuid}).")

    # Fetch MC avatar from skin
    mc_avatar = await _fetch_mc_avatar(mc_username, mc_uuid)

    Logger.info(f"\"{username}\" (ID: {user_id}) successfully whitelisted \"{mc_username}\" (UUID: {mc_uuid}).")

    # Return info
    return {
        "success": True,
        "uuid": mc_uuid,
        "avatar": mc_avatar,
    }

# ================
# INTERNAL HELPERS
# ================

# Fetches UUID from username using official API
async def _fetch_mc_uuid(mc_username: str) -> str:
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://api.mojang.com/users/profiles/minecraft/{mc_username}", timeout=aiohttp.ClientTimeout(total=2)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("id", "unknown")
                Logger.warning(f"Failed to fetch UUID for Minecraft username \"{mc_username}\" as response was not \"OK\" (Status: {response.status}).")
                return "failed"
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
