sudo bash -c '
set -e

# ==========================================
# 🔑 AUTHORIZED LICENSES & EXPIRY DATES
# Format: "KEY:YYYY-MM-DD"
# ==========================================
VALID_LICENSES=(
  "DARKNESS-PREMIUM-2026:2026-12-31"
  "DARKNESS-TRIAL-30DAYS:2026-09-09"
  "DARKNESS-VIP-KEY:2027-01-01"
)

clear
echo "=================================================================="
echo "          🔒 DARKNESS CLOUD LICENSE VERIFICATION 🔒             "
echo "=================================================================="
echo ""
echo "   +----------------------------------------------------------+"
echo "   |                   📸 PROOF OF PURCHASE                    |"
echo "   |                                                          |"
echo "   |   Please paste your LICENSE KEY below.                  |"
echo "   |   If expired or invalid, send your payment screenshot    |"
echo "   |   (SS) to the owner/support channel to get a new key.    |"
echo "   +----------------------------------------------------------+"
echo ""

read -p "🔑 Enter your LICENSE KEY: " USER_LICENSE_KEY

CURRENT_DATE=$(date +%Y-%m-%d)
KEY_VALID=false
KEY_EXPIRED=false
EXPIRY_DATE=""

for item in "${VALID_LICENSES[@]}"; do
    KEY="${item%%:*}"
    EXP="${item#*:}"
    if [ "$USER_LICENSE_KEY" == "$KEY" ]; then
        KEY_VALID=true
        EXPIRY_DATE="$EXP"
        if [[ "$CURRENT_DATE" > "$EXP" ]]; then
            KEY_EXPIRED=true
        fi
        break
    fi
done

if [ "$KEY_VALID" = false ]; then
    echo ""
    echo "❌ [LICENSE ERROR] Invalid License Key!"
    echo "📸 Please share your Payment Screenshot (SS) to get a valid Key."
    echo "=================================================================="
    exit 1
elif [ "$KEY_EXPIRED" = true ]; then
    echo ""
    echo "⌛ [TERM EXPIRED] License Term Expired on: $EXPIRY_DATE"
    echo "📸 Send renewal payment screenshot (SS) to extend your subscription."
    echo "=================================================================="
    exit 1
fi

echo ""
echo "✅ License Key Verified! Valid Term Until: $EXPIRY_DATE"
echo "=================================================================="
echo "🚀 Starting Complete Installation (Docker + LXD + Git Clone + Venv)"
echo "=================================================================="

# 1. Update system & install core packages
apt-get update && apt-get install -y \
  python3 python3-pip python3-venv git curl docker.io ca-certificates \
  nano snapd procps psmisc lxc lxc-utils bridge-utils zfsutils-linux

# 2. Enable & start Docker service
systemctl enable --now docker

# 3. Install & initialize LXC / LXD automatically
echo "📦 Initializing LXD / LXC..."
if ! command -v lxd &> /dev/null; then
    snap install lxd --channel=latest/stable || apt-get install -y lxd
fi
lxd init --auto || true

# 4. Clone GitHub repository directly into workspace
INSTALL_DIR="/opt/darkness_cloud_bot"
rm -rf "$INSTALL_DIR"

echo "📥 Cloning repository from GitHub (Hunter89p/Bro)..."
git clone https://github.com/Hunter89p/Bro.git "$INSTALL_DIR"
cd "$INSTALL_DIR"

# 5. Setup Python Virtual Environment & Install All Pip Requirements
echo "🐍 Setting up Python venv and installing requirements..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip setuptools wheel
./venv/bin/pip install discord.py docker python-dotenv psutil requests aiohttp

# 6. Generate .env Configuration using verified License & Term Expiry
echo "⚙️ Writing .env configuration file..."
cat << EOT > .env
# ==========================================
# DarknessCloud Complete Configuration
# ==========================================

LICENSE_KEY=$USER_LICENSE_KEY
LICENSE_EXPIRY=$EXPIRY_DATE
DISCORD_TOKEN=your_bot_token_here
MAIN_OWNER_ID=123456789012345678

ADMIN_ROLE_ID=123456789012345678
ANTINUKE_WHITELIST=123456789012345678,876543210987654321

LOG_CHANNEL_ID=123456789012345678
PROOF_CHANNEL_ID=123456789012345678

MAX_VPS_PER_USER=5
UPI_ID=yourupi@upi
EOT

# 7. Configure systemd service for 24/7 background operation
echo "🛠️ Creating systemd service..."
cat << "EOT" > /etc/systemd/system/darknessbot.service
[Unit]
Description=DarknessCloud Discord Bot Service
After=network.target docker.service lxd.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/darkness_cloud_bot
ExecStart=/opt/darkness_cloud_bot/venv/bin/python3 /opt/darkness_cloud_bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOT

systemctl daemon-reload
systemctl enable darknessbot

echo "=================================================================="
echo "✅ Installation Complete! License Active Until: $EXPIRY_DATE"
echo "📁 Directory: $INSTALL_DIR"
echo "=================================================================="
'
