import discord
import asyncio
import os

from discord.ext import commands
from discord import app_commands

from utilities.helps import config, is_admin
from utilities.database import init_db
from utilities.embeds import Embeds
from utilities.output import Logger

class PookieBot(commands.Bot):
    def __init__(self):
        super().__init__(commands_prefix="", intents=discord.Intents.all(), help_command=None)

    async def setup_hook(self):
        await init_db()

        # Fetch all modules and their state from the config
        module_config = config.get("modules", {})

        # If the module is enabled, load it
        for module_name, module_state in module_config.items():
            if module_state:
                try:
                    await self.load_extension(f"modules.{module_name}")
                    Logger.success(f"Loaded {module_name}")
                except:
                    Logger.error(f"Failed to load {module_path}. Check log.", Exception)

        # Sync bot commands to Discord
        try:
            synced = await self.tree.sync()
            Logger.info(f"Synced {len(synced)} commands")
        except:
            Logger.error(f"Failed to sync commands. Check log.", Exception)

client = PookieBot()

# Legacy command error handler
@client.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        return
    Logger.error(f"Ignoring exception in command {ctx.command}. Check log.", {error})

# Slash command error handler
@client.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
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
    elif isinistance(error, app_commands.CommandOnCooldown):
        embed = Embeds.error(f"You've been rate limited. Try again in {error.retry_after:.1f} seconds.")

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

@client.event
async def on_ready():
    Logger.info(f"Connected to Discord as {client.user.name}#{client.user.discriminator}")

if __name__ == "__main__":
    client.run(os.environ.get(config["auth"]["discord_token"]), log_handler=None)
