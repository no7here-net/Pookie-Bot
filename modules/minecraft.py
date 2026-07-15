import asyncio
import discord

from discord import app_commands
from discord.ext import commands, tasks

from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.helpers import config
from utilities.minecraft import whitelist_logic, unlink_logic, check_rcon

class Minecraft(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.server_online = True

        # Starts server_monitor when cog starts
        self.vc_status = None
        self.server_states = {}
        self.server_monitor.start()

    def cog_unload(self):
        self.server_monitor.cancel()

    @app_commands.command(name="whitelist", description="Whitelist an account to the Minecraft server")
    @app_commands.describe(mc_username="Minecraft username to whitelist.")
    @app_commands.rename(mc_username="username")
    async def whitelist(self, interaction: discord.Interaction, mc_username: str):
        # Prevent Discord timing out
        await interaction.response.defer(ephemeral=True)

        Logger.info(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) is attempting to whitelist \"{mc_username}\".")

        # Send info to logic
        result = await whitelist_logic(self.bot, interaction.user.id, mc_username)

        if not result.get("success"):
            # Error message already ends with a full stop
            embed = Embeds.error(result.get("error"))

            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # If successful, create fancy embed
        embed = Embeds.success(f"`{mc_username}` (`{result.get("uuid")}`) linked & whitelisted.")

        # Catch incase unable to find avatar of skin from either API
        if result.get("avatar"):
            embed.set_thumbnail(url=result.get("avatar"))

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="unlink", description="Unlink your account from the Minecraft server")
    @app_commands.describe(mc_username="Minecraft username to unlink.")
    @app_commands.rename(mc_username="username")
    async def unlink(self, interaction: discord.Interaction, mc_username: str):
        # Prevent Discord timing out
        await interaction.response.defer(ephemeral=True)

        Logger.info(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) is attempting to unlink \"{mc_username}\".")

        # Send info to logic
        result = await unlink_logic(self.bot, interaction.user.id, mc_username)

        if not result.get("success"):
            # Error message already ends with a full stop
            embed = Embeds.error(result.get("error"))
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # If successful, create fancy embed
        embed = Embeds.success(f"`{mc_username}` (`{result.get("uuid")}`) has been unlinked and removed from the whitelist.")

        # Catch incase unable to find avatar of skin from either API
        if result.get("avatar"):
            embed.set_thumbnail(url=result.get("avatar"))

        await interaction.followup.send(embed=embed, ephemeral=True)

    @tasks.loop(minutes=5)
    async def server_monitor(self):
        try:
            results = await check_rcon(task=True)

            # Check that the result is valid
            if results is not None:
                for name, current_state in results.items():
                    previous_state = self.server_states.get(name)

                    # If the state changed and it's not the first run
                    if previous_state is not None and previous_state != current_state:
                        # Make names slightly more pretty
                        pretty_name = "Velocity (proxy)" if name == "velocity" else name.capitalize()

                        # Generate Embeds and Logs based on state transition
                        if current_state:
                            embed = Embeds.success(f"**{pretty_name}** is back online.")
                            Logger.info(f"\"{name}\" was detected as online during routine RCON ping.", task=True)
                        else:
                            embed = Embeds.error(f"**{pretty_name}** has gone offline.")
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
            else:
                Logger.warning("Detected result is missing from check_rcon() function. Ignoring this run.", task=True)
        except Exception as e:
            Logger.warning("A critical error occurred whilst running the Minecraft server monitor task, but was caught by the global task exception capture to prevent the task stopping.", str(e), task=True)

    # Ensure bot & cache is ready first before task starts
    @server_monitor.before_loop
    async def before_server_monitor(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Minecraft(bot))
