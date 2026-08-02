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

from discord import app_commands

from utilities.output import Logger

# Load static config
def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

config = load_config()

# Add a function to reload config
def reload_config():
    try:
        # Load the new config into a temporary variable first
        new_config = load_config()

        # Check if the new config is empty (e.g., if the file was totally blank)
        if not new_config:
            Logger.warning("Config reload aborted: config.json is empty.")
            return False

        # Update config after passing check
        config.clear()
        config.update(new_config)

        return True

    except (FileNotFoundError, json.JSONDecodeError) as e:
        # Catch missing files or broken JSON formatting, keeping the old config safe
        Logger.error("Failed to reload config.json. The previous config has been kept until reboot. Check log.", str(e))
        return False

# =================
# SCRIPT LEVEL DEFS
# =================

# DB import is here to prevent circular import crashes
import utilities.database as db

customisation = config.get("customisation") or {}

# ===============
# COMMAND HELPERS
# ===============

# Formats time for logging
def format_duration(seconds: float, max_units: int = 2) -> str:
    seconds = int(seconds)
    if seconds <= 0:
        return "a moment"

    parts = []
    for name, size in (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        value, seconds = divmod(seconds, size)
        if value:
            parts.append(f"{value} {name}{"s" if value != 1 else ""}")

    parts = parts[:max_units]
    if len(parts) == 1:
        return parts[0]
    return f"{", ".join(parts[:-1])} and {parts[-1]}"

# Check for if user is a bot admin
def is_admin(user_id: int) -> bool:
    return user_id in (config.get("admins") or [])

# Check if a user is currently quarantined
async def is_quarantined(guild_id: int, user_id: int) -> bool | None:
    try:
        async with db.conn_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 FROM quarantine WHERE user_id = %s AND guild_id = %s LIMIT 1", (user_id, guild_id,))
                return await cur.fetchone() is not None
    except Exception as e:
        # Fail close
        Logger.warning(f"Failed to check quarantine status for user (ID: {user_id}) in server (ID: {guild_id}). Check log.", str(e))
        return None

# Fetch emoji ID by name
def get_emoji(name: str) -> str:
    emojis = customisation.get("emojis") or {}
    return emojis.get(name)

# Fetch HEX colours and convert to integers for discord.py
def get_colour(name: str) -> int:
    colours = customisation.get("colours") or {}
    value = colours.get(name)
    return int(value if value else "2fbffd", 16)

# Fetch server configs
def get_guild_config(guild_id: int) -> dict:
    return next((s for s in config.get("servers") or [] if s.get("guild_id") == guild_id), {}) or {}

# Fetch username by using their Discord ID (useful for when someone has left server for example)
async def fetch_username(client: discord.Client, user_id: int) -> str:
    try:
        user = await client.fetch_user(user_id)
        return user.name
    except discord.NotFound:
        return "Unknown User"
    except discord.HTTPException:
        # Prevents ratelimits or Discord API outages from crashing the bot
        return "Unknown User (API Error)"

# ===============
# STATUS CHECKERS
# ===============

# Check Cloudflare DNS & Google DNS for internet connectivity
async def check_internet() -> bool:
    results = await asyncio.gather(
        _ping_host("1.1.1.1"),
        _ping_host("8.8.8.8")
    )

    # Return true if at least one is true
    return any(results)

# Check hosts by checking SSH list in config
async def check_host() -> dict:
    # Create a list of host IP/domain of each server
    hostnames = [server.get("host") for server in (config.get("auth") or {}).get("ssh") or [] if server.get("host")]

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

# Globally forces all commands to pass all conditions for each interaction
async def is_verified(interaction: discord.Interaction) -> bool:
    # Bot admin bypass
    if interaction.user.id in (config.get("admins") or []):
        return True

    # Match server in config
    server_config = get_guild_config(interaction.guild.id)

    # Handle unknown guilds
    if not server_config:
        raise app_commands.CheckFailure()

    # Find verified role in server
    verified_role_id = (server_config.get("roles") or {}).get("verified")

    # Check user has the role
    for role in interaction.user.roles:
        if role.id == verified_role_id:
            return True

    # If any checks fail, block
    raise app_commands.CheckFailure()

# ================
# INTERNAL HELPERS
# ================

# Internal ping helper function
async def _ping_host(host: str) -> bool:
    # Creates a background process: ping -c 4 <host>
    process = await asyncio.create_subprocess_exec(
        "ping", "-c", "4", host,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )

    try:
        # Timeout if it takes too long
        await asyncio.wait_for(process.wait(), timeout=6)
        return process.returncode == 0
    except Exception:
        # Log failure
        Logger.warning(f"Background sub-process ping to \"{host}\" failed.")

        try:
            # Prevent ghost sub-processes
            process.kill()

            # Prevent Linux kernel keeping zombie process open for status code reading
            await process.wait()
        except Exception:
            Logger.warning(f"Failed to kill background sub-process ping to \"{host}\". Did it spawn?")
        return False

# Verify emojis are present and working
for name in ["success", "warning", "error", "info"]:
    customisation = config.get("customisation") or {}
    emojis = customisation.get("emojis") or {}

    if not emojis.get(name):
        Logger.error(f"Failed to find emoji \"{name}\" in config.json.")
        raise SystemExit(1)
