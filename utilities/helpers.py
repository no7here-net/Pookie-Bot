# Handle various misc. parts of bot
# - Bot admin check
# - Emoji finder
# - HEX converter (for embed colours)
# - Username fetcher
# - Status checkers
#   - Cloudflare & Google DNS checks for internet connectivity... I get the irony of it being a Discord bot ok
#   - SSH access check

import discord
import asyncio
import json
import os

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

config = load_config()

# ===============
# COMMAND HELPERS
# ===============

# Check for if user is a bot admin
def is_admin(user_id: int) -> bool:
    return user_id in config.get("admins", [])

# Fetch emoji ID by name
def get_emoji(name: str) -> str:
    return config.get("customisation", {}).get("emojis", {}).get(name, "")

# Fetch HEX colours and convert to integers for discord.py
def get_colour(name: str) -> int:
    return int(config.get("customisation", {}).get("colours", {}).get(name, "2fbffd"), 16)

# Fetch username by using their Discord ID (useful for when someone has left server for example)
async def fetch_username(client: discord.Client, user_id: int) -> str:
    try:
        user = await client.fetch_user(user_id)
        return user.global_name or user.name
    except discord.NotFound:
        return "Unknown User"

# ===============
# STATUS CHECKERS
# ===============

# Check Cloudflare DNS & Google DNS for internet connectivity
async def check_internet() -> bool:
    results = await asyncio.gather(
        _ping_host("1.1.1.1", 53),
        _ping_host("8.8.8.8", 53)
    )

    # Return true if at least one is true
    return any(results)

# Check hosts by checking SSH list in config
async def check_host() -> dict:
    # Create a list of host IP/domain of each server
    hostnames = [server.get("host") for server in config.get("auth", {}).get("ssh", []) if server.get("host")]

    # If there are no servers, return nothing
    if not hostnames:
        return {}

    # Ping servers at same time
    ping_tasks = [_ping_host(host) for host in hostnames]
    results = await asyncio.gather(*ping_tasks)

    # Create KV dictionary of hostnames and results
    return dict(zip(hostnames, results))

# ==================
# PERMISSION CHECKER
# ==================

def is_verified(interaction: discord.Interaction) -> bool:
    # Bot admin bypass
    if interaction.user.id in config.get("admins", []):
        return True

    # Block DMs (prevents crashes on next part)
    if not interaction.guild:
        return False

    # Match server in config
    server_config = None
    for server in config.get("servers", []):
        if server.get("guild") == interaction.guild.id:
            server_config = server
            break

    # Find verified role in server
    verified_role_id = server_config.get("roles", {}).get("verified")

    # Check user has the role
    for role in interaction.user.roles:
        if role.id == verified_role_id:
            return True

    # If any cheks fail, block
    return False

# ================
# INTERNAL HELPERS
# ================

# Internal ping helper function
async def _ping_host(host: str) -> bool:
    try:
        # Creates a background process: ping -c 1 <host>
        process = await asyncio.create_subprocess_exec(
            "ping", "-c", "4", host,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await process.wait()
        return process.returncode == 0
    except Exception:
        return False
