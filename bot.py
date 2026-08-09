import os
import random
import string
import json
import subprocess
import asyncio
import datetime
import time
import urllib.parse
import docker
import discord
from discord.ext import commands, tasks
from discord import ui
from dotenv import load_dotenv

# ----------------- Configuration & Initialization -----------------

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
VPS_STORAGE_FILE = 'vps_data.json'
ECONOMY_FILE = 'economy_data.json'
ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID', '0'))
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', '0'))
PROOF_CHANNEL_ID = int(os.getenv('PROOF_CHANNEL_ID', '0'))
MAX_VPS_PER_USER = int(os.getenv('MAX_VPS_PER_USER', '5'))
UPI_ID = os.getenv('UPI_ID', 'yourupi@upi')

# Antinuke Whitelist (Comma-separated Discord User IDs)
ANTINUKE_WHITELIST = [
    int(x.strip()) for x in os.getenv('ANTINUKE_WHITELIST', '').split(',') if x.strip().isdigit()
]

# Free VPS Plans (Invite-based)
FREE_PLANS = {
    1: {"name": "Starter Cloud", "invites": 2, "ram": 2, "cpu": 1, "disk": 20},
    2: {"name": "Basic Cloud", "invites": 4, "ram": 4, "cpu": 2, "disk": 30},
    3: {"name": "Pro Cloud", "invites": 8, "ram": 8, "cpu": 4, "disk": 50},
    4: {"name": "Ultra Cloud", "invites": 16, "ram": 16, "cpu": 6, "disk": 80},
    5: {"name": "Extreme Cloud", "invites": 24, "ram": 32, "cpu": 8, "disk": 120},
    6: {"name": "God Mode Cloud", "invites": 32, "ram": 64, "cpu": 12, "disk": 200},
}

# Paid VPS Plans (Currency/UPI-based)
PAID_PLANS = {
    1: {"name": "Starter Paid", "price": 20, "ram": 2, "cpu": 1, "disk": 20},
    2: {"name": "Basic Paid", "price": 50, "ram": 4, "cpu": 2, "disk": 40},
    3: {"name": "Pro Paid", "price": 100, "ram": 8, "cpu": 4, "disk": 60},
    4: {"name": "Ultra Paid", "price": 180, "ram": 16, "cpu": 6, "disk": 100},
    5: {"name": "Extreme Paid", "price": 280, "ram": 32, "cpu": 8, "disk": 150},
    6: {"name": "Super Paid", "price": 380, "ram": 64, "cpu": 12, "disk": 250},
    7: {"name": "Monster Paid", "price": 450, "ram": 78, "cpu": 16, "disk": 350},
}

class CustomBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_command = None
        self._last_command_time = 0

    async def process_commands(self, message):
        if message.author.bot:
            return
        
        current_time = time.time()
        if self._last_command == message.content and (current_time - self._last_command_time < 2):
            return
        
        self._last_command = message.content
        self._last_command_time = current_time
        await super().process_commands(message)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = CustomBot(command_prefix='.', intents=intents)

# Docker Client Initialization
try:
    client = docker.from_env()
except Exception as e:
    print(f"[WARNING] Failed to initialize Docker client: {e}")
    client = None

# Global Data Stores
vps_data = {}
economy_data = {}

# ----------------- Helper Functions -----------------

def load_economy_data():
    global economy_data
    if os.path.exists(ECONOMY_FILE):
        with open(ECONOMY_FILE, 'r') as f:
            economy_data = json.load(f)

def save_economy_data():
    with open(ECONOMY_FILE, 'w') as f:
        json.dump(economy_data, f, indent=4)

def get_balance(user_id: int) -> int:
    uid = str(user_id)
    if uid not in economy_data:
        economy_data[uid] = {"balance": 0, "last_daily": None}
        save_economy_data()
    return economy_data[uid]["balance"]

def add_balance(user_id: int, amount: int):
    uid = str(user_id)
    if uid not in economy_data:
        economy_data[uid] = {"balance": 0, "last_daily": None}
    economy_data[uid]["balance"] += amount
    save_economy_data()

def load_vps_data():
    global vps_data
    if os.path.exists(VPS_STORAGE_FILE):
        with open(VPS_STORAGE_FILE, 'r') as f:
            vps_data = json.load(f)
        for token, data in vps_data.items():
            if 'vps_id' not in data:
                data['vps_id'] = generate_vps_id()
            if 'expires_at' not in data:
                data['expires_at'] = None
        save_vps_data()

def save_vps_data():
    with open(VPS_STORAGE_FILE, 'w') as f:
        json.dump(vps_data, f, indent=4)

def generate_token():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

def generate_vps_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def generate_upi_qr(upi_id, amount, note="DarknessCloud"):
    upi_url = f"upi://pay?pa={upi_id}&pn=DarknessCloud&am={amount}&cu=INR&tn={urllib.parse.quote(note)}"
    return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"

def has_admin_role(ctx):
    return any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles) or ctx.author.guild_permissions.administrator

async def get_user_invites(guild: discord.Guild, user: discord.User) -> int:
    try:
        invites = await guild.invites()
        return sum(inv.uses for inv in invites if inv.inviter and inv.inviter.id == user.id)
    except Exception as e:
        print(f"Error fetching invites: {e}")
        return 0

async def send_audit_log(embed: discord.Embed):
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"Failed to send audit log: {e}")

async def capture_ssh_session_line(process):
    try:
        while True:
            output = await process.stdout.readline()
            if not output:
                break
            output = output.decode('utf-8', errors='ignore').strip()
            if "ssh session:" in output:
                return output.split("ssh session:")[1].strip()
        return None
    except Exception as e:
        print(f"Error capturing SSH session: {e}")
        return None

def count_user_servers(userid):
    return sum(1 for data in vps_data.values() if data.get("created_by") == str(userid))

async def run_docker_command(container_id, command, timeout=120):
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            if process.returncode != 0:
                raise Exception(f"Command failed: {stderr.decode()}")
            return stdout.decode('utf-8')
        except asyncio.TimeoutError:
            process.kill()
            raise Exception(f"Command timed out after {timeout} seconds")
    except Exception as e:
        print(f"Error running Docker command: {e}")
        return None

async def setup_netplan(container_id):
    netplan_config = """network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: true
      optional: true
"""
    try:
        cmd = f"mkdir -p /etc/netplan && echo '{netplan_config}' > /etc/netplan/01-netcfg.yaml && chmod 600 /etc/netplan/01-netcfg.yaml"
        await run_docker_command(container_id, ["bash", "-c", cmd])
        await run_docker_command(container_id, ["bash", "-c", "netplan apply || true"])
        return True
    except Exception as e:
        print(f"Netplan warning: {e}")
        return False

async def setup_container(container_id, memory):
    try:
        container = client.containers.get(container_id)
        if container.status != "running":
            container.start()
            await asyncio.sleep(5)

        update_process = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "bash", "-c", 
            "apt-get update && apt-get install -y tmate passwd procps net-tools netplan.io iproute2",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await update_process.communicate()
        await setup_netplan(container_id)

        await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "bash", "-c", "echo 'darkness__cloud' > /etc/hostname && hostname darkness__cloud",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        return True
    except Exception as e:
        print(f"Container setup failed: {e}")
        return False

async def deploy_vps_for_user(user: discord.User, plan: dict):
    if not client:
        raise Exception("Docker client unavailable.")

    vps_id = generate_vps_id()
    memory_bytes = plan['ram'] * 1024 * 1024 * 1024

    container = client.containers.run(
        "ubuntu:22.04", detach=True, privileged=True, hostname="darkness__cloud",
        mem_limit=memory_bytes, cpu_period=100000, cpu_quota=int(plan['cpu'] * 100000),
        cap_add=["ALL"], command="tail -f /dev/null", tty=True
    )

    await asyncio.sleep(3)
    await setup_container(container.id, plan['ram'])

    exec_cmd = await asyncio.create_subprocess_exec(
        "docker", "exec", container.id, "tmate", "-F",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    ssh_session_line = await capture_ssh_session_line(exec_cmd)

    if not ssh_session_line:
        raise Exception("Failed to retrieve tmate session")

    token = generate_token()
    created_at = datetime.datetime.now().isoformat()

    vps_data[token] = {
        "vps_id": vps_id, "container_id": container.id, "memory": plan['ram'],
        "cpu": plan['cpu'], "disk": plan['disk'], "username": user.name,
        "created_by": str(user.id), "created_at": created_at, "expires_at": None,
        "tmate_session": ssh_session_line, "claimed_plan": plan['name']
    }
    save_vps_data()

    embed = discord.Embed(title="🎉 VPS Provisioned & Ready!", color=discord.Color.green())
    embed.add_field(name="📦 Plan", value=plan['name'], inline=True)
    embed.add_field(name="🆔 VPS ID", value=vps_id, inline=True)
    embed.add_field(name="💾 Memory", value=f"{plan['ram']} GB", inline=True)
    embed.add_field(name="⚡ CPU", value=f"{plan['cpu']} Core(s)", inline=True)
    embed.add_field(name="🌐 Network", value="`Netplan Configured ✅`", inline=False)
    embed.add_field(name="🔑 Access Token", value=f"`{token}`", inline=False)
    embed.add_field(name="🔒 SSH Session", value=f"```{ssh_session_line}```", inline=False)

    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        pass

    return vps_id

# ----------------- UI Views & Interactive Components -----------------

class TicketCloseView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Close Ticket 🔒", style=discord.ButtonStyle.red, custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("🔒 Closing this ticket in 5 seconds...", ephemeral=False)
        await asyncio.sleep(5)
        await interaction.channel.delete(reason="Ticket closed by user/staff.")

class TicketTypeSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="General Support", description="Help with general questions or bot setup", emoji="❓"),
            discord.SelectOption(label="VPS Assistance", description="Troubleshooting and support for active VPS", emoji="💻"),
            discord.SelectOption(label="Billing & Orders", description="Payment verification and order inquiries", emoji="💳"),
        ]
        super().__init__(placeholder="Select the type of ticket to open...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.author
        ticket_type = self.values[0]

        category = discord.utils.get(guild.categories, name="Tickets")
        if not category:
            category = await guild.create_category("Tickets")

        ticket_channel_name = f"ticket-{user.name.lower().replace(' ', '-')}"
        
        existing_channel = discord.utils.get(guild.text_channels, name=ticket_channel_name)
        if existing_channel:
            await interaction.response.send_message(f"❌ You already have an open ticket: {existing_channel.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        admin_role = guild.get_role(ADMIN_ROLE_ID)
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_channel = await guild.create_text_channel(name=ticket_channel_name, category=category, overwrites=overwrites)

        embed = discord.Embed(
            title=f"🎫 {ticket_type} Ticket Created",
            description=f"Welcome {user.mention}! Staff will assist you shortly.\n\nPlease describe your request in detail.",
            color=discord.Color.blue()
        )
        await ticket_channel.send(content=f"{user.mention} | <@&{ADMIN_ROLE_ID}>", embed=embed, view=TicketCloseView())
        await interaction.response.send_message(f"✅ Ticket channel created: {ticket_channel.mention}", ephemeral=True)

class TicketSetupView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())

# ----------------- Antinuke Security Core -----------------

async def handle_antinuke(guild: discord.Guild, action_type: str):
    async for entry in guild.audit_logs(limit=1):
        user = entry.user
        if user.id == bot.user.id or user.id == guild.owner_id or user.id in ANTINUKE_WHITELIST:
            return

        member = guild.get_member(user.id)
        if member:
            try:
                await member.edit(roles=[], reason=f"[ANTINUKE] Triggered: {action_type}")
            except Exception as e:
                print(f"[ANTINUKE ERROR] Failed to revoke roles: {e}")

        embed = discord.Embed(title="🛡️ Antinuke Defense Activated", color=discord.Color.dark_red())
        embed.add_field(name="Violation", value=action_type, inline=True)
        embed.add_field(name="Offender", value=f"{user.mention} (`{user.id}`)", inline=True)
        embed.add_field(name="Action Taken", value="Stripped all user roles", inline=False)
        await send_audit_log(embed)

@bot.event
async def on_guild_channel_delete(channel):
    await handle_antinuke(channel.guild, f"Channel Deleted: #{channel.name}")

@bot.event
async def on_guild_role_delete(role):
    await handle_antinuke(role.guild, f"Role Deleted: @{role.name}")

@bot.event
async def on_member_ban(guild, user):
    await handle_antinuke(guild, f"Member Banned: {user.name}")

# ----------------- Background Loops & Startup -----------------

@tasks.loop(minutes=30)
async def check_vps_expiry():
    now = datetime.datetime.now()
    to_delete = []

    for token, vps in list(vps_data.items()):
        expires_str = vps.get('expires_at')
        if expires_str:
            expires_at = datetime.datetime.fromisoformat(expires_str)
            if now >= expires_at:
                to_delete.append((token, vps))

    for token, vps in to_delete:
        container_id = vps.get('container_id')
        try:
            container = client.containers.get(container_id)
            container.stop()
            container.remove()
        except Exception as e:
            print(f"Error removing expired container {container_id}: {e}")

        del vps_data[token]
        save_vps_data()

@bot.event
async def on_ready():
    print(f"✅ Bot successfully online as {bot.user}")
    load_vps_data()
    load_economy_data()
    bot.add_view(TicketCloseView())
    if not check_vps_expiry.is_running():
        check_vps_expiry.start()

# ----------------- Command Modules -----------------

@bot.command(name='commands')
async def show_commands(ctx):
    """List all available system commands"""
    embed = discord.Embed(title="🤖 DarknessCloud Command Directory", color=discord.Color.blue())
    
    embed.add_field(name="🪙 Economy", value="`.balance`, `.daily`, `.pay <@user> <amount>`", inline=False)
    embed.add_field(name="💳 Paid VPS", value="`.buy [plan_id]`, `.payproof <plan_id> <utr>`", inline=False)
    embed.add_field(name="🎁 Free VPS & Invites", value="`.deploy [plan_id]`, `.invites [@user]`, `.list`", inline=False)
    embed.add_field(name="⚙️ Control Panel", value="`.manage_vps <vps_id>`, `.stats <vps_id>`, `.logs <vps_id>`, `.reset_pass <vps_id> <pass>`", inline=False)

    if has_admin_role(ctx):
        embed.add_field(name="🛡️ Admin & Moderation", value="`.ticket_setup`, `.economy_add`, `.economy_remove`, `.create_vps`, `.delete_vps`", inline=False)

    await ctx.send(embed=embed)

@bot.command(name='invites')
async def check_invites_cmd(ctx, member: discord.Member = None):
    """Inspect user invite tally"""
    target = member or ctx.author
    if not ctx.guild:
        await ctx.send("❌ Command must be executed within a server.")
        return

    invites_count = await get_user_invites(ctx.guild, target)
    embed = discord.Embed(title=f"📨 Invite Tally - {target.display_name}", color=discord.Color.green())
    embed.add_field(name="Tracked Invites", value=f"**{invites_count} Uses**", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='ticket_setup')
@commands.check(has_admin_role)
async def ticket_setup_cmd(ctx):
    """Deploy Ticket System Panel (Admin Only)"""
    embed = discord.Embed(
        title="🎫 DarknessCloud Support Center",
        description="Need assistance? Choose a ticket option from the menu below to talk to staff.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=TicketSetupView())

@bot.command(name='balance', aliases=['bal'])
async def check_balance(ctx, member: discord.Member = None):
    """Check wallet balance"""
    target = member or ctx.author
    bal = get_balance(target.id)
    embed = discord.Embed(title=f"🪙 Wallet Balance - {target.display_name}", color=discord.Color.gold())
    embed.add_field(name="Balance", value=f"**{bal} Coins**", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='daily')
async def claim_daily(ctx):
    """Claim daily economy reward"""
    uid = str(ctx.author.id)
    if uid not in economy_data:
        economy_data[uid] = {"balance": 0, "last_daily": None}

    now = datetime.datetime.now()
    last_daily_str = economy_data[uid].get("last_daily")

    if last_daily_str:
        last_daily = datetime.datetime.fromisoformat(last_daily_str)
        if now - last_daily < datetime.timedelta(hours=24):
            remaining = datetime.timedelta(hours=24) - (now - last_daily)
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            await ctx.send(f"⌛ Daily bonus is on cooldown! Return in `{hours}h {minutes}m`.")
            return

    reward = random.randint(100, 500)
    add_balance(ctx.author.id, reward)
    economy_data[uid]["last_daily"] = now.isoformat()
    save_economy_data()

    await ctx.send(f"🎉 Claimed **{reward} Coins**! Total Balance: `{get_balance(ctx.author.id)} Coins`.")

@bot.command(name='deploy')
async def deploy_free_vps(ctx, plan_id: int):
    """Claim a Free VPS using Server Invites"""
    if plan_id not in FREE_PLANS:
        await ctx.send("❌ Invalid plan ID. Use `.list` to inspect valid plans.")
        return

    plan = FREE_PLANS[plan_id]
    user_invites = await get_user_invites(ctx.guild, ctx.author)

    if user_invites < plan['invites']:
        await ctx.send(f"❌ You need **{plan['invites']} invites** for {plan['name']} (You have {user_invites}).")
        return

    if count_user_servers(ctx.author.id) >= MAX_VPS_PER_USER and not has_admin_role(ctx):
        await ctx.send(f"❌ You have reached the maximum server allowance of {MAX_VPS_PER_USER}.")
        return

    status_msg = await ctx.send(f"🔄 Provisioning **{plan['name']}**... Please wait.")
    try:
        vps_id = await deploy_vps_for_user(ctx.author, plan)
        await status_msg.edit(content=f"✅ VPS **{vps_id}** deployed! Details sent to your Direct Messages.")
    except Exception as e:
        await status_msg.edit(content=f"❌ Provisioning failed: {e}")

@bot.command(name='buy')
async def buy_paid_vps(ctx, plan_id: int):
    """Generate UPI QR payment code for Paid VPS"""
    if plan_id not in PAID_PLANS:
        await ctx.send("❌ Invalid paid plan ID.")
        return

    plan = PAID_PLANS[plan_id]
    qr_url = generate_upi_qr(UPI_ID, plan['price'], f"VPS Plan {plan_id}")

    embed = discord.Embed(title=f"💳 Payment Details for {plan['name']}", color=discord.Color.gold())
    embed.add_field(name="Amount", value=f"₹{plan['price']} INR", inline=True)
    embed.add_field(name="UPI ID", value=f"`{UPI_ID}`", inline=True)
    embed.set_image(url=qr_url)
    embed.set_footer(text="After paying, submit proof via: .payproof <plan_id> <UTR_Number>")

    await ctx.send(embed=embed)

@bot.command(name='payproof')
async def submit_payproof(ctx, plan_id: int, utr: str):
    """Submit UTR payment proof for review"""
    if plan_id not in PAID_PLANS:
        await ctx.send("❌ Invalid plan ID.")
        return

    if PROOF_CHANNEL_ID == 0:
        await ctx.send("❌ Verification channel is not configured.")
        return

    proof_channel = bot.get_channel(PROOF_CHANNEL_ID)
    if proof_channel:
        embed = discord.Embed(title="🧾 New Payment Proof Submitted", color=discord.Color.blue())
        embed.add_field(name="User", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=True)
        embed.add_field(name="Plan ID", value=f"Plan #{plan_id} ({PAID_PLANS[plan_id]['name']})", inline=True)
        embed.add_field(name="UTR / Ref No.", value=f"`{utr}`", inline=False)
        await proof_channel.send(embed=embed)
        await ctx.send("✅ Payment proof submitted successfully! Staff will review it shortly.")

# ----------------- Main Entry Point -----------------

if __name__ == "__main__":
    if not TOKEN:
        print("[ERROR] DISCORD_TOKEN environment variable not set!")
    else:
        bot.run(TOKEN)
