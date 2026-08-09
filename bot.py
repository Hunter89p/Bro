import asyncio
import datetime
import json
import os
import random
import string
import sys
import time

import discord
import docker
from discord.ext import commands
from dotenv import load_dotenv

# --- LOAD ENVIRONMENT VARIABLES ---
load_dotenv()

# --- LOAD CONFIGURATION FILE ---
CONFIG_FILE = "config.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ CRITICAL ERROR: {CONFIG_FILE} not found!")
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


CONFIG = load_config()

# Extract Config Parameters
BOT_NAME = CONFIG["bot"]["name"]
COMMAND_PREFIX = CONFIG["bot"]["prefix"]
ADMIN_ROLE_ID = CONFIG["bot"]["admin_role_id"]
CURRENCY = CONFIG["economy"]["currency_symbol"]
VPS_PLANS = CONFIG["vps_plans"]

# AFK Voice Rewards Settings
AFK_COINS_PER_MIN = CONFIG.get("afk_rewards", {}).get("coins_per_minute", 1)

LICENSE_KEY = CONFIG["license"]["key"]
VALID_LICENSES = CONFIG["license"]["valid_licenses"]


# --- LICENSE VERIFICATION ---
def verify_license():
    """Validate software license on boot"""
    print(f"🔒 Validating {BOT_NAME} License Key...")
    if LICENSE_KEY not in VALID_LICENSES:
        print("❌ CRITICAL ERROR: Invalid or missing license key!")
        print("⛔ Unauthorized software copy. System shutting down...")
        sys.exit(1)

    lic_info = VALID_LICENSES[LICENSE_KEY]
    if not lic_info.get("active", False):
        print("❌ CRITICAL ERROR: Your license has been revoked or suspended!")
        sys.exit(1)

    print(
        f"✅ LICENSE VERIFIED | Owner: {lic_info['owner']} | Tier:"
        f" {lic_info['tier']}"
    )


verify_license()

# File & Bot Settings
TOKEN = os.getenv("DISCORD_TOKEN")
VPS_STORAGE_FILE = "vps_data.json"
ECONOMY_STORAGE_FILE = "economy_data.json"
AFK_STORAGE_FILE = "afk_data.json"


# Custom Bot Instance with Anti-Spam Command Protection
class CustomBot(commands.Bot):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_command = None
        self._last_command_time = 0

    async def process_commands(self, message):
        if message.author.bot:
            return
        current_time = time.time()
        if (
            self._last_command == message.content
            and current_time - self._last_command_time < 2
        ):
            return
        self._last_command = message.content
        self._last_command_time = current_time
        await super().process_commands(message)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = CustomBot(command_prefix=COMMAND_PREFIX, intents=intents)

# Docker Client Setup
try:
    client = docker.from_env()
except Exception as e:
    print(f"Failed to initialize Docker client: {e}")
    client = None

# In-Memory Storage Containers
vps_data = {}
economy_data = {}
afk_data = {}


# --- PERSISTENCE STORAGE FUNCTIONS ---
def load_all_data():
    global vps_data, economy_data, afk_data
    if os.path.exists(VPS_STORAGE_FILE):
        with open(VPS_STORAGE_FILE, "r") as f:
            vps_data = json.load(f)

    if os.path.exists(ECONOMY_STORAGE_FILE):
        with open(ECONOMY_STORAGE_FILE, "r") as f:
            economy_data = json.load(f)

    if os.path.exists(AFK_STORAGE_FILE):
        with open(AFK_STORAGE_FILE, "r") as f:
            afk_data = json.load(f)


def save_vps_data():
    with open(VPS_STORAGE_FILE, "w") as f:
        json.dump(vps_data, f, indent=4)


def save_economy_data():
    with open(ECONOMY_STORAGE_FILE, "w") as f:
        json.dump(economy_data, f, indent=4)


def save_afk_data():
    with open(AFK_STORAGE_FILE, "w") as f:
        json.dump(afk_data, f, indent=4)


# --- ECONOMY HELPER FUNCTIONS ---
def get_balance(user_id: str) -> int:
    return economy_data.get(str(user_id), {}).get("balance", 0)


def add_balance(user_id: str, amount: int):
    user_id = str(user_id)
    if user_id not in economy_data:
        economy_data[user_id] = {"balance": 0, "last_daily": 0}
    economy_data[user_id]["balance"] += amount
    save_economy_data()


def remove_balance(user_id: str, amount: int) -> bool:
    user_id = str(user_id)
    if get_balance(user_id) >= amount:
        economy_data[user_id]["balance"] -= amount
        save_economy_data()
        return True
    return False


# --- GENERAL UTILITY FUNCTIONS ---
def generate_token():
    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


def generate_vps_id():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def is_admin_check(author):
    return any(role.id == ADMIN_ROLE_ID for role in getattr(author, "roles", []))


def has_admin_role(ctx):
    return is_admin_check(ctx.author)


def find_vps_by_id_or_token(query):
    query = query.strip()
    if query in vps_data:
        return query, vps_data[query]
    for token, details in vps_data.items():
        if details.get("vps_id", "").upper() == query.upper():
            return token, details
    return None, None


async def capture_ssh_session_line(process):
    try:
        while True:
            output = await process.stdout.readline()
            if not output:
                break
            output = output.decode("utf-8").strip()
            if "ssh session:" in output:
                return output.split("ssh session:")[1].strip()
        return None
    except Exception as e:
        print(f"Error capturing SSH session: {e}")
        return None


async def setup_container(container_id, status_msg):
    try:
        container = client.containers.get(container_id)
        if container.status != "running":
            container.start()
            await asyncio.sleep(3)

        update_proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            container_id,
            "apt-get",
            "update",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await update_proc.communicate()

        install_proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            container_id,
            "apt-get",
            "install",
            "-y",
            "tmate",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await install_proc.communicate()

        return True
    except Exception as e:
        print(f"Setup container error: {e}")
        return False


# --- BOT EVENT HANDLERS ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({BOT_NAME})")
    load_all_data()

    for guild in bot.guilds:
        try:
            await guild.me.edit(nick=BOT_NAME)
        except Exception as e:
            print(f"Could not change nickname in {guild.name}: {e}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    author_id = str(message.author.id)
    is_afk_command = message.content.strip().startswith(
        f"{COMMAND_PREFIX}afk"
    )

    if author_id in afk_data and not is_afk_command:
        info = afk_data[author_id]
        start_time = info.get("timestamp", int(time.time()))
        now = int(time.time())
        elapsed_seconds = now - start_time
        elapsed_minutes = elapsed_seconds // 60

        reward_coins = 0
        in_vc = message.author.voice and message.author.voice.channel

        if in_vc and elapsed_minutes >= 1:
            reward_coins = int(elapsed_minutes * AFK_COINS_PER_MIN)
            add_balance(author_id, reward_coins)

        del afk_data[author_id]
        save_afk_data()

        msg = f"👋 Welcome back {message.author.mention}! Your AFK status has been removed."
        if reward_coins > 0:
            msg += f"\n🎙️ **Voice Reward:** Earned **{CURRENCY}{reward_coins}** coins for spending **{int(elapsed_minutes)} min(s)** AFK in VC!"
        elif not in_vc and elapsed_minutes >= 1:
            msg += "\n⚠️ *No AFK coins awarded because you were not in a Voice Channel (VC).* "

        await message.channel.send(msg)

    if message.mentions:
        for user in message.mentions:
            user_id = str(user.id)
            if user_id in afk_data and user_id != author_id:
                info = afk_data[user_id]
                reason = info.get("reason", "AFK")
                ts = info.get("timestamp", int(time.time()))
                await message.channel.send(
                    f"💤 **{user.display_name}** is currently AFK: **{reason}**"
                    f" (<t:{ts}:R>)"
                )

    await bot.process_commands(message)


# --- LICENSE COMMAND ---
@bot.command(name="license_info")
@commands.check(has_admin_role)
async def license_info_cmd(ctx):
    """Check active software license information"""
    info = VALID_LICENSES.get(LICENSE_KEY, {})
    embed = discord.Embed(
        title=f"🔑 {BOT_NAME} License Details", color=discord.Color.blue()
    )
    embed.add_field(
        name="License Key", value=f"`{LICENSE_KEY}`", inline=False
    )
    embed.add_field(
        name="Registered Owner",
        value=info.get("owner", "Unknown"),
        inline=True,
    )
    embed.add_field(
        name="License Tier", value=info.get("tier", "Unknown"), inline=True
    )
    embed.add_field(
        name="Status",
        value="🟢 Active" if info.get("active") else "🔴 Inactive",
        inline=True,
    )
    embed.add_field(
        name="Expires On", value=info.get("expires", "N/A"), inline=True
    )
    await ctx.send(embed=embed)


# --- AFK COMMAND ---
@bot.command(name="afk")
async def afk_cmd(ctx, *, reason: str = "AFK"):
    """Set AFK status (Voice Channel required to earn per-minute coins)"""
    user_id = str(ctx.author.id)
    afk_data[user_id] = {
        "reason": reason,
        "timestamp": int(time.time())
    }
    save_afk_data()

    vc_status = (
        "🎙️ **VC Active:** Earning **"
        + f"{CURRENCY}{AFK_COINS_PER_MIN}** coin(s)/minute while in Voice!"
        if ctx.author.voice and ctx.author.voice.channel
        else "⚠️ **VC Inactive:** Join a Voice Channel to earn per-minute AFK"
        " coins!"
    )

    await ctx.send(
        f"💤 {ctx.author.mention}, I set your AFK status to: **{reason}**.\n{vc_status}"
    )


# --- ECONOMY COMMANDS ---
@bot.command(name="balance", aliases=["bal"])
async def balance_cmd(ctx, user: discord.Member = None):
    """Check user coin balance"""
    target = user or ctx.author
    bal = get_balance(target.id)
    embed = discord.Embed(
        title="💰 Wallet Balance",
        description=f"**{target.name}** has **{CURRENCY}{bal}** coins.",
        color=discord.Color.gold(),
    )
    await ctx.send(embed=embed)


@bot.command(name="daily")
async def daily_cmd(ctx):
    """Claim daily free reward"""
    user_id = str(ctx.author.id)
    if user_id not in economy_data:
        economy_data[user_id] = {"balance": 0, "last_daily": 0}

    last_daily = economy_data[user_id].get("last_daily", 0)
    cooldown = CONFIG["economy"]["daily_cooldown_seconds"]
    current_time = time.time()

    if current_time - last_daily < cooldown:
        remaining = int(cooldown - (current_time - last_daily))
        hours, mins = divmod(remaining // 60, 60)
        await ctx.send(f"⏳ Reward locked! Try again in **{hours}h {mins}m**.")
        return

    reward = random.randint(
        CONFIG["economy"]["daily_min_reward"],
        CONFIG["economy"]["daily_max_reward"],
    )
    add_balance(user_id, reward)
    economy_data[user_id]["last_daily"] = current_time
    save_economy_data()

    await ctx.send(
        f"🎉 Claimed **{CURRENCY}{reward}** daily reward! Wallet total:"
        f" **{CURRENCY}{get_balance(user_id)}**."
    )


@bot.command(name="pay")
async def pay_cmd(ctx, recipient: discord.Member, amount: int):
    """Transfer coins to another user"""
    if amount <= 0:
        await ctx.send("❌ Please specify an amount greater than 0.")
        return

    if remove_balance(ctx.author.id, amount):
        add_balance(recipient.id, amount)
        await ctx.send(
            f"✅ Transferred **{CURRENCY}{amount}** coins to"
            f" {recipient.mention}!"
        )
    else:
        await ctx.send("❌ Insufficient funds!")


@bot.command(name="add_coins")
@commands.check(has_admin_role)
async def add_coins_cmd(ctx, recipient: discord.Member, amount: int):
    """Admin command to issue coins"""
    add_balance(recipient.id, amount)
    await ctx.send(
        f"👑 Admin added **{CURRENCY}{amount}** coins to {recipient.mention}."
        f" New balance: **{CURRENCY}{get_balance(recipient.id)}**."
    )


# --- VPS PLANS & DEDICATED KVM CREATION COMMANDS ---
@bot.command(name="plans")
async def show_plans(ctx):
    """Display VPS hosting plans loaded from config"""
    embed = discord.Embed(
        title=f"☁️ {BOT_NAME} - Hosting Plans",
        description=(
            f"Buy a Dedicated KVM VPS using"
            f" `{COMMAND_PREFIX}buy_vps <plan_name>`:"
        ),
        color=discord.Color.purple(),
    )

    table_rows = [
        "Plan Key   │ Price  │ RAM  │ CPU   │ Disk",
        "───────────┼────────┼──────┼───────┼─────────",
    ]
    for key, plan in VPS_PLANS.items():
        price_str = f"{CURRENCY}{plan['price']}".ljust(6)
        ram_str = f"{plan['ram_gb']}GB".ljust(4)
        cpu_str = f"{plan['cpu_cores']} Core".ljust(6)
        disk_str = f"{plan['disk_gb']}GB SSD"
        table_rows.append(
            f"{key.ljust(11)}│ {price_str} │ {ram_str} │ {cpu_str}│ {disk_str}"
        )

    embed.add_field(
        name="Available VPS Tiers",
        value="```\n" + "\n".join(table_rows) + "\n```",
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command(name="buy_vps")
async def buy_vps_cmd(ctx, plan_name: str):
    """Purchase a dedicated KVM VPS with coins"""
    plan_key = plan_name.lower()
    if plan_key not in VPS_PLANS:
        await ctx.send(
            f"❌ Invalid plan! Available: `{', '.join(VPS_PLANS.keys())}`"
        )
        return

    plan = VPS_PLANS[plan_key]
    cost = plan["price"]

    if get_balance(ctx.author.id) < cost:
        await ctx.send(
            f"❌ Insufficient balance! You need **{CURRENCY}{cost}**, but only"
            f" have **{CURRENCY}{get_balance(ctx.author.id)}**."
        )
        return

    if not client:
        await ctx.send("❌ Docker engine is currently unavailable.")
        return

    status_msg = await ctx.send(
        "🔄 Allocating Dedicated Hardware Resources & Booting KVM Engine..."
    )
    remove_balance(ctx.author.id, cost)

    try:
        vps_id = generate_vps_id()
        memory_bytes = plan["ram_gb"] * 1024 * 1024 * 1024
        docker_cfg = CONFIG["docker"]

        container = client.containers.run(
            docker_cfg["default_image"],
            detach=True,
            hostname=f"{docker_cfg['hostname_prefix']}-{vps_id.lower()}",
            mem_limit=memory_bytes,
            mem_reservation=(
                memory_bytes if docker_cfg["dedicated_resources"] else None
            ),
            mem_swappiness=0 if docker_cfg["dedicated_resources"] else None,
            cpu_period=100000,
            cpu_quota=int(plan["cpu_cores"] * 100000),
            devices=docker_cfg["devices"] if docker_cfg["enable_kvm"] else None,
            cap_add=docker_cfg["capabilities"],
            security_opt=["seccomp=unconfined"],
            command="tail -f /dev/null",
            tty=True,
        )

        await status_msg.edit(content="⚙️ Setting up dedicated environment...")
        await asyncio.sleep(3)

        if not await setup_container(container.id, status_msg):
            raise Exception("Failed to configure container environment.")

        exec_cmd = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            container.id,
            "tmate",
            "-F",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        ssh_session_line = await capture_ssh_session_line(exec_cmd)

        token = generate_token()
        vps_data[token] = {
            "vps_id": vps_id,
            "container_id": container.id,
            "memory": plan["ram_gb"],
            "cpu": plan["cpu_cores"],
            "disk": plan["disk_gb"],
            "type": "Dedicated KVM VPS",
            "username": ctx.author.name,
            "created_by": str(ctx.author.id),
            "created_at": str(datetime.datetime.now()),
            "tmate_session": ssh_session_line or "Session pending...",
        }
        save_vps_data()

        embed = discord.Embed(
            title="⚡ Dedicated KVM VPS Ready", color=discord.Color.green()
        )
        embed.add_field(name="🆔 VPS ID", value=vps_id, inline=True)
        embed.add_field(name="🖥️ Type", value="Dedicated KVM", inline=True)
        embed.add_field(
            name="💾 Dedicated RAM", value=f"{plan['ram_gb']} GB", inline=True
        )
        embed.add_field(
            name="⚡ Dedicated CPU",
            value=f"{plan['cpu_cores']} Cores",
            inline=True,
        )
        embed.add_field(name="🔑 Connection Token", value=token, inline=False)
        if ssh_session_line:
            embed.add_field(
                name="🔒 SSH / Tmate Session",
                value=f"```{ssh_session_line}```",
                inline=False,
            )

        try:
            await ctx.author.send(embed=embed)
            await status_msg.edit(
                content=(
                    f"✅ Dedicated KVM VPS (**{plan_key.upper()}**) purchased"
                    f" successfully! Credentials sent to your DMs."
                )
            )
        except discord.Forbidden:
            await status_msg.edit(
                content=(
                    f"✅ Dedicated KVM VPS (**{plan_key.upper()}**) created! Direct"
                    " message blocked, please enable server DMs."
                )
            )

    except Exception as e:
        add_balance(ctx.author.id, cost)
        await status_msg.edit(
            content=(
                f"❌ VPS Creation failed: {str(e)}. Refunded"
                f" **{CURRENCY}{cost}**."
            )
        )


# --- PROFESSIONAL VPS MANAGEMENT CONTROL PANEL (!manage) ---
@bot.group(name="manage", invoke_without_command=True)
async def manage_group(ctx):
    """Professional VPS Control Dashboard"""
    embed = discord.Embed(
        title=f"🛠️ {BOT_NAME} - Professional VPS Control Panel",
        description="Manage your dedicated KVM server instances effortlessly.",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="📋 Commands Overview",
        value=(
            f"`{COMMAND_PREFIX}manage list` - List your active VPS instances\n"
            f"`{COMMAND_PREFIX}manage info <vps_id>` - View status & hardware specs\n"
            f"`{COMMAND_PREFIX}manage start` / `on <vps_id>` - Power ON your VPS\n"
            f"`{COMMAND_PREFIX}manage stop` / `off <vps_id>` - Power OFF your VPS\n"
            f"`{COMMAND_PREFIX}manage restart <vps_id>` - Reboot your VPS\n"
            f"`{COMMAND_PREFIX}manage reinstall <vps_id>` - Reinstall clean OS & reset VPS\n"
            f"`{COMMAND_PREFIX}manage ssh <vps_id>` - Re-send SSH credentials to DM\n"
            f"`{COMMAND_PREFIX}manage delete <vps_id>` - Destroy your VPS instance"
        ),
        inline=False,
    )
    embed.set_footer(text="Use your VPS ID or Token with management commands.")
    await ctx.send(embed=embed)


# --- LIST COMMAND ---
@manage_group.command(name="list")
async def manage_list(ctx):
    """List user's active VPS instances"""
    user_id = str(ctx.author.id)
    admin = is_admin_check(ctx.author)

    user_vps = []
    for token, info in vps_data.items():
        if info.get("created_by") == user_id or admin:
            user_vps.append((token, info))

    if not user_vps:
        await ctx.send("❌ You do not own any active VPS instances.")
        return

    embed = discord.Embed(
        title="🖥️ Your Active VPS Instances",
        color=discord.Color.dark_teal(),
    )

    for token, info in user_vps:
        status_icon = "❓ Unknown"
        if client:
            try:
                cnt = client.containers.get(info["container_id"])
                status_icon = "🟢 Running" if cnt.status == "running" else f"🔴 {cnt.status.capitalize()}"
            except Exception:
                status_icon = "🔴 Stopped / Removed"

        owner_str = f" | Owner: <@{info.get('created_by')}>" if admin else ""
        embed.add_field(
            name=f"🆔 VPS ID: `{info['vps_id']}`",
            value=(
                f"• **Status:** {status_icon}\n"
                f"• **Specs:** {info.get('memory', '?')}GB RAM | {info.get('cpu', '?')} Cores | {info.get('disk', '?')}GB SSD\n"
                f"• **Token:** `{token}`{owner_str}"
            ),
            inline=False,
        )

    await ctx.send(embed=embed)


# --- INFO COMMAND ---
@manage_group.command(name="info")
async def manage_info(ctx, vps_id: str):
    """Display detailed hardware and power status for a VPS"""
    token, info = find_vps_by_id_or_token(vps_id)

    if not info:
        await ctx.send(f"❌ VPS with ID/Token `{vps_id}` not found.")
        return

    if info.get("created_by") != str(ctx.author.id) and not is_admin_check(ctx.author):
        await ctx.send("❌ Permission denied! You do not own this VPS.")
        return

    status_str = "Unknown"
    if client:
        try:
            cnt = client.containers.get(info["container_id"])
            status_str = f"🟢 {cnt.status.upper()}" if cnt.status == "running" else f"🔴 {cnt.status.upper()}"
        except Exception:
            status_str = "🔴 STOPPED"

    embed = discord.Embed(
        title=f"📊 VPS Instance Detailed Info [{info['vps_id']}]",
        color=discord.Color.blue(),
    )
    embed.add_field(name="🆔 VPS ID", value=f"`{info['vps_id']}`", inline=True)
    embed.add_field(name="⚡ Status", value=status_str, inline=True)
    embed.add_field(name="🖥️ Type", value=info.get("type", "KVM VPS"), inline=True)
    embed.add_field(name="💾 RAM", value=f"{info.get('memory')} GB", inline=True)
    embed.add_field(name="⚡ CPU", value=f"{info.get('cpu')} Cores", inline=True)
    embed.add_field(name="💽 Disk", value=f"{info.get('disk')} GB SSD", inline=True)
    embed.add_field(name="👤 Owner ID", value=f"`{info.get('created_by')}`", inline=True)
    embed.add_field(name="📅 Created At", value=str(info.get("created_at")), inline=True)

    await ctx.send(embed=embed)


# --- POWER ON / START COMMANDS ---
@manage_group.command(name="start", aliases=["on"])
async def manage_start(ctx, vps_id: str):
    """Power ON / Start a VPS instance"""
    token, info = find_vps_by_id_or_token(vps_id)

    if not info:
        await ctx.send(f"❌ VPS with ID/Token `{vps_id}` not found.")
        return

    if info.get("created_by") != str(ctx.author.id) and not is_admin_check(ctx.author):
        await ctx.send("❌ Permission denied!")
        return

    if not client:
        await ctx.send("❌ Docker service is offline.")
        return

    msg = await ctx.send(f"🔄 Booting VPS `{info['vps_id']}`...")
    try:
        container = client.containers.get(info["container_id"])
        if container.status == "running":
            await msg.edit(content=f"⚠️ VPS `{info['vps_id']}` is already **RUNNING**!")
            return

        container.start()
        await msg.edit(content=f"🟢 VPS `{info['vps_id']}` powered ON successfully!")
    except Exception as e:
        await msg.edit(content=f"❌ Failed to start VPS: {str(e)}")


# --- POWER OFF / STOP COMMANDS ---
@manage_group.command(name="stop", aliases=["off"])
async def manage_stop(ctx, vps_id: str):
    """Power OFF / Stop a running VPS instance"""
    token, info = find_vps_by_id_or_token(vps_id)

    if not info:
        await ctx.send(f"❌ VPS with ID/Token `{vps_id}` not found.")
        return

    if info.get("created_by") != str(ctx.author.id) and not is_admin_check(ctx.author):
        await ctx.send("❌ Permission denied!")
        return

    if not client:
        await ctx.send("❌ Docker service is offline.")
        return

    msg = await ctx.send(f"🛑 Powering OFF VPS `{info['vps_id']}`...")
    try:
        container = client.containers.get(info["container_id"])
        container.stop(timeout=10)
        await msg.edit(content=f"🔴 VPS `{info['vps_id']}` has been powered OFF!")
    except Exception as e:
        await msg.edit(content=f"❌ Failed to stop VPS: {str(e)}")


# --- RESTART COMMAND ---
@manage_group.command(name="restart", aliases=["reboot"])
async def manage_restart(ctx, vps_id: str):
    """Reboot / Restart a VPS instance"""
    token, info = find_vps_by_id_or_token(vps_id)

    if not info:
        await ctx.send(f"❌ VPS with ID/Token `{vps_id}` not found.")
        return

    if info.get("created_by") != str(ctx.author.id) and not is_admin_check(ctx.author):
        await ctx.send("❌ Permission denied!")
        return

    if not client:
        await ctx.send("❌ Docker service is offline.")
        return

    msg = await ctx.send(f"🔄 Rebooting VPS `{info['vps_id']}`...")
    try:
        container = client.containers.get(info["container_id"])
        container.restart()
        await msg.edit(content=f"🟢 VPS `{info['vps_id']}` restarted successfully!")
    except Exception as e:
        await msg.edit(content=f"❌ Failed to restart VPS: {str(e)}")


# --- REINSTALL / RESET OS COMMAND ---
@manage_group.command(name="reinstall", aliases=["reset", "rebuild"])
async def manage_reinstall(ctx, vps_id: str):
    """Wipe and reinstall a fresh OS/environment on the VPS"""
    token, info = find_vps_by_id_or_token(vps_id)

    if not info:
        await ctx.send(f"❌ VPS with ID/Token `{vps_id}` not found.")
        return

    if info.get("created_by") != str(ctx.author.id) and not is_admin_check(ctx.author):
        await ctx.send("❌ Permission denied!")
        return

    if not client:
        await ctx.send("❌ Docker service is offline.")
        return

    msg = await ctx.send(f"🔄 **Reinstalling VPS `{info['vps_id']}`...** Wiping existing container...")

    try:
        # 1. Terminate and remove old container
        try:
            old_container = client.containers.get(info["container_id"])
            old_container.stop(timeout=5)
            old_container.remove(force=True)
        except Exception as e:
            print(f"Old container removal note: {e}")

        # 2. Retrieve hardware allocations
        ram_gb = info.get("memory", 2)
        cpu_cores = info.get("cpu", 1)
        memory_bytes = ram_gb * 1024 * 1024 * 1024
        docker_cfg = CONFIG["docker"]

        # 3. Spin up fresh environment
        new_container = client.containers.run(
            docker_cfg["default_image"],
            detach=True,
            hostname=f"{docker_cfg['hostname_prefix']}-{info['vps_id'].lower()}",
            mem_limit=memory_bytes,
            mem_reservation=memory_bytes if docker_cfg["dedicated_resources"] else None,
            mem_swappiness=0 if docker_cfg["dedicated_resources"] else None,
            cpu_period=100000,
            cpu_quota=int(cpu_cores * 100000),
            devices=docker_cfg["devices"] if docker_cfg["enable_kvm"] else None,
            cap_add=docker_cfg["capabilities"],
            security_opt=["seccomp=unconfined"],
            command="tail -f /dev/null",
            tty=True,
        )

        await msg.edit(content=f"⚙️ Provisioning fresh OS and packages for `{info['vps_id']}`...")
        await asyncio.sleep(3)

        if not await setup_container(new_container.id, msg):
            raise Exception("Failed to configure container packages.")

        exec_cmd = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            new_container.id,
            "tmate",
            "-F",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        ssh_session_line = await capture_ssh_session_line(exec_cmd)

        # 4. Save updated container info
        info["container_id"] = new_container.id
        info["tmate_session"] = ssh_session_line or "Session pending..."
        vps_data[token] = info
        save_vps_data()

        embed = discord.Embed(
            title=f"🔄 VPS Reinstalled Successfully [{info['vps_id']}]",
            color=discord.Color.green(),
        )
        embed.add_field(name="🆔 VPS ID", value=f"`{info['vps_id']}`", inline=True)
        embed.add_field(name="🔑 Connection Token", value=f"`{token}`", inline=True)
        if ssh_session_line:
            embed.add_field(
                name="🔒 New SSH / Tmate Session",
                value=f"```{ssh_session_line}```",
                inline=False,
            )

        try:
            await ctx.author.send(embed=embed)
            await msg.edit(content=f"✅ VPS `{info['vps_id']}` has been reinstalled! New SSH credentials sent to your DMs.")
        except discord.Forbidden:
            await msg.edit(content=f"✅ VPS `{info['vps_id']}` reinstalled! Direct message blocked, enable DMs to view SSH details.")

    except Exception as e:
        await msg.edit(content=f"❌ Reinstall failed: {str(e)}")


# --- SSH COMMAND ---
@manage_group.command(name="ssh")
async def manage_ssh(ctx, vps_id: str):
    """Fetch and DM active SSH / Tmate credentials"""
    token, info = find_vps_by_id_or_token(vps_id)

    if not info:
        await ctx.send(f"❌ VPS with ID/Token `{vps_id}` not found.")
        return

    if info.get("created_by") != str(ctx.author.id) and not is_admin_check(ctx.author):
        await ctx.send("❌ Permission denied!")
        return

    session_info = info.get("tmate_session", "No active session recorded.")

    embed = discord.Embed(
        title=f"🔑 VPS Session Details [{info['vps_id']}]",
        color=discord.Color.gold(),
    )
    embed.add_field(name="🆔 VPS ID", value=f"`{info['vps_id']}`", inline=True)
    embed.add_field(name="🔑 Connection Token", value=f"`{token}`", inline=True)
    embed.add_field(
        name="🔒 SSH / Tmate Command",
        value=f"```{session_info}```",
        inline=False,
    )

    try:
        await ctx.author.send(embed=embed)
        await ctx.send(f"✅ Active SSH credentials sent to your DMs for VPS `{info['vps_id']}`.")
    except discord.Forbidden:
        await ctx.send("❌ Direct message blocked! Please enable server DMs to receive credentials.")


# --- DELETE COMMAND ---
@manage_group.command(name="delete", aliases=["destroy"])
async def manage_delete(ctx, vps_id: str):
    """Permanently delete and erase a VPS instance"""
    token, info = find_vps_by_id_or_token(vps_id)

    if not info:
        await ctx.send(f"❌ VPS with ID/Token `{vps_id}` not found.")
        return

    if info.get("created_by") != str(ctx.author.id) and not is_admin_check(ctx.author):
        await ctx.send("❌ Permission denied!")
        return

    msg = await ctx.send(f"⚠️ Terminating & destroying VPS `{info['vps_id']}`...")

    if client:
        try:
            container = client.containers.get(info["container_id"])
            container.stop(timeout=5)
            container.remove(force=True)
        except Exception as e:
            print(f"Error deleting Docker container: {e}")

    del vps_data[token]
    save_vps_data()

    await msg.edit(content=f"🗑️ VPS `{info['vps_id']}` has been permanently destroyed.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ Permission denied.")
    else:
        print(f"Command Error: {error}")


if __name__ == "__main__":
    bot.run(TOKEN)
