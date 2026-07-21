# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Extractors — turn discord.py objects into plain snapshot dicts.

This is the ONLY module in the engine that imports discord.py, and it is imported on demand
(never from the top-level package), so the engine core keeps its zero-discord invariant. Each
function is pure: ``discord object -> dict`` (or ``-> list[dict]``), driven by a
``GuildSnapshotConfig``. The dict shapes reproduce TheCodex's legacy ``GuildCacheManager``
field-for-field, except timestamps are stored as BSON datetimes (not ISO-8601 strings) per the
ecosystem ID/timestamp ruling -- this is what the engine's own ``delete_before_date`` /
``cleanup_old_data`` datetime cutoffs compare against. IDs remain raw ints pending the scheduled
per-bot string-ID normalization migration.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import discord

from ..logging_compat import get_logger
from .config import GuildSnapshotConfig

logger = get_logger("GuildSnapshotExtractors")


def _account_age_days(created_at: datetime, now_utc: datetime) -> int:
    return (now_utc - created_at).days


def extract_guild(guild: "discord.Guild", config: GuildSnapshotConfig) -> Dict[str, Any]:
    """Snapshot guild-level metadata + derived counts (root doc, keyed by ``id``)."""
    features = list(guild.features) if guild.features else []
    bot_count = sum(1 for member in guild.members if member.bot)
    voice_channels_active = sum(1 for vc in guild.voice_channels if vc.members)
    premium_members = sum(1 for member in guild.members if member.premium_since)

    return {
        "id": guild.id,
        "name": guild.name,
        "icon_url": str(guild.icon.url) if guild.icon else None,
        "banner_url": str(guild.banner.url) if guild.banner else None,
        "description": guild.description,
        "owner_id": guild.owner_id,
        "member_count": guild.member_count,
        "bot_count": bot_count,
        "human_count": guild.member_count - bot_count,
        "premium_members": premium_members,
        "voice_channels_active": voice_channels_active,
        "max_members": guild.max_members,
        "verification_level": str(guild.verification_level),
        "default_notifications": str(guild.default_notifications),
        "explicit_content_filter": str(guild.explicit_content_filter),
        "mfa_level": guild.mfa_level,
        "premium_tier": guild.premium_tier,
        "premium_subscription_count": guild.premium_subscription_count,
        "features": features,
        "created_at": guild.created_at,
        "cache_version": config.cache_version,
        "total_channels": len(guild.channels),
        "text_channels": len(guild.text_channels),
        "voice_channels": len(guild.voice_channels),
        "categories": len(guild.categories),
        "total_roles": len(guild.roles),
        "system_channel_id": guild.system_channel.id if guild.system_channel else None,
        "rules_channel_id": guild.rules_channel.id if guild.rules_channel else None,
        "public_updates_channel_id": guild.public_updates_channel.id if guild.public_updates_channel else None,
        "vanity_url": guild.vanity_url,
        "preferred_locale": str(guild.preferred_locale) if guild.preferred_locale else None,
    }


async def extract_channels(guild: "discord.Guild", config: GuildSnapshotConfig) -> List[Dict[str, Any]]:
    """Snapshot every channel (text/voice/forum) with overwrites, threads and type specifics."""
    channels: List[Dict[str, Any]] = []
    for channel in guild.channels:
        try:
            permissions = []
            try:
                for target, overwrite in (channel.overwrites or {}).items():
                    try:
                        allow = discord.Permissions.none()
                        deny = discord.Permissions.none()
                        for name, value in overwrite:
                            if value is True:
                                setattr(allow, name, True)
                            elif value is False:
                                setattr(deny, name, True)
                        permissions.append({
                            "id": target.id,
                            "name": getattr(target, "name", None),
                            "type": "role" if isinstance(target, discord.Role) else "user",
                            "allow": allow.value,
                            "deny": deny.value,
                        })
                    except Exception as po_err:
                        logger.debug(f"Skipping bad overwrite for channel {channel.name}: {po_err}")
            except Exception as perm_error:
                logger.warning(f"Error processing permissions for channel {channel.name}: {perm_error}")

            channel_data: Dict[str, Any] = {
                "guild_id": guild.id,
                "id": channel.id,
                "name": channel.name,
                "type": str(channel.type),
                "position": channel.position,
                "permissions": permissions,
                "created_at": channel.created_at,
            }

            if hasattr(channel, "category") and channel.category:
                channel_data["category_id"] = channel.category.id
                channel_data["category_name"] = channel.category.name

            if isinstance(channel, discord.TextChannel):
                channel_data.update({
                    "topic": channel.topic,
                    "slowmode_delay": channel.slowmode_delay,
                    "nsfw": channel.nsfw,
                    "last_message_id": channel.last_message_id,
                    "message_history_enabled": True,
                })
                if hasattr(channel, "threads"):
                    threads = []
                    try:
                        async for thread in channel.archived_threads(limit=50):
                            threads.append({
                                "id": thread.id,
                                "name": thread.name,
                                "archived": thread.archived,
                                "locked": thread.locked,
                                "created_at": thread.created_at,
                            })
                        channel_data["archived_threads"] = threads
                        channel_data["thread_count"] = len(threads)
                    except (discord.Forbidden, discord.HTTPException):
                        channel_data["archived_threads"] = []
                        channel_data["thread_count"] = 0

            elif isinstance(channel, discord.VoiceChannel):
                channel_data.update({
                    "bitrate": channel.bitrate,
                    "user_limit": channel.user_limit,
                    "rtc_region": str(channel.rtc_region) if channel.rtc_region else None,
                    "current_users": len(channel.members),
                    "user_list": [member.id for member in channel.members],
                })

            elif hasattr(discord, "ForumChannel") and isinstance(channel, discord.ForumChannel):
                channel_data.update({
                    "topic": channel.topic,
                    "slowmode_delay": channel.slowmode_delay,
                    "nsfw": channel.nsfw,
                    "default_auto_archive_duration": channel.default_auto_archive_duration,
                })

            channels.append(channel_data)
        except Exception as channel_error:
            logger.error(f"Error processing channel {getattr(channel, 'name', '?')}: {channel_error}")
            continue
    return channels


def extract_roles(guild: "discord.Guild", config: GuildSnapshotConfig) -> List[Dict[str, Any]]:
    """Snapshot roles with dangerous/moderation permission flags (driven by config)."""
    roles: List[Dict[str, Any]] = []
    for role in guild.roles:
        try:
            has_dangerous = any(
                getattr(role.permissions, perm, False) for perm in config.dangerous_permissions
            )
            has_moderation = any(
                getattr(role.permissions, perm, False) for perm in config.moderation_permissions
            )
            roles.append({
                "guild_id": guild.id,
                "id": role.id,
                "name": role.name,
                "color": str(role.color),
                "color_value": role.color.value,
                "permissions": role.permissions.value,
                "position": role.position,
                "mentionable": role.mentionable,
                "hoist": role.hoist,
                "managed": role.managed,
                "is_default": role.is_default(),
                "is_premium_subscriber": role.is_premium_subscriber(),
                "has_dangerous_permissions": has_dangerous,
                "has_moderation_permissions": has_moderation,
                "member_count": len(role.members),
                "created_at": role.created_at,
                "display_icon": str(role.display_icon) if getattr(role, "display_icon", None) else None,
                "unicode_emoji": role.unicode_emoji if hasattr(role, "unicode_emoji") else None,
            })
        except Exception as role_error:
            logger.error(f"Error processing role {getattr(role, 'name', '?')}: {role_error}")
            continue
    return roles


def extract_members(
    guild: "discord.Guild",
    config: GuildSnapshotConfig,
    *,
    now_utc: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Snapshot members with account age + suspicious indicators (threshold from config)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    members: List[Dict[str, Any]] = []
    for member in guild.members:
        try:
            account_age = _account_age_days(member.created_at, now_utc)

            suspicious_indicators = []
            if account_age < config.suspicious_new_account_days:
                suspicious_indicators.append("very_new_account")
            # A default (never-set) avatar is served from the CDN's embed path
            # (/embed/avatars/{0..5}.png); a custom avatar is under /avatars/{id}/.
            # The old check only matched index 0, missing ~5 of 6 default users.
            if not member.display_avatar or "/embed/avatars/" in str(member.display_avatar.url):
                suspicious_indicators.append("default_avatar")
            if len(member.roles) <= 1:  # only @everyone
                suspicious_indicators.append("no_roles")

            members.append({
                "guild_id": guild.id,
                "id": member.id,
                "username": member.name,
                "global_name": member.global_name,
                "display_name": member.display_name or member.name,
                "discriminator": member.discriminator,
                "bot": member.bot,
                "system": member.system,
                "joined_at": member.joined_at,
                "premium_since": member.premium_since,
                "roles": [role.id for role in member.roles if not role.is_default()],
                "role_count": len([role for role in member.roles if not role.is_default()]),
                "top_role_id": member.top_role.id if member.top_role else None,
                "top_role_position": member.top_role.position if member.top_role else 0,
                "permissions": member.guild_permissions.value,
                "avatar_url": str(member.display_avatar.url),
                "created_at": member.created_at,
                "account_age_days": account_age,
                "suspicious_indicators": suspicious_indicators,
                "is_owner": member.id == guild.owner_id,
                "guild_permissions_value": member.guild_permissions.value,
                "voice_channel_id": member.voice.channel.id if member.voice else None,
            })
        except Exception as member_error:
            logger.error(f"Error processing member {getattr(member, 'name', '?')}: {member_error}")
            continue
    return members


def extract_analytics(
    guild: "discord.Guild",
    config: GuildSnapshotConfig,
    *,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Snapshot the daily analytics rollup (keyed by ``guild_id`` + local-timezone ``date``)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    now_local = datetime.now(ZoneInfo(config.timezone))
    today = now_local.strftime("%Y-%m-%d")

    bot_count = sum(1 for member in guild.members if member.bot)
    human_count = guild.member_count - bot_count

    role_distribution: Dict[str, int] = defaultdict(int)
    for member in guild.members:
        for role in member.roles:
            if not role.is_default():
                role_distribution[role.name] += 1

    voice_activity = {vc.name: len(vc.members) for vc in guild.voice_channels}

    age_distribution = {label: 0 for label, _ in config.age_buckets}
    for member in guild.members:
        if member.bot:
            continue
        age = _account_age_days(member.created_at, now_utc)
        for label, upper in config.age_buckets:
            if upper is None or age <= upper:
                age_distribution[label] += 1
                break

    return {
        "guild_id": guild.id,
        "date": today,
        "timestamp": now_local,
        "member_stats": {
            "total": guild.member_count,
            "humans": human_count,
            "bots": bot_count,
            "premium": sum(1 for member in guild.members if member.premium_since),
        },
        "channel_stats": {
            "total": len(guild.channels),
            "text": len(guild.text_channels),
            "voice": len(guild.voice_channels),
            "categories": len(guild.categories),
            "voice_active": sum(1 for vc in guild.voice_channels if vc.members),
        },
        "role_stats": {
            "total": len(guild.roles),
            "with_permissions": len([r for r in guild.roles if r.permissions.value > 0]),
            "managed": len([r for r in guild.roles if r.managed]),
            "distribution": dict(role_distribution),
        },
        "voice_activity": voice_activity,
        "age_distribution": age_distribution,
        "guild_features": list(guild.features) if guild.features else [],
        "verification_level": str(guild.verification_level),
        "premium_tier": guild.premium_tier,
    }
