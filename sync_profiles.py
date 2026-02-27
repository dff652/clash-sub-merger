#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_profiles.py - 从 GlaDOS 订阅同步生成 profiles

功能：获取 GlaDOS 订阅，提取 proxy-groups，自动生成 profiles/<client>.yaml
支持客户端：mihomo, clash

使用方法：
    python sync_profiles.py                # 同步所有客户端
    python sync_profiles.py -t mihomo      # 只同步 mihomo
    python sync_profiles.py -t clash       # 只同步 clash
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml

from utils import (
    setup_logger,
    load_config,
    load_local_subscription,
    download_subscription,
)

# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
logger = setup_logger("sync_profiles", str(SCRIPT_DIR / "logs"))

# 支持的客户端类型
SUPPORTED_CLIENTS = ["mihomo", "clash"]


def generate_profile(client: str, glados_data: dict) -> str:
    """从 GlaDOS 订阅数据生成 profile 文件内容"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    glados_groups = glados_data.get("proxy-groups", [])

    lines = [
        f"# ===== 方案：{client} =====",
        f"# 自动同步自 GlaDOS {client} 订阅（{now}）",
        f"# 运行 python sync_profiles.py -t {client} 更新此文件",
        f"",
        f"needs_glados: true",
        f"glados_client: {client}",
        f"",
        f"proxy_groups:",
        f"  # --- VPS 节点（Sub-Store，追加）---",
        f"  - name: VPS",
        f"    type: select",
        f'    use: ["{{PROVIDER}}"]',
        f"",
    ]

    for g in glados_groups:
        lines.append(f"  - name: {g['name']}")
        lines.append(f"    type: {g['type']}")
        if g.get("url"):
            lines.append(f'    url: "{g["url"]}"')
        if g.get("interval"):
            lines.append(f"    interval: {g['interval']}")
        if g.get("tolerance"):
            lines.append(f"    tolerance: {g['tolerance']}")

        proxies = g.get("proxies", [])
        if proxies:
            lines.append(f"    proxies:")
            for p in proxies:
                lines.append(f'      - "{p}"')
            if g["name"] == "Proxy":
                lines.append(f'      - "VPS"')

        lines.append("")

    return "\n".join(lines)


def write_log(log_dir: Path, client: str, status: str, n_groups: int, source: str):
    """追加同步日志到 generate.log"""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "generate.log"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = (
        f"{now} | SYNC  | {client:10s} "
        f"| {status:4s} | {n_groups:2d} groups "
        f"| from: {source}\n"
    )
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(log_line)


def sync_client(cfg: dict, client: str) -> bool:
    """同步单个客户端的 profile，返回是否成功"""
    # 优先从 download/ 目录读取
    download_dir = SCRIPT_DIR / cfg.get("download_dir", "download")
    local_file = download_dir / f"glados_{client}.yaml"

    if local_file.exists():
        data = load_local_subscription(str(local_file), name=f"GlaDOS {client}", logger=logger)
        source = "local"
    else:
        # 本地文件不存在，尝试在线下载
        glados_urls = cfg.get("glados_urls", {})
        url = glados_urls.get(client, "")
        if not url:
            logger.warning("未配置 %s 的订阅链接，跳过", client)
            return False

        save_path = str(local_file)
        min_proxies = cfg.get("min_proxy_count", 5)
        data, source = download_subscription(
            url=url,
            save_path=save_path,
            name=f"GlaDOS {client}",
            min_proxies=min_proxies,
            logger=logger,
        )

    if data is None:
        logger.error("❌ %s: 获取失败且无本地文件", client)
        log_dir = SCRIPT_DIR / cfg.get("log_dir", "logs")
        write_log(log_dir, client, "fail", 0, "fail")
        return False

    # 提取 proxy-groups
    glados_groups = data.get("proxy-groups", [])
    if not glados_groups:
        logger.warning("⚠️  %s: 订阅中没有 proxy-groups，跳过 profile 同步", client)
        logger.info("   提示: %s 订阅可能不包含分组信息，请手动维护 profiles/%s.yaml", client, client)
        return False

    # 生成 profile 文件
    profile_content = generate_profile(client, data)
    profiles_dir = SCRIPT_DIR / cfg.get("profiles_dir", "profiles")
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profiles_dir / f"{client}.yaml"
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write(profile_content)

    # 写入日志
    log_dir = SCRIPT_DIR / cfg.get("log_dir", "logs")
    write_log(log_dir, client, "ok", len(glados_groups), source)

    logger.info("✅ %s: 已同步 %d 个分组 → %s (来源: %s)",
                client, len(glados_groups), profile_path, source)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="从 GlaDOS 订阅同步生成 profiles"
    )
    parser.add_argument(
        "-c", "--config",
        default=str(SCRIPT_DIR / "conf" / "config.yaml"),
        help="配置文件路径（默认: conf/config.yaml）",
    )
    parser.add_argument(
        "-t", "--type",
        choices=SUPPORTED_CLIENTS,
        default=None,
        help="只同步指定客户端（mihomo / clash）",
    )
    args = parser.parse_args()

    cfg = load_config(args.config, logger=logger)

    clients = [args.type] if args.type else SUPPORTED_CLIENTS

    success = 0
    for client in clients:
        if sync_client(cfg, client):
            success += 1

    logger.info("同步完成: %d/%d 成功", success, len(clients))


if __name__ == "__main__":
    main()
