import discord
import os

from discord.ext import commands
from discord import app_commands

from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.helpers import config, is_verified
from utilities.interactions import VerificationView

import utilities.database as db

class PookieBot(commands.Bot):
    def __init__(self):
        # Prefix doesn't do anything, however prevents performance issues with analysis on every message (which would happen if left blank)
        super().__init__(command_prefix="//", intents=discord.Intents.all(), help_command=None)
        self._login_logged = False # Guard flag to prevent multiple on_ready messages

    async def setup_hook(self):
        await db.init_db()

        # Check database actually initialised and is usable
        if db.conn_pool is None:
            Logger.error("Failed to initialise database.")
            raise SystemExit(1)

        # Hook slash command errors directly to command tree
        self.tree.on_error = self.on_app_command_error

        # Global permission check
        self.tree.interaction_check = is_verified

        # Add persistent views for interactions
        self.add_view(VerificationView())

        # Fetch all modules and their state from the config
        module_config = config.get("modules") or {}

        # If the module is enabled, load it
        for module_name, module_state in module_config.items():
            if module_state:
                try:
                    await self.load_extension(f"modules.{module_name}")
                    Logger.success(f"Loaded \"{module_name}\".")
                except Exception as e:
                    Logger.error(f"Failed to load \"{module_name}\". Check log.", str(e))

        # Sync bot commands to Discord
        try:
            synced = await self.tree.sync()
            Logger.info(f"Synced {len(synced)} commands.")
        except Exception as e:
            Logger.error("Failed to sync commands. Check log.", str(e))

    # Legacy command error handler
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            return
        if ctx.command is None:
            return
        Logger.error(f"\"{ctx.author.name}\" (ID: {ctx.author.id}) triggered an unexpected error in the command \"{ctx.command}\". Check log.", str(error))

    # Slash command error handler
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        cmd_name = interaction.command.name if interaction.command else "unknown"

        # If user is missing permissions
        if isinstance(error, app_commands.MissingPermissions):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) was blocked from executing \"{cmd_name}\" as they were missing command-specific permissions.")

            embed = Embeds.error("You don't have permission to do that.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # If bot is missing permissions
        elif isinstance(error, app_commands.BotMissingPermissions):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) attempted to run \"{cmd_name}\" but the bot was missing permissions.")

            embed = Embeds.error("I don't have permission to do that.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # If user is executing commands too fast
        elif isinstance(error, app_commands.CommandOnCooldown):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) was ratelimited from executing the command \"{cmd_name}\" for {error.retry_after:.1f} seconds.")

            embed = Embeds.error(f"You've been rate limited. Try again in {error.retry_after:.1f} seconds.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # If user fails global permission checks
        elif isinstance(error, app_commands.CheckFailure):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) was blocked from executing \"{cmd_name}\" as they were missing required global permissions.")

            embed = Embeds.error("You don't have permission to do that.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Handle generic error messages
        else:
            Logger.error(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) triggered an unexpected error in the command \"{cmd_name}\". Check log.", str(error))

            embed = Embeds.error("An unexpected error occurred.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

    async def on_ready(self):
        if not self._login_logged:
            self._login_logged = True
            Logger.info(f"Connected to Discord as \"{self.user.name}#{self.user.discriminator}\" (ID: {self.user.id}).")

bot = PookieBot()

if __name__ == "__main__":
    # Fetch non-sensitive environment key name
    env_key = (config.get("auth") or {}).get("discord_token")
    # Check if the key exists and if the environment has a value for it
    if not env_key or not os.environ.get(env_key):
        Logger.error("Bot failed to login. Missing token key in config or environment.")
        raise SystemExit(1)
    try:
        # Pass the token inline
        bot.run(os.environ.get(env_key), log_handler=None)
    except Exception as e:
        Logger.error("Bot failed to login. Check log.", str(e))
        raise SystemExit(1)
