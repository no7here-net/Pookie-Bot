import time
import discord

from typing import Literal
from discord import app_commands
from discord.ext import commands, tasks

import utilities.database as db

from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.helpers import config, fetch_username, get_guild_config, is_quarantined
from utilities.invites import ban_user, preverify_logic, preverify_list, verify_member, fetch_join_state, register_pending
from utilities.interactions import VerificationView

class Invites(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Starts auto-sweeper when cog starts
        self.verify_sweeper.start()

    def cog_unload(self):
        self.verify_sweeper.cancel()

    @app_commands.command(name="verify", description="Manually verify a user or manage automatic member verification on member join.")
    @app_commands.describe(action="Whether to add, remove, or list pre-verified users. Add also manually verifies existing members.", user="User to target. Required for Add and Remove.")
    async def verify(self, interaction: discord.Interaction, action: Literal["Add", "Remove", "List"] = "Add", user: discord.User = None):
        # Add & remove target a specific user, so one must be provided
        if action in ("Add", "Remove") and user is None:
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) tried to {action.lower()} a verification without providing a user.")
            embed = Embeds.error("You must provide a user for this action.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Prevent Discord timing out
        await interaction.response.defer(ephemeral=True)

        if action == "Add":
            state = await is_quarantined(interaction.guild.id, user.id)
            if state is None:
                embed = Embeds.error("Couldn't check quarantine status right now. Try again shortly.")
            if state:
                embed = Embeds.error("This user is currently quarantined and cannot be verified.")
            # Shared send message
            if state is None or state:
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            member = interaction.guild.get_member(user.id)
            if member:
                # User is in server, manually verify
                if await verify_member(member):
                    embed = Embeds.success(f"<@{user.id}> has been manually verified.")
                else:
                    embed = Embeds.error(f"Failed to verify <@{user.id}>. Check logs.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            else:
                # User is not in server, pre-verify
                result = await preverify_logic(self.bot, action, interaction.guild.id, user.id, interaction.user.id)
                if not result.get("success"):
                    embed = Embeds.error(result.get("error"))
                else:
                    embed = Embeds.success(f"<@{user.id}> will bypass verification when they join.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        elif action == "Remove":
            # Just remove from pre_verified list
            result = await preverify_logic(self.bot, action, interaction.guild.id, user.id, interaction.user.id)
            if not result.get("success"):
                embed = Embeds.error(result.get("error"))
            else:
                embed = Embeds.success(f"<@{user.id}> will no longer bypass verification when they join.")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        elif action == "List":
            # Fetch all entries for this server
            result = await preverify_list(interaction.guild.id)

            if not result.get("success"):
                embed = Embeds.error(result.get("error"))
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            entries = result.get("entries") or ()

            if not entries:
                embed = Embeds.info("No users are currently pre-verified.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Cap the output so huge lists cannot overflow the embed description limit
            lines = [f"<@{user_id}> - added by <@{added_by_id}> <t:{int(added_at.timestamp())}:R>" for user_id, added_by_id, added_at in entries[:25]]

            if len(entries) > 25:
                lines.append(f"...and {len(entries) - 25} more.")

            embed = Embeds.info("\n".join(lines))
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="preverify", description="Manage automatic member verification on member join.")
    @app_commands.describe(action="Whether to add, remove, or list pre-verified users.", user="User to target. Required for Add and Remove.")
    async def preverify(self, interaction: discord.Interaction, action: Literal["Add", "Remove", "List"], user: discord.User = None):
        # Add & remove target a specific user, so one must be provided
        if action in ("Add", "Remove") and user is None:
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) tried to {action.lower()} a pre-verification without providing a user.")
            embed = Embeds.error("You must provide a user for this action.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Prevent Discord timing out
        await interaction.response.defer(ephemeral=True)

        # Add & remove logic are handled by a single logic function
        if action in ("Add", "Remove"):
            # Send info to logic
            result = await preverify_logic(self.bot, action, interaction.guild.id, user.id, interaction.user.id)

            if not result.get("success"):
                # Error message already ends with a full stop
                embed = Embeds.error(result.get("error"))
            else:
                embed = Embeds.success(f"<@{user.id}> will {"no longer " if action == "Remove" else ""}bypass verification when they join.")

            await interaction.followup.send(embed=embed, ephemeral=True)

        elif action == "List":
            # Fetch all entries for this server
            result = await preverify_list(interaction.guild.id)

            if not result.get("success"):
                embed = Embeds.error(result.get("error"))
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            entries = result.get("entries") or ()

            if not entries:
                embed = Embeds.info("No users are currently pre-verified.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Cap the output so huge lists cannot overflow the embed description limit
            lines = [f"<@{user_id}> - added by <@{added_by_id}> <t:{int(added_at.timestamp())}:R>" for user_id, added_by_id, added_at in entries[:25]]

            if len(entries) > 25:
                lines.append(f"...and {len(entries) - 25} more.")

            embed = Embeds.info("\n".join(lines))
            await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Prevents bots being put through this automated system - they go through a different permission flow via oauth limited to admins, they don't need checking
        if member.bot:
            Logger.info(f"\"{member.name}#{member.discriminator}\" (ID: {member.id}) joined \"{member.guild.name}\" (ID: {member.guild.id}) as a bot, skipping gatekeeper.")
            return

        # Match server in config
        server_config = get_guild_config(member.guild.id)

        if not server_config:
            Logger.warning(f"\"{member.name}\" (ID: {member.id}) joined \"{member.guild.name}\" (ID: {member.guild.id}) but the server is not in config.json, skipping gatekeeper.")
            return

        # Find the joins channel
        channel = await self._get_joins_channel(member.guild, server_config)

        # Fetch quarantine state
        quarantine = await is_quarantined(member.guild.id, member.id)

        embed = None

        if quarantine is None:
            Logger.warning(f"... could not be checked against the quarantined list due to a database exception. Falling back to standard verification.")
            embed = Embeds.warning(f"<@{member.id}> has joined the server but could not be checked against the quarantine list. If they are not quarantined, they require manual verification.")
        elif quarantine:
            Logger.info(f"... joined while quarantined. Ignoring verification flow.")
            embed = Embeds.warning(f"Quarantined account <@{member.id}> has joined the server. They will remain unverified and ignored by the gatekeeper system.")

        if embed and channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                Logger.warning(f"Failed to send quarantine join warning for \"{member.name}\" (ID: {member.id}) in channel (ID: {channel.id}).")

        # Only a confirmed quarantine halts the gatekeeper
        if quarantine:
            return

        # Fetch pre-verification state & any leftover pending message from a previous join
        join_state = await fetch_join_state(member.guild.id, member.id)

        if not join_state.get("success"):
            # Fail towards the gatekeeper: treat them as a normal joiner rather than letting them through
            Logger.warning(f"\"{member.name}\" (ID: {member.id}) could not be checked against the pre-verified list due to a database exception. Falling back to standard verification.")

        old_message_id = join_state.get("pending_message_id")

        if not channel:
            Logger.error(f"\"{member.name}\" (ID: {member.id}) joined \"{member.guild.name}\" (ID: {member.guild.id}) but the joins channel could not be found. The gatekeeper timer still applies, so they must be verified manually via role grant.")

        # Pre-verified members skip the gate entirely
        if join_state.get("preverified_by_id"):
            # verify_member() handles role granting, database cleanup and its own logging
            if await verify_member(member):
                await self._announce_preverify(channel, member.id, join_state.get("preverified_by_id"), old_message_id)
                return

            # If granting the role fails, fall through to the standard flow so they are at least visible & pending
            Logger.warning(f"\"{member.name}\" (ID: {member.id}) is pre-verified but could not be verified on join. Falling back to standard verification.")

        # Standard flow: post the gatekeeper message with verification buttons
        message_id = 0
        message = None

        if channel:
            embed = Embeds.info(f"<@{member.id}> joined and is awaiting verification. Their account was created <t:{int(member.created_at.timestamp())}:R>. They will be banned <t:{int(time.time() + 86400)}:R> unless verified.")

            try:
                message = await channel.send(embed=embed, view=VerificationView())
                message_id = message.id
            except Exception:
                Logger.warning(f"\"{member.name}\" (ID: {member.id}) joined but the verification message could not be sent to the joins channel (ID: {channel.id}).")

        # Track them even if no message could be sent, so the 24 hour timer still applies. As message_id of 0 can never match a real message, so the buttons & sweeper edit safely don't
        if not await register_pending(member.guild.id, member.id, message_id):
            Logger.error(f"\"{member.name}\" (ID: {member.id}) joined but could not be added to pending verifications. The gatekeeper cannot track them. Manual verification or removal required.")

            # Disarm the buttons, as they cannot work without a database entry
            if message:
                try:
                    embed = Embeds.error(f"<@{member.id}> joined but couldn't be tracked due to a database error. Manual verification or removal required.")
                    await message.edit(embed=embed, view=None)
                except Exception:
                    Logger.warning(f"\"{member.name}\" (ID: {member.id})'s join message could not be updated to reflect the tracking failure (Message ID: {message_id}).")
            return

        # Retire the previous join message if they rejoined whilst still pending, so only the newest buttons are live
        if old_message_id and channel:
            try:
                old_message = await channel.fetch_message(old_message_id)
                embed = Embeds.info(f"<@{member.id}> rejoined before being verified. Verification moved to a newer message.")
                await old_message.edit(embed=embed, view=None)
            except Exception:
                Logger.warning(f"\"{member.name}\" (ID: {member.id}) rejoined but their previous join message could not be updated (Message ID: {old_message_id}).")

        Logger.info(f"\"{member.name}\" (ID: {member.id}) joined \"{member.guild.name}\" (ID: {member.guild.id}) and is pending verification.")

    # Run every hour to catch users who didn't get verified in 24h
    @tasks.loop(hours=1)
    async def verify_sweeper(self):
        try:
            # =============================
            # PHASE 1: PRE-VERIFY CATCH-UP
            # =============================

            for server_config in config.get("servers") or []:
                guild_id = server_config.get("guild_id")
                guild = self.bot.get_guild(guild_id) if guild_id else None

                if not guild:
                    continue

                # Make sure the member cache is complete, otherwise present members could be missed this run
                if not guild.chunked:
                    try:
                        await guild.chunk()
                    except Exception:
                        Logger.warning(f"Failed to fetch the full member list for \"{guild.name}\" (ID: {guild.id}). Pre-verification catch-up may be incomplete this run.", task=True)

                try:
                    async with db.conn_pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("SELECT user_id, added_by_id FROM pre_verified WHERE guild_id = %s", (guild_id,))
                            preverified_users = await cur.fetchall()
                except Exception:
                    Logger.warning("Verification sweeper failed to fetch the pre-verified list from the database.", task=True)
                    preverified_users = ()

                for user_id, added_by_id in preverified_users:
                    member = guild.get_member(user_id)

                    # Not in the server yet - on_member_join() will verify them when they arrive
                    if not member:
                        continue

                    # Fetch any pending join message before verify_member() deletes the row
                    join_state = await fetch_join_state(guild_id, user_id)
                    old_message_id = join_state.get("pending_message_id")

                    if await verify_member(member, task=True):
                        Logger.info(f"\"{member.name}\" (ID: {member.id}) was caught by the pre-verification sweep and verified.", task=True)

                        channel = await self._get_joins_channel(guild, server_config)
                        await self._announce_preverify(channel, member.id, added_by_id, old_message_id, task=True)

            # ==================
            # PHASE 2: BAN SWEEP
            # ==================

            async with db.conn_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Fetch everyone whose join_time was more than 24 hours ago, excluding anyone in pre-verified table
                    await cur.execute("""
                        SELECT pv.user_id, pv.guild_id, pv.message_id
                        FROM pending_verifications pv
                        LEFT JOIN pre_verified p ON p.user_id = pv.user_id AND p.guild_id = pv.guild_id
                        WHERE pv.join_time < NOW() - INTERVAL 24 HOUR AND p.user_id IS NULL
                    """)
                    expired_users = await cur.fetchall()

            # Loop through all the expired users and ban
            for entry in expired_users:
                user_id, guild_id, message_id = entry

                # Fetch username once for ban_user & logging / embeds
                username = await fetch_username(self.bot, user_id)

                guild = self.bot.get_guild(guild_id)

                # Safely navigate the nested dictionaries
                server_config = get_guild_config(guild_id)

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

    # ================
    # INTERNAL HELPERS
    # ================

    # Resolves the joins channel for a server config, preferring the cache with an API fallback
    async def _get_joins_channel(self, guild: discord.Guild, server_config: dict):
        channel_id = (server_config.get("channels") or {}).get("joins")

        if not channel_id:
            return None

        channel = self.bot.get_channel(channel_id)

        if channel:
            return channel

        try:
            return await guild.fetch_channel(channel_id)
        except Exception:
            return None

    # Announces a pre-verification in the joins channel. Retires the user's old join message if one exists so stale buttons never linger.
    async def _announce_preverify(self, channel, user_id: int, added_by_id: int, old_message_id: int = None, task: bool = False):
        if not channel:
            return

        embed = Embeds.info(f"<@{user_id}> joined and was pre-verified by <@{added_by_id}>.")

        try:
            if old_message_id:
                old_message = await channel.fetch_message(old_message_id)
                await old_message.edit(embed=embed, view=None)
            else:
                await channel.send(embed=embed)
        except Exception:
            Logger.warning(f"Pre-verification for user (ID: {user_id}) could not be announced in the joins channel (ID: {channel.id}).", task=task)

async def setup(bot):
    await bot.add_cog(Invites(bot))
