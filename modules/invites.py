import discord

from discord.ext import commands, tasks

import utilities.database as db

from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.helpers import config, fetch_username
from utilities.invites import ban_user

class Invites(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Starts auto-sweeper when cog starts
        self.verify_sweeper.start()

    def cog_unload(self):
        self.verify_sweeper.cancel()

    # Run every hour to catch users who didn't get verified in 24h
    @tasks.loop(hours=1)
    async def verify_sweeper(self):
        try:
            async with db.conn_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Fetch everyone whose join_time was more than 24 hours ago
                    await cur.execute("SELECT user_id, guild_id, message_id FROM pending_verifications WHERE join_time < NOW() - INTERVAL 24 HOUR")
                    expired_users = await cur.fetchall()

            # Loop through all the expired users and ban
            for entry in expired_users:
                user_id, guild_id, message_id = entry

                # Fetch username once for ban_user & logging / embeds
                username = await fetch_username(self.bot, user_id)

                guild = self.bot.get_guild(guild_id)

                # Safely navigate the nested dictionaries
                server_config = next((s for s in config.get("servers") or [] if s.get("guild_id") == guild_id), {}) or {}

                if guild:
                    # Handle manual verification
                    try:
                        # Find member in guild using API, not cache
                        member = await guild.fetch_member(user_id)

                        # Fetch verified role ID from config
                        verified_role_id = (server_config.get("roles") or {}).get("verified")

                        # Fetch the actual role object from the guild
                        role = guild.get_role(verified_role_id) if verified_role_id else None

                        if not role:
                            Logger.warning(f"\"{username}\" (ID: {user_id}) will not be automatically verified or removed, as verified role cannot be found in \"{guild.name}\" (ID: {guild.id}).", task=True)
                            continue
                        if any(r.id == role.id for r in member.roles):
                            # Enable Task log mode via True
                            Logger.info(f"\"{username}\" (ID: {user_id}) was manually verified, ignoring & removing.", task=True)

                            async with db.conn_pool.acquire() as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute("DELETE FROM pending_verifications WHERE user_id = %s AND guild_id = %s", (user_id, guild_id,))
                            continue
                    except discord.NotFound:
                        # This means they've likely left the server, so will proceed with standard logic.
                        pass
                    except Exception:
                        Logger.warning(f"\"{username}\" (ID: {user_id}) could not be fetched during sweep.", task=True)
                        continue

                    # Calls ban function
                    success = await ban_user(self.bot, guild, user_id, username, reason="Gatekeeper timeout: Failed to verify within 24 hours.", task=True)

                    if success:
                        Logger.info(f"\"{username}\" (ID: {user_id}) was banned for verification timeout.", task=True)

                        try:
                            # Use "or {}" to force a dictionary even if the key is explicitly None
                            channels_cfg = server_config.get("channels") or {}
                            channel_id = channels_cfg.get("joins")

                            # Only attempt to get the channel if we have a valid integer ID
                            try:
                                channel = await guild.fetch_channel(channel_id) if channel_id else None
                            except Exception:
                                Logger.warning(f"\"{username}\" (ID: {user_id}) was auto-banned but failed to update their join message as the channel could not be fetched.", task=True)
                                continue

                            if channel:
                                # Find initial join message
                                message = await channel.fetch_message(message_id)

                                # Update message & remove buttons
                                embed = Embeds.info(f"<@{user_id}> wasn't verified within 24 hours and was auto-banned.")

                                await message.edit(embed=embed, view=None)
                        except Exception:
                            Logger.warning(f"\"{username}\" (ID: {user_id}) was auto-banned but failed to update their join message.", task=True)
                    else:
                        Logger.warning(f"\"{username}\" (ID: {user_id}) could not be banned for verification timeout.", task=True)
                else:
                    # Clear the orphaned entries where bot is no longer in guild
                    Logger.info(f"\"{username}\" (ID: {user_id}) was removed from database as bot is no longer in server (ID: {guild_id}).", task=True)

                    async with db.conn_pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("DELETE FROM pending_verifications WHERE user_id = %s AND guild_id = %s", (user_id, guild_id,))
        except Exception as e:
            Logger.warning("A critical error occurred whilst running the verification sweeper task, but was caught by the global task exception capture to prevent the task stopping.", str(e), task=True)

    # Ensure bot & cache is ready first before task starts
    @verify_sweeper.before_loop
    async def before_verify_sweeper(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Invites(bot))
