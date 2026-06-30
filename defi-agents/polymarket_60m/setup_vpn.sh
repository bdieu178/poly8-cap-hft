#!/bin/bash
# High-Fidelity HFT VPN Setup Script
# Isolates the Polymarket Hot-Path in a dedicated Network Namespace (polymask)

NS="polymask"
IF="wg0"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
CONF="$SCRIPT_DIR/config/WireGuard.conf"

# 1. Cleanup existing setup
sudo ip netns delete $NS 2>/dev/null
sudo ip link delete $IF 2>/dev/null

# 2. Add namespace
sudo ip netns add $NS
echo "[1/4] Created namespace: $NS"

# 3. Create and configure WireGuard interface in main namespace
sudo ip link add $IF type wireguard
grep -vE "DNS =|Address =" $CONF > /tmp/wg_clean.conf
sudo wg setconf $IF /tmp/wg_clean.conf
rm /tmp/wg_clean.conf
echo "[2/4] Initialized $IF with ProtonVPN config"

# 4. Move interface to namespace and configure
sudo ip link set $IF netns $NS
sudo ip netns exec $NS ip addr add 10.2.0.2/32 dev $IF
sudo ip netns exec $NS ip link set $IF mtu 1280
sudo ip netns exec $NS ip link set $IF up
sudo ip netns exec $NS ip link set lo up
sudo ip netns exec $NS ip route add default dev $IF
echo "[3/4] Moved $IF to $NS and established default route"

# 5. Configure DNS for the namespace
sudo mkdir -p /etc/netns/$NS
echo -e "nameserver 10.2.0.1\nnameserver 8.8.8.8" | sudo tee /etc/netns/$NS/resolv.conf > /dev/null
echo "[4/4] Configured DNS for $NS"

# 6. Verify connection
echo "--- Verifying VPN Connection ---"
if sudo ip netns exec $NS curl -s --max-time 10 https://ifconfig.me > /dev/null; then
    echo "VPN: ONLINE"
    VPN_IP=$(sudo ip netns exec $NS curl -s https://ifconfig.me)
    echo "Namespace IP: $VPN_IP"
else
    echo "VPN: OFFLINE"
fi
sudo ip netns exec $NS wg show
