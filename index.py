import discord
import asyncio
import os

from discord.ext import commands
from discord import app_commands

from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.helpers import config, is_verified
from utilities.database import init_db
from utilities.interactions import VerificationView

class PookieBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="", intents=discord.Intents.all(), help_command=None)

    async def setup_hook(self):
        await init_db()

        # Hook slash command errors directly to command tree
        self.tree.on_error = self.on_app_command_error

        # Global permission check
        self.tree.interaction_check = is_verified

        # Add persistent views for interactions
        self.add_view(VerificationView())

        # Fetch all modules and their state from the config
        module_config = config.get("modules", {})

        # If the module is enabled, load it
        for module_name, module_state in module_config.items():
            if module_state:
                try:
                    await self.load_extension(f"modules.{module_name}")
                    Logger.success(f"Loaded {module_name}")
                except Exception as e:
                    Logger.error(f"Failed to load {module_name}. Check log.", str(e))

        # Sync bot commands to Discord
        try:
            synced = await self.tree.sync()
            Logger.info(f"Synced {len(synced)} commands")
        except Exception as e:
            Logger.error(f"Failed to sync commands. Check log.", str(e))

    # Legacy command error handler
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            return
        Logger.error(f"Ignoring exception in command {ctx.command}. Check log.", error)

    # Slash command error handler
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # If user is missing permissions
        if isinstance(error, app_commands.MissingPermissions):
            embed = Embeds.error(f"You don't have permission to do that.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # If bot is missing permissions
        elif isinstance(error, app_commands.BotMissingPermissions):
            embed = Embeds.error(f"I don't have permission to do that.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # If user is executing commands too fast
        elif isinstance(error, app_commands.CommandOnCooldown):
            embed = Embeds.error(f"You've been rate limited. Try again in {error.retry_after:.1f} seconds.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # If user fails global permission checks
        elif isinstance(error, app_commands.CheckFailure):
            embed = Embeds.error("You must be verified to use commands in this server.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Handle generic error messages
        else:
            embed = Embeds.error(f"An unexpected error occurred.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

    async def on_ready(self):
        Logger.info(f"Connected to Discord as \"{self.user.name}#{self.user.discriminator}\" (ID: {self.user.id})")

client = PookieBot()

if __name__ == "__main__":
    client.run(os.environ.get(config["auth"]["discord_token"]), log_handler=None)
