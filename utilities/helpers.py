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

from utilities.output import Logger

# Load static config
def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

config = load_config()

# Add a function to reload config
def reload_config():
    # Import global config variable
    global config
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

# ===============
# COMMAND HELPERS
# ===============

# Check for if user is a bot admin
def is_admin(user_id: int) -> bool:
    return user_id in (config.get("admins") or [])

# Fetch emoji ID by name
def get_emoji(name: str) -> str:
    customisation = config.get("customisation") or {}
    emojis = customisation.get("emojis") or {}
    return emojis.get(name)

# Fetch HEX colours and convert to integers for discord.py
def get_colour(name: str) -> int:
    customisation = config.get("customisation") or {}
    colours = customisation.get("colours") or {}
    value = colours.get(name)
    return int(value if value else "2fbffd", 16)

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

async def is_verified(interaction: discord.Interaction) -> bool:
    # Bot admin bypass
    if interaction.user.id in (config.get("admins") or []):
        return True

    # Block DMs (prevents crashes on next part)
    if not interaction.guild:
        return False

    # Match server in config
    server_config = next((s for s in config.get("servers") or [] if s.get("guild_id") == interaction.guild.id), {}) or {}

    # Handle unknown guilds
    if not server_config:
        return False

    # Find verified role in server
    verified_role_id = (server_config.get("roles") or {}).get("verified")

    # Check user has the role
    for role in interaction.user.roles:
        if role.id == verified_role_id:
            return True

    # If any checks fail, block
    return False

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
