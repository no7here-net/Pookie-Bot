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

import discord

from typing import Literal
from discord import app_commands
from discord.ext import commands, tasks

import utilities.database as db

from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.config import config
from utilities.helpers import is_admin
from utilities.minecraft import whitelist_logic, blacklist_logic, check_rcon, unwhitelist_user

class Minecraft(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Starts server_monitor when cog starts
        self.vc_status = None
        self.server_states = {}
        self.server_monitor.start()

        # Start whitelist reconciliation sweeper when cog starts
        self.whitelist_sweeper.start()

    def cog_unload(self):
        self.server_monitor.cancel()
        self.whitelist_sweeper.cancel()

    @app_commands.command(name="whitelist", description="Add or remove an account from the Minecraft server whitelist.")
    @app_commands.describe(mc_username="Minecraft username to target.", action="Whether to add or remove the account from the whitelist.")
    @app_commands.rename(mc_username="username")
    async def whitelist(self, interaction: discord.Interaction, action: Literal["Add", "Remove"], mc_username: str):
        # Prevent Discord timing out
        await interaction.response.defer(ephemeral=True)

        # Send info to logic
        result = await whitelist_logic(self.bot, action, interaction.user.id, mc_username)

        if not result.get("success"):
            # Error message already ends with a full stop
            embed = Embeds.error(result.get("error"))

            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # If successful, create fancy embed
        if action == "Add":
            embed = Embeds.success(f"`{mc_username}` (`{result.get("uuid")}`) linked & whitelisted.")
        else:
            embed = Embeds.success(f"`{mc_username}` (`{result.get("uuid")}`) has been unlinked & removed from the whitelist.")

        # Catch incase unable to find avatar of skin from either API
        if result.get("avatar"):
            embed.set_thumbnail(url=result.get("avatar"))

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="blacklist", description="Add or remove an account from the Minecraft server blacklist.")
    @app_commands.describe(mc_username="Minecraft username to target.", action="Whether to add or remove the account from the blacklist.", reason="Why you're taking this action.")
    @app_commands.rename(mc_username="username")
    async def blacklist(self, interaction: discord.Interaction, action: Literal["Add", "Remove"], mc_username: str, reason: str):
        # Require bot admin / user ban perms to run ban action
        if not (interaction.user.guild_permissions.ban_members or is_admin(interaction.user.id)):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) tried to {action.lower()} the Minecraft account \"{mc_username}\" for the reason \"{reason}\" but was blocked as they do not have permission.")
            embed = Embeds.error("You don't have permission to do that.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        else:
            # Prevent Discord timing out
            await interaction.response.defer(ephemeral=True)

            # Send info to logic
            result = await blacklist_logic(self.bot, action, interaction.guild.id, interaction.user.id, mc_username, reason)

            if not result.get("success"):
                # Error message already ends with a full stop
                embed = Embeds.error(result.get("error"))

                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Build description per action to make wording match what happened
            if action == "Add":
                discord_link = f" Linked Discord account <@{result.get('user_id')}> was unlinked & removed from the whitelist." if result.get("user_id") else ""

                description = f"`{mc_username}` (`{result.get('uuid')}`) blacklisted.{discord_link}"
            else:
                discord_link = f" The ban was linked to <@{result.get('user_id')}>." if result.get("user_id") else ""
                banned_by = f" Originally banned by <@{result.get('added_by_id')}>." if result.get("added_by_id") else ""

                description = f"`{mc_username}` (`{result.get('uuid')}`) removed from the blacklist.{discord_link}{banned_by}"

            embed = Embeds.success(description)

            # Catch incase unable to find avatar of skin from either API
            if result.get("avatar"):
                embed.set_thumbnail(url=result.get("avatar"))

            await interaction.followup.send(embed=embed, ephemeral=True)

    # Clean up the whitelist when a member leaves, is kicked or banned
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Only react to guilds that are actually in the config
        if not any(s.get("guild_id") == member.guild.id for s in config.get("servers") or []):
            return

        # If they're still a member of another configured guild, their whitelist access stays
        for server_config in config.get("servers") or []:
            guild_id = server_config.get("guild_id")

            if guild_id and guild_id != member.guild.id:
                guild = self.bot.get_guild(guild_id)

                if guild and guild.get_member(member.id):
                    return

        # Logging & error handling all happen inside unwhitelist_user()
        await unwhitelist_user(self.bot, member.id, f"left or was removed from \"{member.guild.name}\"")

    # Runs immediately on start-up to prevent missed on_member_remove() events from downtime
    @tasks.loop(hours=1)
    async def whitelist_sweeper(self):
        try:
            guilds = []

            for server_config in config.get("servers") or []:
                guild_id = server_config.get("guild_id")

                # Catch for malformed configs
                if not guild_id:
                    continue

                guild = self.bot.get_guild(guild_id)

                # Prevent false removals if Discord's potato server goes down
                if not guild or guild.unavailable:
                    Logger.warning(f"Configured server (ID: {guild_id}) is unavailable. Aborting whitelist sweep this run to prevent false removals.", task=True)
                    return

                # Attempt to fill cache
                if not guild.chunked:
                    try:
                        await guild.chunk()
                    except Exception:
                        Logger.warning(f"Failed to fetch the full member list for \"{guild.name}\" (ID: {guild.id}). Aborting whitelist sweep this run to prevent false removals.", task=True)
                        return

                guilds.append(guild)

            # With no configured guilds there is nothing to reconcile against
            if not guilds:
                return

            # Fetch all linked accounts
            try:
                async with db.conn_pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT user_id FROM mc_accounts")
                        linked_users = await cur.fetchall()
            except Exception:
                Logger.warning("Whitelist sweeper failed to fetch linked accounts from the database.", task=True)
                return

            for entry in linked_users:
                user_id = entry[0]

                # Skip anyone still in at least one configured guild
                if any(guild.get_member(user_id) for guild in guilds):
                    continue

                # Logging & error handling all happen inside unwhitelist_user()
                await unwhitelist_user(self.bot, user_id, "no longer in any configured server (offline-gap sweep)", task=True)
        except Exception as e:
            Logger.warning("A critical error occurred whilst running the whitelist sweeper task, but was caught by the global task exception capture to prevent the task stopping.", str(e), task=True)

    # Continuously monitors Minecraft servers / proxy if populated
    @tasks.loop(minutes=5)
    async def server_monitor(self):
        try:
            server_list = (config.get("minecraft") or {}).get("servers") or {}

            # If there are no servers to check, save resources and stop the routine
            if not server_list:
                self.server_monitor.cancel()
                return

            results = await check_rcon(task=True)

            # Empty result means every configured server failed validation inside check_rcon()
            if not results:
                return

            # Check that the result is valid
            for name, current_state in results.items():
                previous_state = self.server_states.get(name)

                # If the state changed and it's not the first run
                if previous_state and previous_state != current_state:
                    # Make names slightly more pretty
                    pretty_name = "Velocity (proxy)" if name == "velocity" else name.capitalize()

                    # Generate Embeds and Logs based on state transition
                    if current_state:
                        embed = Embeds.success(f"**{pretty_name}** is back online.")
                        Logger.info(f"\"{name}\" was detected as online during routine RCON ping.", task=True)
                    else:
                        embed = Embeds.warning(f"**{pretty_name}** has gone offline.")
                        Logger.warning(f"\"{name}\" was detected as offline during routine RCON ping.", task=True)

                    # Broadcast to all Discord servers with an mc_chat channel configured
                    for server_config in (config.get("servers") or []):
                        channel_id = (server_config.get("channels") or {}).get("mc_chat")

                        if channel_id:
                            # Use discord.py cache to avoid spamming API
                            channel = self.bot.get_channel(channel_id)

                            if channel:
                                try:
                                    await channel.send(embed=embed)
                                except Exception:
                                    Logger.warning(f"\"{name}\" Minecraft server status update could not be sent to channel (ID: {channel_id}).", task=True)

                # Update the memory state for the next check
                self.server_states[name] = current_state

            # Get only velocity status
            velocity_status = results.get("velocity", False)

            # Calculate how many backend servers exist, except for velocity
            backend_servers = [state for name, state in results.items() if name != "velocity"]

            # Count server totals
            online_count = backend_servers.count(True)
            total_count = len(backend_servers)

            # If velocity is offline / all servers are offline, display as unavailable
            if not velocity_status or online_count == 0:
                new_status = "🔴・Unavailable"

            # If velocity is online & not all servers are online (but at least 1 is)
            elif online_count < total_count:
                new_status = "🟡・Partial Outage"

            # If velocity is online & all servers are online
            else:
                new_status = "🟢・Online"

            # Change VC name if it does NOT match
            if new_status != self.vc_status:
                for server_cfg in (config.get("servers") or []):
                    channel_id = (server_cfg.get("channels") or {}).get("mc_status")

                    if channel_id:
                        channel = self.bot.get_channel(channel_id)

                        if channel:
                            try:
                                # Only rename is the status changes to avoid API spam
                                if channel.name != new_status:
                                    await channel.edit(name=new_status)
                            except Exception:
                                Logger.warning(f"Minecraft server VC status update failed for channel (ID: {channel_id}).", task=True)

                # Save the new status to memory
                self.vc_status = new_status
        except Exception as e:
            Logger.warning("A critical error occurred whilst running the Minecraft server monitor task, but was caught by the global task exception capture to prevent the task stopping.", str(e), task=True)

    # Ensure bot & cache is ready first before task starts
    @server_monitor.before_loop
    async def before_server_monitor(self):
        await self.bot.wait_until_ready()

    # Ensure bot & cache is ready first before task starts
    @whitelist_sweeper.before_loop
    async def before_whitelist_sweeper(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Minecraft(bot))
