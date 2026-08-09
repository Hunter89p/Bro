#!/bin/bash

# Color Definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}====================================================${NC}"
echo -e "${CYAN}   🚀 Darkness__cloud - Enterprise Installer        ${NC}"
echo -e "${CYAN}   (Docker, KVM, LXC/LXD & Economy Environment)     ${NC}"
echo -e "${CYAN}====================================================${NC}\n"

# 1. Check Root Privileges
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}❌ Please run this script as root or using sudo!${NC}"
  exit 1
fi

# 2. Update System & Install Dependencies
echo -e "${YELLOW}🔄 Updating system packages & installing core tools...${NC}"
apt-get update -y
apt-get install -y \
  python3 \
  python3-pip \
  python3-venv \
  docker.io \
  tmate \
  openssl \
  cpu-checker \
  curl \
  snapd \
  build-essential \
  libssl-dev \
  libffi-dev

# 3. Install & Initialize LXC / LXD
echo -e "${YELLOW}📦 Installing and configuring LXC / LXD virtualization...${NC}"
if ! command -v lxd &> /dev/null; then
    snap install lxd --channel=latest/stable || apt-get install -y lxd lxd-client
fi

# Ensure snap path is loaded
export PATH=$PATH:/snap/bin

# Non-interactive LXD Initialization
echo -e "${YELLOW}⚙️ Initializing LXD engine (--auto)...${NC}"
lxd init --auto

# Add root to LXD & Docker groups
usermod -aG lxd root 2>/dev/null
usermod -aG docker root 2>/dev/null

# 4. Enable and Start Docker Service
echo -e "${YELLOW}🐳 Configuring Docker service...${NC}"
systemctl enable --now docker

# 5. Enable KVM Virtualization Modules
echo -e "${YELLOW}⚡ Enabling Hardware KVM Support...${NC}"
modprobe kvm 2>/dev/null
modprobe kvm_intel 2>/dev/null || modprobe kvm_amd 2>/dev/null

if [ -e /dev/kvm ]; then
    chmod 666 /dev/kvm
    echo -e "${GREEN}✅ KVM device permissions configured (/dev/kvm).${NC}"
else
    echo -e "${RED}⚠️ Warning: /dev/kvm not found! Ensure hardware virtualization is enabled in BIOS/VPS hypervisor.${NC}"
fi

# 6. Set Active License Key
LICENSE_KEY="Ankit890"
echo -e "\n${GREEN}🔑 ACTIVE LICENSE KEY CONFIGURED:${NC} ${CYAN}${LICENSE_KEY}${NC}\n"

# 7. User Inputs
read -p "🔑 Enter your Discord Bot Token: " DISCORD_TOKEN
read -p "👑 Enter Admin Discord Role ID [Default: 1376177459870961694]: " ADMIN_ROLE_ID
ADMIN_ROLE_ID=${ADMIN_ROLE_ID:-1376177459870961694}

# 8. Create .env File
echo -e "${YELLOW}⚙️ Writing .env environment file...${NC}"
cat <<EOF > .env
DISCORD_TOKEN=${DISCORD_TOKEN}
BOT_LICENSE_KEY=${LICENSE_KEY}
EOF

# 9. Create config.json File
echo -e "${YELLOW}⚙️ Writing config.json file...${NC}"
cat <<EOF > config.json
{
  "bot": {
    "name": "Darkness__cloud",
    "prefix": "!",
    "admin_role_id": ${ADMIN_ROLE_ID}
  },
  "license": {
    "key": "${LICENSE_KEY}",
    "valid_licenses": {
      "${LICENSE_KEY}": {
        "owner": "Ankit890",
        "tier": "Enterprise / Master KVM Host",
        "expires": "2028-12-31",
        "active": true
      },
      "DARKNESS-CLOUD-883A-2026-PRO": {
        "owner": "Darkness Cloud Admin",
        "tier": "Enterprise / Dedicated KVM Host",
        "expires": "2027-12-31",
        "active": true
      }
    }
  },
  "economy": {
    "currency_symbol": "₹",
    "daily_cooldown_seconds": 86400,
    "daily_min_reward": 20,
    "daily_max_reward": 50
  },
  "vps_plans": {
    "starter": {
      "price": 20,
      "ram_gb": 2,
      "cpu_cores": 1,
      "disk_gb": 10
    },
    "basic": {
      "price": 50,
      "ram_gb": 8,
      "cpu_cores": 2,
      "disk_gb": 25
    },
    "pro": {
      "price": 120,
      "ram_gb": 16,
      "cpu_cores": 4,
      "disk_gb": 50
    },
    "ultra": {
      "price": 220,
      "ram_gb": 32,
      "cpu_cores": 8,
      "disk_gb": 100
    },
    "max": {
      "price": 350,
      "ram_gb": 78,
      "cpu_cores": 16,
      "disk_gb": 200
    }
  },
  "docker": {
    "default_image": "ubuntu:22.04",
    "hostname_prefix": "darkness-kvm",
    "enable_kvm": true,
    "dedicated_resources": true,
    "devices": ["/dev/kvm:/dev/kvm"],
    "capabilities": ["NET_ADMIN", "SYS_ADMIN"]
  }
}
EOF

# 10. Setup Python Virtual Environment and Install All Dependencies
echo -e "${YELLOW}📦 Creating Python virtual environment & installing pip packages...${NC}"
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install \
  discord.py \
  docker \
  python-dotenv \
  psutil \
  requests \
  aiohttp \
  pydantic

echo -e "\n${GREEN}====================================================${NC}"
echo -e "${GREEN}🎉 FULL INSTALLATION & SYSTEM INITIALIZATION COMPLETE! ${NC}"
echo -e "${GREEN}====================================================${NC}"
echo -e "🔑 ${YELLOW}Active License Key:${NC} ${LICENSE_KEY}"
echo -e "🐳 ${YELLOW}Docker Engine:${NC} Active"
echo -e "📦 ${YELLOW}LXD Virtualization:${NC} Initialized (--auto)"
echo -e "📄 ${YELLOW}Config File:${NC} config.json"
echo -e "🔐 ${YELLOW}Environment File:${NC} .env"
echo -e "\n${CYAN}To start your bot now, execute:${NC}"
echo -e "   source venv/bin/activate"
echo -e "   python3 bot.py"
echo -e "${GREEN}====================================================${NC}"
