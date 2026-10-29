#!/bin/bash

# ======================== 配置 ========================
PASSWORD="Creality2024"
USERNAME="root"
DEVICE_BASE="/usr/share/klipper"
LOCAL_BASE="$(pwd)"
SERVICE_RESTART="/etc/init.d/klipper restart"
CONFIG_FILE=".last_klipper_deploy.conf"
# ======================================================

# 加载上一次的参数
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
fi

# ======= 函数：带默认值的用户输入 =======
function prompt_param() {
    local prompt_text=$1
    local var_name=$2
    local default_val=$3

    local input
    read -e -p "$prompt_text [$default_val]: " input

    if [[ -z "$input" && -n "$default_val" ]]; then
        eval "$var_name=\"$default_val\""
    elif [[ -n "$input" ]]; then
        eval "$var_name=\"$input\""
    else
        echo "❌ 错误：参数不能为空"
        exit 1
    fi
}
# =========================================

# ======= 获取用户输入 =======
prompt_param "请输入本地相对文件路径（例如 klippy/extras/box_wrapper.py）" REL_PATH "$LAST_REL_PATH"
prompt_param "请输入设备 IP 地址" DEVICE_IP "$LAST_DEVICE_IP"
# ===========================

# ======= 保存参数 =======
cat > "$CONFIG_FILE" <<EOF
LAST_REL_PATH="$REL_PATH"
LAST_DEVICE_IP="$DEVICE_IP"
EOF
# =========================

# ======= 构造路径 =======
LOCAL_FILE="$LOCAL_BASE/$REL_PATH"
REMOTE_FILE="$DEVICE_BASE/$REL_PATH"
REMOTE_DIR=$(dirname "$REMOTE_FILE")
FILENAME=$(basename -- "$REL_PATH")
MODULE_NAME="${FILENAME%.*}"
SO_FILE="$REMOTE_DIR/${MODULE_NAME}.cpython-39.so"
SO_BAK="$REMOTE_DIR/${MODULE_NAME}.cpython-39.sobak"
# =========================

# ======= 验证本地文件 =======
if [[ ! -f "$LOCAL_FILE" ]]; then
    echo "❌ 本地文件不存在：$LOCAL_FILE"
    exit 1
fi
# ==============================

# ======= 部署开始 =======
echo "🕒 开始部署：$(date '+%Y-%m-%d %H:%M:%S')"
echo "🚀 目标设备：$DEVICE_IP"
echo "📂 上传文件：$LOCAL_FILE"
echo "📁 目标路径：$REMOTE_FILE"
echo "🔄 .so备份路径（如存在）：$SO_BAK"

# 移除 known_hosts 中旧指纹，防止冲突
ssh-keygen -R "$DEVICE_IP" >/dev/null 2>&1

# 创建远程目录
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$USERNAME@$DEVICE_IP" "mkdir -p '$REMOTE_DIR'"

# 备份旧 .so 文件（如果存在）
echo ">>> 检查并备份 .so 文件..."
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$USERNAME@$DEVICE_IP" \
    "[ -f '$SO_FILE' ] && mv '$SO_FILE' '$SO_BAK' && echo '✅ 已备份旧 .so 文件' || echo '✅ 无需备份 .so 文件'"

# 上传文件
echo ">>> 上传文件中..."
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no "$LOCAL_FILE" "$USERNAME@$DEVICE_IP:$REMOTE_FILE"

# 重启 klipper
echo ">>> 重启 klipper 服务..."
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$USERNAME@$DEVICE_IP" "$SERVICE_RESTART"

# 完成
echo "✅ 部署完成！完成时间：$(date '+%Y-%m-%d %H:%M:%S')"
