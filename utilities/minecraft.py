import asyncio
import aiohttp
import os

from mcrcon import MCRcon
from utilities.output import Logger
from utilities.helpers import config

# Check Minecraft host(s)
async def check_rcon() -> dict:
    # Fetch Minecraft server list from config
    mc_servers = config.get("minecraft", {}).get("servers", {})

    # If there are no servers, return nothing
    if not mc_servers:
        return {}

    # Create dictionary for server names
    server_names = []

    # Create dictionary for status to be added to
    rcon_tasks = []

    # Iterates through all servers in config
    for name, info in mc_servers.items():
        server_names.append(name)

        # Fetch password from environment variable
        password = os.environ.get(info.get("rcon_password"))

        # Queue a background task using internal rcon function
        rcon_tasks.append(asyncio.to_thread(_sync_check_rcon, info.get("address"), info.get("rcon_port"), password))

    # Run RCON connections simultaneously
    results = await asyncio.gather(*rcon_tasks)

    # Return a KV dictionary
    return dict(zip(server_names, results))

# Fetches and links Minecraft & Discord account together
async def mc_info(discord_id: str, mc_name: str) -> dict:
    # Fetch unique (and unchangeable) ID for the MC account
    uuid = await _fetch_mc_uuid(mc_name)

    # If it fails to fetch the UUID, error out
    if uuid == "failed":
        return {
            "success": False,
            "error": "Failed to find Minecraft account."
        }

    # Database security checks
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Has user already linked an account
            await cur.execute("SELECT MC_uuid FROM mc_accounts WHERE discord_id = %s", (discord_id,))

            if await cur.fetchone():
                return {
                    "success": False,
                    "error": "Your Discord account is already linked to a Minecraft account."
                }

            # Is this account matched with someone else
            await cur.execute("SELECT discord_id FROM mc_accounts WHERE mc_uuid = %s", (uuid,))

            if await cur.fetchone():
                return {
                    "success": False,
                    "error": "This Minecraft account is already linked to another Discord account."
                }

            # Is the Minecraft account banned
            await cur.execute("SELECT reason FROM mc_bans WHERE mc_uuid = %s", (uuid,))

            ban = await cur.fetchone()

            if ban:
                return {
                    "success": False,
                    "error": "This Minecraft account is banned."
                }

            # If checks pass
            response = await _send_velocity_command(f"whitelist add {mc_name}")

            if "ERROR" in response:
                return {
                    "success": False,
                    "error": f"Failed to execute whitelist command."
                }

            await cur.execute("INSERT INTO mc_accounts (discord_id, mc_uuid) VALUES (%s, %s)", (discord_id, uuid,))

    # Fetch MC avatar from skin
    avatar = await _fetch_mc_avatar(uuid)

    # Return info
    return {
        "success": True,
        "uuid": uuid,
        "avatar": avatar,
    }

# ================
# INTERNAL HELPERS
# ================

# Fetches UUID from username using official API
async def _fetch_mc_uuid(name: str) -> str:
    async with aiohttp.ClientSession() as session:
        try:
            async with session.head("https://api.mojang.com/users/profiles/minecraft/" + name) as response:
                if response.status == 200:
                    return await (response.json().get("id", "failed"))
        except Exception:
            return "failed"

# Fetches avatar by trying multiple 3rd party services
async def _fetch_mc_avatar(uuid: str) -> str:
    # APIs in order of preference
    apis = [
        f"https://minotar.net/avatar/{uuid}",
        f"https://mc-heads.net/avatar/{uuid}"
    ]

    # Try all domains with a timeout of 2
    async with aiohttp.ClientSession() as session:
        for url in apis:
            try:
                async with session.get(url, timeout=2) as response:
                    if response.status == 200:
                        return url
            except Exception:
                continue

# Send a command to Velocity
async def _send_velocity_command(command: str) -> str:
    # Find velocity info from config
    velocity = config.get("minecraft", {}).get("servers", {}).get("velocity")

    # If there isn't a velocity entry in the config, return nothing
    if not velocity:
        return "ERROR: Velocity server not found in config."

    # Fetch password from environment variables
    password = os.environ.get(velocity.get("rcon_password"), "")

    # Return direct result from _rcon_send function
    return await asyncio.to_thread(_send_rcon, velocity.get("address"), velocity.get("rcon_port"), password, command)

# Internal RCON broadcast helpers
def _send_rcon(host: str, port: int, password: str, command: str) -> str:
    try:
        with MCRcon(host, password, port=port) as mcr:
            response = mcr.command(command)
            return response
    except Exception as e:
        return "ERROR: " + str(e)

# Internal RCON helper function
def _sync_check_rcon(host: str, port: int, password: str) -> bool:
    try:
        with MCRcon(host, password, port=port) as mcr:
            return True
    except Exception:
        return False
