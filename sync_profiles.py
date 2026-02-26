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
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml
import requests

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
_log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_console = logging.StreamHandler()
_console.setFormatter(_log_fmt)

_log_dir = Path(__file__).parent / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(_log_dir / "detail.log", encoding="utf-8")
_file_handler.setFormatter(_log_fmt)

logger = logging.getLogger("sync_profiles")
logger.setLevel(logging.INFO)
logger.addHandler(_console)
logger.addHandler(_file_handler)

# 支持的客户端类型
SUPPORTED_CLIENTS = ["mihomo", "clash"]


def load_config(config_path: str) -> dict:
    """加载脚本配置文件"""
    path = Path(config_path)
    if not path.exists():
        logger.error("配置文件不存在: %s", config_path)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    logger.info("已加载配置文件: %s", config_path)
    return cfg


def fetch_glados(url: str, cache_file: str) -> dict:
    """
    从远程 URL 获取 GlaDOS 订阅。
    成功后保存缓存；失败时回退缓存。
    返回 (data, source) 其中 source 为 "online" 或 "cache"。
    """
    logger.info("正在获取订阅: %s", url[:60] + "...")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = yaml.safe_load(resp.text)
        # 保存缓存
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(resp.text)
        return data, "online"
    except requests.RequestException as e:
        logger.warning("获取失败: %s", e)
        if Path(cache_file).exists():
            logger.info("⚠️  回退使用本地缓存: %s", cache_file)
            with open(cache_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data, "cache"
        else:
            return None, "fail"


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
        f"    use: [sub3in1]",
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
            # 在 Proxy 组中追加 VPS 选项
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
    script_dir = Path(__file__).parent

    # 获取该客户端的 URL
    glados_urls = cfg.get("glados_urls", {})
    url = glados_urls.get(client, "")
    if not url:
        logger.warning("未配置 %s 的订阅链接，跳过", client)
        return False

    # 缓存路径按客户端区分
    cache_dir = script_dir / cfg.get("glados_cache_dir", "cache")
    cache_file = str(cache_dir / f"glados_{client}.yaml")

    # 获取订阅
    data, source = fetch_glados(url, cache_file)
    if data is None:
        logger.error("❌ %s: 获取失败且无缓存", client)
        log_dir = script_dir / cfg.get("log_dir", "logs")
        write_log(log_dir, client, "fail", 0, "fail")
        return False

    # 提取 proxy-groups
    glados_groups = data.get("proxy-groups", [])
    if not glados_groups:
        logger.error("❌ %s: 订阅中没有 proxy-groups", client)
        return False

    # 生成 profile 文件
    profile_content = generate_profile(client, data)
    profiles_dir = script_dir / cfg.get("profiles_dir", "profiles")
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profiles_dir / f"{client}.yaml"
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write(profile_content)

    # 写入日志
    log_dir = script_dir / cfg.get("log_dir", "logs")
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
        default=str(Path(__file__).parent / "conf" / "config.yaml"),
        help="配置文件路径（默认: conf/config.yaml）",
    )
    parser.add_argument(
        "-t", "--type",
        choices=SUPPORTED_CLIENTS,
        default=None,
        help="只同步指定客户端（mihomo / clash）",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)

    # 确定要同步的客户端列表
    clients = [args.type] if args.type else SUPPORTED_CLIENTS

    success = 0
    for client in clients:
        if sync_client(cfg, client):
            success += 1

    logger.info("同步完成: %d/%d 成功", success, len(clients))


if __name__ == "__main__":
    main()
