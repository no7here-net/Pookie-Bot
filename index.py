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
import time
import os

from discord.ext import commands
from discord import app_commands

from utilities.config import config
from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.helpers import is_verified, format_duration
from utilities.interactions import VerificationView
from utilities.minecraft import close_http_session

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

        # Register every command as guild only so they don't show up in DMs
        for command in self.tree.walk_commands():
            command.guild_only = True

        # Sync bot commands to Discord
        try:
            synced = await self.tree.sync()
            Logger.info(f"Synced {len(synced)} commands.")
        except Exception as e:
            Logger.error("Failed to sync commands. Check log.", str(e))

    # Gracefully release shared resources when the bot shuts down
    async def close(self):
        # Close the shared HTTP session used for Mojang / avatar lookups
        try:
            await close_http_session()
        except Exception as e:
            Logger.warning("Failed to close the shared HTTP session cleanly.", str(e))

        # Close the database connection pool
        try:
            if db.conn_pool is not None:
                db.conn_pool.close()
                await db.conn_pool.wait_closed()
        except Exception as e:
            Logger.warning("Failed to close the database connection pool cleanly.", str(e))
        await super().close()

    # Legacy command error handler
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            return
        if ctx.command is None:
            return
        Logger.error(f"\"{ctx.author.name}\" (ID: {ctx.author.id}) triggered an unexpected error in the command \"{ctx.command}\". Check log.", str(error))

    # Shared responder for command errors
    async def _send_error_embed(self, interaction: discord.Interaction, description: str):
        embed = Embeds.error(description)

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # Slash command error handler
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        cmd_name = interaction.command.name if interaction.command else "unknown"

        # If user is missing permissions
        if isinstance(error, app_commands.MissingPermissions):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) was blocked from executing \"{cmd_name}\" as they were missing command-specific permissions.")
            await self._send_error_embed(interaction, "You don't have permission to do that.")

        # If bot is missing permissions
        elif isinstance(error, app_commands.BotMissingPermissions):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) attempted to run \"{cmd_name}\" but the bot was missing permissions.")
            await self._send_error_embed(interaction, "I don't have permission to do that.")

        # If user is executing commands too fast
        elif isinstance(error, app_commands.CommandOnCooldown):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) was ratelimited from executing the command \"{cmd_name}\" for {format_duration(error.retry_after)}.")
            await self._send_error_embed(interaction, f"You've been rate limited. Try again <t:{int(time.time() + error.retry_after)}:R>.")

        # If user fails global permission checks
        elif isinstance(error, app_commands.CheckFailure):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) was blocked from executing \"{cmd_name}\" as they were missing required global permissions.")
            await self._send_error_embed(interaction, "You don't have permission to do that.")

        # Handle generic error messages
        else:
            Logger.error(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) triggered an unexpected error in the command \"{cmd_name}\". Check log.", str(error))
            await self._send_error_embed(interaction, "An unexpected error occurred.")

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
        raise SystemExit(1) from None
