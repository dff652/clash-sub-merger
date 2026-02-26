#!/usr/bin/env bash
# ===== Clash 订阅合并工具 =====
# 交互菜单 & 命令行模式
#
# 交互模式: ./run.sh
# 命令模式: ./run.sh sync [mihomo|clash]
#           ./run.sh merge [mihomo|clash|custom|vps]
#           ./run.sh list
#           ./run.sh log

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---------------------------------------------------------------------------
# 功能函数
# ---------------------------------------------------------------------------

do_sync() {
    local target="$1"
    if [ -n "$target" ]; then
        echo -e "${CYAN}▸ 同步 ${target} profile...${NC}"
        python3 sync_profiles.py -t "$target"
    else
        echo -e "${CYAN}▸ 同步所有客户端 profiles...${NC}"
        python3 sync_profiles.py
    fi
}

do_merge() {
    local profile="${1:-mihomo}"
    echo -e "${CYAN}▸ 合并生成 ${profile} 配置...${NC}"
    python3 merge_glados.py -p "$profile"
}

do_list() {
    python3 merge_glados.py --list-profiles
}

do_log() {
    local log_file="logs/generate.log"
    if [ -f "$log_file" ]; then
        echo -e "${BLUE}===== 最近 20 条记录 =====${NC}"
        tail -20 "$log_file"
    else
        echo -e "${YELLOW}暂无日志${NC}"
    fi
}

# ---------------------------------------------------------------------------
# 命令行模式
# ---------------------------------------------------------------------------

if [ $# -gt 0 ]; then
    case "$1" in
        sync)
            do_sync "$2"
            ;;
        merge)
            do_merge "$2"
            ;;
        list)
            do_list
            ;;
        log)
            do_log
            ;;
        *)
            echo "用法: $0 [sync|merge|list|log] [参数]"
            echo ""
            echo "  sync [mihomo|clash]    同步 GlaDOS profiles"
            echo "  merge [profile]        合并生成配置（默认 mihomo）"
            echo "  list                   列出所有方案"
            echo "  log                    查看生成日志"
            exit 1
            ;;
    esac
    exit 0
fi

# ---------------------------------------------------------------------------
# 交互菜单模式
# ---------------------------------------------------------------------------

show_menu() {
    echo ""
    echo -e "${BLUE}=====================================${NC}"
    echo -e "${GREEN}  Clash 订阅合并工具${NC}"
    echo -e "${BLUE}=====================================${NC}"
    echo -e "  ${CYAN}1)${NC} 同步所有客户端 profiles"
    echo -e "  ${CYAN}2)${NC} 同步 mihomo profile"
    echo -e "  ${CYAN}3)${NC} 同步 clash profile"
    echo -e "  ${CYAN}4)${NC} 合并生成 mihomo 配置"
    echo -e "  ${CYAN}5)${NC} 合并生成 clash 配置"
    echo -e "  ${CYAN}6)${NC} 合并生成 custom 配置"
    echo -e "  ${CYAN}7)${NC} 合并生成 VPS 配置"
    echo -e "  ${CYAN}8)${NC} 查看所有方案"
    echo -e "  ${CYAN}9)${NC} 查看生成日志"
    echo -e "  ${RED}0)${NC} 退出"
    echo -e "${BLUE}=====================================${NC}"
    echo -ne "请选择 [0-9]: "
}

while true; do
    show_menu
    read -r choice
    echo ""
    case "$choice" in
        1) do_sync ;;
        2) do_sync mihomo ;;
        3) do_sync clash ;;
        4) do_merge mihomo ;;
        5) do_merge clash ;;
        6) do_merge custom ;;
        7) do_merge vps ;;
        8) do_list ;;
        9) do_log ;;
        0)
            echo -e "${GREEN}再见！${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}无效选项${NC}"
            ;;
    esac
done
