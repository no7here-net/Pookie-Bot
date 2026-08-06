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

# Handle various misc. parts of bot
# - Bot admin check
# - Username fetcher
# - Duration formatter
# - Quarantine check
# - Status checkers
#   - Cloudflare & Google DNS checks for internet connectivity... I get the irony of it being a Discord bot ok
#   - SSH access check

import discord
import asyncio
import uuid

from discord import app_commands

from utilities.config import config, get_guild_config
from utilities.output import Logger

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
    return dict(zip(hostnames, results, strict=True))

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
