#!/bin/bash
set -euo pipefail

echo "=========================================================="
echo " Redrum-AI Edge Optimization Setup Script                 "
echo "=========================================================="

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root. Please run with sudo." 
   exit 1
fi

echo "[*] Step 1: Please ensure you have manually set the UMA Frame Buffer Size in your BIOS to the lowest setting (64MB/128MB)."

echo "[*] Step 2: Disabling zswap in GRUB..."
if grep -q "GRUB_CMDLINE_LINUX_DEFAULT" /etc/default/grub; then
    if ! grep -q "zswap.enabled=0" /etc/default/grub; then
        sed -i 's/\(GRUB_CMDLINE_LINUX_DEFAULT="[^"]*\)"/\1 zswap.enabled=0"/' /etc/default/grub
        update-grub
    else
        echo "zswap.enabled=0 already set."
    fi
fi

echo "[*] Step 3: Installing ZRam and vmtouch..."
apt-get update
# Remove systemd-zram-generator to prevent conflicts with zram-tools
apt-get remove -y systemd-zram-generator || true
apt-get install -y zram-tools vmtouch

echo "[*] Step 4: Configuring ZRam..."
cat <<EOF > /etc/default/zramswap
ALGO=zstd
PERCENT=60
EOF

if systemctl --version >/dev/null 2>&1; then
    systemctl restart zramswap.service || true
else
    service zramswap restart || true
fi

echo "[*] Step 5: Applying sysctl virtual memory tweaks..."
cat <<EOF > /etc/sysctl.d/99-zram-tweaks.conf
vm.swappiness=80
vm.vfs_cache_pressure=50
EOF
sysctl --system

echo "[*] Step 6: Clearing active caches..."
echo 3 > /proc/sys/vm/drop_caches

echo "[*] Step 7: Preparing vmtouch model pin..."
USER_HOME=$(eval echo ~${SUDO_USER:-redrum})
MODEL_PATH="${REDRUM_AI_MODEL_PATH:-$USER_HOME/.ollama/models/blobs/sha256-gemma-3-4b-it-Q4_0.gguf}"
if [ ! -f "$MODEL_PATH" ] && [ -f "$USER_HOME/usb-ai/AI/models/gemma-2-2b-it-Q4_K_M.gguf" ]; then
    MODEL_PATH="$USER_HOME/usb-ai/AI/models/gemma-2-2b-it-Q4_K_M.gguf"
fi

echo "[*] Configuring memlock limits for the vmtouch model..."
LIMIT_USER="${SUDO_USER:-redrum}"
install -d -m 0755 /etc/security/limits.d
cat > /etc/security/limits.d/redrum-ai-memlock.conf <<EOF
$LIMIT_USER soft memlock unlimited
$LIMIT_USER hard memlock unlimited
EOF
echo "    $LIMIT_USER may need to log out and back in before the new limit applies."

if [ -f "$MODEL_PATH" ]; then
    echo "Pinning $MODEL_PATH to RAM..."
    install -d -m 0755 "$USER_HOME/.local/state/redrum-ai"
    vmtouch -dl -w -P "$USER_HOME/.local/state/redrum-ai/vmtouch-model.pid" "$MODEL_PATH"
else
    echo "Warning: Model file not found at $MODEL_PATH."
    echo "Please download the model and run vmtouch manually:"
    echo "  vmtouch -dl -w /path/to/model.gguf"
fi

echo "=========================================================="
echo " Optimization complete! "
echo " Run redrum-ai with --config containing 'runtime_profile': 'constrained-edge'"
echo "=========================================================="
