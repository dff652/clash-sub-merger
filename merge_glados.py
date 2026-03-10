#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_glados.py - Clash 订阅合并脚本

功能：基于 GlaDOS 的订阅模版，将 GlaDOS、RackNerd+Vultr 等订阅合并，
     并最终生成可用于 Clash/OpenClash 的 YAML 配置文件。

使用方法：
    python merge_glados.py download              # 下载所有订阅
    python merge_glados.py download mihomo        # 只下载 mihomo
    python merge_glados.py merge                  # 合并（默认方案）
    python merge_glados.py merge -p vps           # 指定方案
    python merge_glados.py list                   # 列出所有方案
"""

import argparse
import copy
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import yaml
import requests

from utils import (
    setup_logger,
    load_config,
    download_subscription,
    load_local_subscription,
    mask_url,
)

# ---------------------------------------------------------------------------
# 日志 & YAML 保序支持
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
logger = setup_logger("merge_glados", str(SCRIPT_DIR / "logs"))


def _dict_representer(dumper, data):
    return dumper.represent_mapping(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, data.items())


def _dict_constructor(loader, node):
    return OrderedDict(loader.construct_pairs(node))


yaml.add_representer(OrderedDict, _dict_representer)
yaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _dict_constructor, Loader=yaml.SafeLoader)

# 引用语法的正则：匹配 {XX} 格式（排除 {PROVIDER}）
REF_PATTERN = re.compile(r"^\{(\w+)\}$")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def classify_proxies(proxies: list) -> dict:
    """
    按节点名称分类代理节点。
    返回 dict: { 分类名: [节点名称列表] }

    支持多种命名格式：
      旧格式: GLaDOS-R2-01 → R2,  GLaDOS-Netflix-01 → Netflix
      新格式: US-1 → US,  JP-2 → JP,  TW-IPv6-P1-1 → TW
              Fast-TW-B2-1 → TW,  Fast-Balancer-B1-1 → Balancer
    """
    patterns = [
        re.compile(r"^GLaDOS-([A-Za-z0-9]+)-\d+$"),
        re.compile(r"^Fast-([A-Za-z]+)-"),
        re.compile(r"^([A-Z]{2})(?:-|$)"),
    ]

    categories = OrderedDict()
    for proxy in proxies:
        name = proxy.get("name", "")
        cat = "Other"
        for pattern in patterns:
            match = pattern.match(name)
            if match:
                cat = match.group(1)
                break
        categories.setdefault(cat, []).append(name)

    for cat, names in categories.items():
        logger.info("  分类 %-10s: %d 个节点", cat, len(names))

    return categories


def expand_proxy_list(proxy_list: list, categories: dict) -> list:
    """
    展开 proxies 列表中的 {分类名} 引用。
    例如: ["{R2}", "DIRECT"]  →  ["GLaDOS-R2-01", ..., "DIRECT"]
    """
    expanded = []
    for item in proxy_list:
        if isinstance(item, str):
            m = REF_PATTERN.match(item)
            if m:
                ref_name = m.group(1)
                if ref_name == "PROVIDER":
                    # {PROVIDER} 是 proxy-providers 占位符，不在此处展开
                    expanded.append(item)
                    continue
                nodes = categories.get(ref_name, [])
                if not nodes:
                    logger.warning("引用 {%s} 未找到对应节点，已跳过", ref_name)
                expanded.extend(nodes)
            else:
                expanded.append(item)
        else:
            expanded.append(item)
    return expanded


# ---------------------------------------------------------------------------
# Profile 相关
# ---------------------------------------------------------------------------

def get_profiles_dir(cfg: dict) -> Path:
    """获取 profiles 目录路径"""
    return SCRIPT_DIR / cfg.get("profiles_dir", "profiles")


def list_available_profiles(cfg: dict) -> list:
    """扫描 profiles 目录，返回可用方案名列表"""
    profiles_dir = get_profiles_dir(cfg)
    if not profiles_dir.exists():
        return []
    return sorted(p.stem for p in profiles_dir.glob("*.yaml"))


def load_profile(cfg: dict, profile: str) -> list:
    """从 profiles/ 目录加载指定方案文件，返回 proxy_groups 列表"""
    profiles_dir = get_profiles_dir(cfg)
    profile_file = profiles_dir / f"{profile}.yaml"

    if not profile_file.exists():
        available = list_available_profiles(cfg)
        logger.error("方案文件不存在: %s", profile_file)
        if available:
            logger.error("可用方案: %s", ", ".join(available))
        sys.exit(1)

    with open(profile_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    group_defs = data.get("proxy_groups", [])
    logger.info("已加载方案: %s（%d 个分组）", profile, len(group_defs))
    return group_defs


def build_proxy_groups(cfg: dict, categories: dict, profile: str = None) -> list:
    """
    从 profiles/ 目录加载分组方案，展开其中的 {分类名} 引用。
    同时将 use 列表中的 {PROVIDER} 占位符替换为 config 中的实际 provider 名称。
    """
    provider_name = cfg.get("sub_store_provider_name", "sub_allin1")
    if not profile:
        profile = cfg.get("default_profile", "default")

    available = list_available_profiles(cfg)
    if available:
        logger.info("可用方案: %s", ", ".join(available))

    group_defs = load_profile(cfg, profile)
    if not group_defs:
        logger.error("方案 %s 中没有 proxy_groups 定义", profile)
        sys.exit(1)

    groups = []
    skipped = []
    
    # 动态分析：找到代理节点数最多的 select 组，认为它是主代理组（排除掉专用于包含 provider 的极简组）
    main_group_name = None
    max_proxies = -1
    for gdef in group_defs:
        if gdef.get("type", "") == "select" and "proxies" in gdef:
            # 排除掉自己创建的或节点数极少的组，比如 VPS
            if gdef.get("name") == "VPS":
                continue
            num_proxies = len(gdef.get("proxies", []))
            if num_proxies > max_proxies:
                max_proxies = num_proxies
                main_group_name = gdef.get("name")
    
    if main_group_name:
        logger.info("⚡ 动态识别到主代理组: [%s] (包含 %d 个基础目标)", main_group_name, max_proxies)

    for gdef in group_defs:
        group = OrderedDict()
        for key, val in gdef.items():
            if key == "proxies" and isinstance(val, list):
                expanded = expand_proxy_list(val, categories)
                # 如果这个是主代理组，我们动态把 VPS 加进去（避免原文件被污染）
                if gdef.get("name") == main_group_name:
                    if "VPS" not in expanded:
                        expanded.append("VPS")
                group[key] = expanded
            elif key == "use" and isinstance(val, list):
                group[key] = [provider_name if v == "{PROVIDER}" else v for v in val]
            else:
                group[key] = val

        has_proxies = bool(group.get("proxies"))
        has_use = bool(group.get("use"))
        if not has_proxies and not has_use:
            skipped.append(group.get("name", "?"))
            continue
        groups.append(group)

    if skipped:
        logger.warning("⚠️  以下分组因无可用节点被跳过: %s", ", ".join(skipped))

    return groups, main_group_name


def build_proxy_providers(cfg: dict) -> OrderedDict:
    """构建 proxy-providers 配置"""
    providers_cfg = cfg.get("proxy_providers", {})
    if providers_cfg:
        providers = OrderedDict()
        for name, pdef in providers_cfg.items():
            providers[name] = OrderedDict(pdef.items()) if isinstance(pdef, dict) else pdef
        return providers

    provider_name = cfg.get("sub_store_provider_name", "sub_allin1")
    sub_store_url = cfg.get("sub_store_url", "")
    if not sub_store_url:
        logger.warning("未配置 sub_store_url，跳过 proxy-providers")
        return OrderedDict()

    interval = cfg.get("provider_interval", 3600)
    hc_interval = cfg.get("provider_health_check_interval", 600)
    hc_url = cfg.get("provider_health_check_url", "http://www.gstatic.cn/generate_204")

    providers = OrderedDict()
    providers[provider_name] = OrderedDict([
        ("type", "http"),
        ("url", sub_store_url),
        ("interval", interval),
        ("path", f"./providers/{provider_name}.yaml"),
        ("health-check", OrderedDict([
            ("enable", True),
            ("interval", hc_interval),
            ("url", hc_url),
        ])),
    ])
    return providers


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def load_rules(cfg: dict, profile: str) -> list:
    """
    加载规则文件。优先查找 rules/<profile>.yaml，不存在则回退到 conf/rules_template.yaml。
    """
    # 优先: rules/<profile>.yaml
    rules_file = SCRIPT_DIR / "rules" / f"{profile}.yaml"
    if rules_file.exists():
        with open(rules_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        rules = data.get("rules", [])
        logger.info("已加载方案规则: %s（共 %d 条规则）", rules_file, len(rules))
        return rules

    # 回退: conf/rules_template.yaml
    rules_file = SCRIPT_DIR / cfg.get("rules_template_file", "conf/rules_template.yaml")
    if not rules_file.exists():
        logger.error("规则模版文件不存在: %s", rules_file)
        sys.exit(1)
    with open(rules_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rules = data.get("rules", [])
    logger.info("已加载规则模版: %s（共 %d 条规则）", rules_file, len(rules))
    return rules


def fixup_rules(result: dict, main_proxy_group_name: str = None) -> list:
    """
    自动修复 rules 中引用的缺失组名。
    优先将找不到目标的规则替换为动态识别的 main_proxy_group_name。
    如果没能识别到，则降级为第一个 select 类型的组。
    """
    builtin = {"DIRECT", "REJECT"}
    group_names = {g["name"] for g in result.get("proxy-groups", [])}
    proxy_names = {p["name"] for p in result.get("proxies", [])}
    valid_targets = builtin | group_names | proxy_names

    fallback_target = main_proxy_group_name if main_proxy_group_name in group_names else "DIRECT"
    
    if fallback_target == "DIRECT":
        for g in result.get("proxy-groups", []):
            if g.get("type") == "select" and (g.get("proxies") or g.get("use")) and g.get("name") != "VPS":
                fallback_target = g["name"]
                break

    rule_params = {"no-resolve"}
    rules = result.get("rules", [])
    fixed_rules = []
    replaced = {}

    for rule in rules:
        parts = rule.split(",")
        if len(parts) >= 3 and parts[-1].strip() in rule_params:
            target_idx = -2
        elif len(parts) >= 2:
            target_idx = -1
        else:
            fixed_rules.append(rule)
            continue

        target = parts[target_idx].strip()
        if target not in valid_targets:
            old_target = target
            parts[target_idx] = fallback_target
            rule = ",".join(parts)
            replaced[old_target] = replaced.get(old_target, 0) + 1

        fixed_rules.append(rule)

    if replaced:
        total = sum(replaced.values())
        ratio = total / len(rules) * 100 if rules else 0

        # 回退比例超过 30% 时发出强烈警告
        if ratio > 30:
            logger.warning(
                "⚠️  规则回退比例过高: %d/%d (%.0f%%) → 建议为方案 %s 创建配套规则文件",
                total, len(rules), ratio,
                "当前方案",
            )
        else:
            logger.info("⚡ 自动回退: %d 条规则的目标替换为 %s", total, fallback_target)

        for name, count in sorted(replaced.items()):
            logger.info("   %s → %s (%d 条)", name, fallback_target, count)

    return fixed_rules


# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------

def build_base_config(glados_data: dict = None) -> OrderedDict:
    """构建基础配置。优先从 GlaDOS 订阅提取，无则使用内置默认值。"""
    defaults = OrderedDict([
        ("port", 7890),
        ("socks-port", 7891),
        ("allow-lan", False),
        ("mode", "rule"),
        ("log-level", "info"),
        ("external-controller", "127.0.0.1:9090"),
        ("secret", ""),
        ("dns", OrderedDict([
            ("enable", True),
            ("ipv6", True),
            ("fake-ip-range", "198.18.0.1/16"),
            ("listen", "0.0.0.0:23453"),
            ("default-nameserver", ["119.29.29.29", "114.114.114.114", "223.5.5.5"]),
            ("nameserver", [
                "https://dns.alidns.com/dns-query",
                "https://doh.pub/dns-query",
            ]),
            ("fake-ip-filter", ["*.lan", "*.local"]),
        ])),
    ])

    if glados_data:
        for key in defaults:
            if key in glados_data:
                defaults[key] = glados_data[key]

    return defaults


# ---------------------------------------------------------------------------
# 检测 profile 是否需要 GlaDOS
# ---------------------------------------------------------------------------

def profile_needs_glados(cfg: dict, profile: str = None) -> bool:
    """检测 profile 是否需要 GlaDOS 节点"""
    if not profile:
        profile = cfg.get("default_profile", "default")

    profiles_dir = get_profiles_dir(cfg)
    profile_file = profiles_dir / f"{profile}.yaml"
    if not profile_file.exists():
        return True

    with open(profile_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data.get("needs_glados", False):
        return True

    for gdef in data.get("proxy_groups", []):
        proxies = gdef.get("proxies", [])
        for item in proxies:
            if isinstance(item, str) and REF_PATTERN.match(item):
                ref = REF_PATTERN.match(item).group(1)
                if ref != "PROVIDER":
                    return True
    return False


# ---------------------------------------------------------------------------
# 下载命令
# ---------------------------------------------------------------------------

def get_download_dir(cfg: dict) -> Path:
    """获取下载目录路径"""
    return SCRIPT_DIR / cfg.get("download_dir", "download")


def cmd_download(cfg: dict, client: str = None) -> None:
    """执行下载命令：拉取订阅并保存到 download/ 目录"""
    glados_urls = cfg.get("glados_urls", {})
    download_dir = get_download_dir(cfg)
    min_proxies = cfg.get("min_proxy_count", 5)

    # 确定要下载的客户端列表
    if client:
        clients = [client]
    else:
        clients = list(glados_urls.keys())

    if not clients:
        logger.warning("未配置任何订阅链接（glados_urls 为空）")
        return

    success = 0
    for c in clients:
        url = glados_urls.get(c, "")
        if not url:
            logger.warning("未配置 %s 的订阅链接，跳过", c)
            continue

        save_path = str(download_dir / f"glados_{c}.yaml")
        data, source = download_subscription(
            url=url,
            save_path=save_path,
            name=f"GlaDOS {c}",
            min_proxies=min_proxies,
            logger=logger,
        )

        if source == "online":
            success += 1
        elif source == "local":
            logger.warning("  %s: 使用已有本地文件（新数据未通过校验）", c)
        else:
            logger.error("  %s: 下载失败", c)

    logger.info("下载完成: %d/%d 成功", success, len(clients))


# ---------------------------------------------------------------------------
# 合并命令
# ---------------------------------------------------------------------------

def merge_and_output(cfg: dict, profile: str = None) -> None:
    """主合并逻辑"""
    if not profile:
        profile = cfg.get("default_profile", "mihomo")

    # 1. 检测是否需要 GlaDOS 订阅
    needs_glados = profile_needs_glados(cfg, profile)
    glados_data = None
    proxies = []
    glados_status = "skip"

    if needs_glados:
        profiles_dir = get_profiles_dir(cfg)
        profile_file = profiles_dir / f"{profile}.yaml"
        glados_client = profile
        if profile_file.exists():
            with open(profile_file, "r", encoding="utf-8") as f:
                pdata = yaml.safe_load(f)
            glados_client = pdata.get("glados_client", profile)

        # 优先从 download/ 目录读取本地文件
        download_dir = get_download_dir(cfg)
        local_file = download_dir / f"glados_{glados_client}.yaml"

        if local_file.exists():
            glados_data = load_local_subscription(
                str(local_file),
                name=f"GlaDOS {glados_client}",
                logger=logger,
            )
            glados_status = "local"
        else:
            # 本地文件不存在，自动触发下载
            logger.info("本地文件不存在，自动下载 %s 订阅...", glados_client)
            glados_urls = cfg.get("glados_urls", {})
            glados_url = glados_urls.get(glados_client, cfg.get("glados_url", ""))

            if glados_url:
                save_path = str(local_file)
                min_proxies = cfg.get("min_proxy_count", 5)
                glados_data, source = download_subscription(
                    url=glados_url,
                    save_path=save_path,
                    name=f"GlaDOS {glados_client}",
                    min_proxies=min_proxies,
                    logger=logger,
                )
                glados_status = source  # "online" | "local" | "fail"
            else:
                glados_status = "no-url"
                logger.warning("未配置 %s 的订阅链接", glados_client)

        if glados_data is None:
            logger.error("无法获取 GlaDOS %s 数据，无法继续", glados_client)
            sys.exit(1)

        proxies = glados_data.get("proxies", [])
        logger.info("GlaDOS %s 共 %d 个节点", glados_client, len(proxies))
    else:
        logger.info("📦 当前方案无需 GlaDOS 节点，跳过订阅获取")

    # 2. 构建基础配置
    result = build_base_config(glados_data)

    # 3. 构建 proxy-providers
    providers = build_proxy_providers(cfg)
    provider_status = "ok" if providers else "none"
    if providers:
        result["proxy-providers"] = providers
        logger.info("已构建 proxy-providers: %s", list(providers.keys()))

    # 4. 加入 proxies
    if proxies:
        result["proxies"] = proxies

    # 5. 分类节点 & 构建 proxy-groups
    categories = classify_proxies(proxies) if proxies else {}
    groups, main_group_name = build_proxy_groups(cfg, categories, profile=profile)
    result["proxy-groups"] = groups
    logger.info("已构建 %d 个代理组", len(result["proxy-groups"]))

    # 6. 加载 rules（优先方案配套规则）
    result["rules"] = load_rules(cfg, profile)

    # 7. 自动修复 rules 中引用的缺失组名，并将其桥接到检测出的主分组
    result["rules"] = fixup_rules(result, main_group_name)

    # 8. 输出 YAML
    now = datetime.now()

    output_dir = SCRIPT_DIR / cfg.get("output_dir", "output")
    log_dir = SCRIPT_DIR / cfg.get("log_dir", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    yaml_header = (
        f"# Clash Config - profile: {profile}\n"
        f"# Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# By merge_glados.py\n\n"
    )
    yaml_content = yaml.dump(
        dict(result),
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )

    output_path = output_dir / f"{profile}.yaml"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(yaml_header + yaml_content)
    file_size_kb = output_path.stat().st_size / 1024

    # 追加生成日志
    log_path = log_dir / "generate.log"
    n_proxies = len(proxies)
    n_groups = len(result["proxy-groups"])
    n_rules = len(result["rules"])
    log_line = (
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} | MERGE | {profile:10s} "
        f"| {n_proxies:3d} nodes | {n_groups:2d} groups | {n_rules:4d} rules "
        f"| glados: {glados_status:5s} | provider: {provider_status:4s} "
        f"| {file_size_kb:.0f}KB\n"
    )
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(log_line)

    logger.info("✅ 合并完成！")
    logger.info("   📄 输出: %s (%.0fKB)", output_path, file_size_kb)
    logger.info("   📋 日志: %s", log_path)
    logger.info("   - proxies: %d 个节点", n_proxies)
    logger.info("   - proxy-groups: %d 个分组", n_groups)
    logger.info("   - rules: %d 条规则", n_rules)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Clash 订阅合并脚本 - 合并 GlaDOS + Sub-Store 订阅"
    )
    parser.add_argument(
        "-c", "--config",
        default=str(SCRIPT_DIR / "conf" / "config.yaml"),
        help="配置文件路径（默认: conf/config.yaml）",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # download 子命令
    dl_parser = subparsers.add_parser("download", help="下载订阅到本地")
    dl_parser.add_argument(
        "client",
        nargs="?",
        default=None,
        help="指定客户端（如 mihomo），不填则下载所有",
    )

    # merge 子命令
    merge_parser = subparsers.add_parser("merge", help="合并生成配置文件")
    merge_parser.add_argument(
        "-p", "--profile",
        default=None,
        help="选择代理组方案（对应 profiles/ 目录下的文件名）",
    )

    # list 子命令
    subparsers.add_parser("list", help="列出所有可用方案")

    args = parser.parse_args()

    cfg = load_config(args.config, logger=logger)

    if args.command == "download":
        cmd_download(cfg, client=args.client)

    elif args.command == "list":
        available = list_available_profiles(cfg)
        default_profile = cfg.get("default_profile", "mihomo")
        if available:
            profiles_dir = get_profiles_dir(cfg)
            print(f"可用的代理组方案（{profiles_dir}/）:")
            for name in available:
                marker = " (默认)" if name == default_profile else ""
                with open(profiles_dir / f"{name}.yaml", encoding="utf-8") as f:
                    profile_data = yaml.safe_load(f)
                count = len(profile_data.get("proxy_groups", []))
                print(f"  - {name}: {count} 个分组{marker}")
        else:
            print("profiles/ 目录为空或不存在")

    elif args.command == "merge":
        merge_and_output(cfg, profile=args.profile)

    else:
        # 无子命令时默认执行 merge（向后兼容）
        # 检查旧版参数
        parser.add_argument("-p", "--profile", default=None)
        parser.add_argument("--list-profiles", action="store_true")
        args = parser.parse_args()

        if args.list_profiles:
            available = list_available_profiles(cfg)
            default_profile = cfg.get("default_profile", "mihomo")
            if available:
                profiles_dir = get_profiles_dir(cfg)
                print(f"可用的代理组方案（{profiles_dir}/）:")
                for name in available:
                    marker = " (默认)" if name == default_profile else ""
                    with open(profiles_dir / f"{name}.yaml", encoding="utf-8") as f:
                        profile_data = yaml.safe_load(f)
                    count = len(profile_data.get("proxy_groups", []))
                    print(f"  - {name}: {count} 个分组{marker}")
            else:
                print("profiles/ 目录为空或不存在")
        else:
            merge_and_output(cfg, profile=args.profile)


if __name__ == "__main__":
    main()