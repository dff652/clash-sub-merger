#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_glados.py - Clash 订阅合并脚本

功能：基于 GlaDOS 的订阅模版，将 GlaDOS、RackNerd+Vultr 等订阅合并，
     并最终生成可用于 Clash/OpenClash 的 YAML 配置文件。

使用方法：
    python merge_glados.py                    # 使用默认 conf/config.yaml
    python merge_glados.py -c conf/custom.yaml # 使用自定义配置文件
"""

import argparse
import copy
import logging
import re
import sys
from pathlib import Path
from collections import OrderedDict

import yaml
import requests

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
_log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# 控制台输出
_console = logging.StreamHandler()
_console.setFormatter(_log_fmt)

# 文件输出（logs/detail.log）
_log_dir = Path(__file__).parent / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(_log_dir / "detail.log", encoding="utf-8")
_file_handler.setFormatter(_log_fmt)

logger = logging.getLogger("merge_glados")
logger.setLevel(logging.INFO)
logger.addHandler(_console)
logger.addHandler(_file_handler)

# ---------------------------------------------------------------------------
# YAML 保序支持
# ---------------------------------------------------------------------------

def _dict_representer(dumper, data):
    return dumper.represent_mapping(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, data.items())

def _dict_constructor(loader, node):
    return OrderedDict(loader.construct_pairs(node))

yaml.add_representer(OrderedDict, _dict_representer)
yaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _dict_constructor, Loader=yaml.SafeLoader)

# 引用语法的正则：匹配 {XX} 格式
REF_PATTERN = re.compile(r"^\{(\w+)\}$")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

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


def fetch_subscription(url: str, name: str = "订阅", cache_file: str = None) -> dict:
    """
    从远程 URL 获取 YAML 订阅内容。
    获取成功后自动保存到 cache_file；失败时回退使用缓存。
    """
    logger.info("正在获取 %s: %s", name, url)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = yaml.safe_load(resp.text)
        logger.info("成功获取 %s，共 %d 字节", name, len(resp.content))
        # 保存缓存
        if cache_file:
            Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(resp.text)
            logger.info("已保存缓存: %s", cache_file)
        return data
    except requests.RequestException as e:
        logger.warning("获取 %s 失败: %s", name, e)
        if cache_file and Path(cache_file).exists():
            logger.info("⚠️  回退使用本地缓存: %s", cache_file)
            with open(cache_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data
        else:
            logger.error("无本地缓存可用，无法继续")
            sys.exit(1)


def classify_proxies(proxies: list) -> dict:
    """
    按节点名称分类代理节点。
    返回 dict: { 分类名: [节点名称列表] }

    支持多种命名格式：
      旧格式: GLaDOS-R2-01 → R2,  GLaDOS-Netflix-01 → Netflix
      新格式: US-1 → US,  JP-2 → JP,  TW-IPv6-P1-1 → TW
              Fast-TW-B2-1 → TW,  Fast-Balancer-B1-1 → Balancer
    """
    # 匹配规则（按优先级排列）
    patterns = [
        # 旧格式: GLaDOS-<Category>-<Number>
        re.compile(r"^GLaDOS-([A-Za-z0-9]+)-\d+$"),
        # 新格式 Fast- 开头: Fast-<Region>-<Suffix>
        re.compile(r"^Fast-([A-Za-z]+)-"),
        # 新格式 区域代码开头: <REGION>-xxx
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

    例如:
      ["{R2}", "DIRECT"]  →  ["GLaDOS-R2-01", "GLaDOS-R2-02", ..., "DIRECT"]
    """
    expanded = []
    for item in proxy_list:
        if isinstance(item, str):
            m = REF_PATTERN.match(item)
            if m:
                ref_name = m.group(1)
                nodes = categories.get(ref_name, [])
                if not nodes:
                    logger.warning("引用 {%s} 未找到对应节点，已跳过", ref_name)
                expanded.extend(nodes)
            else:
                expanded.append(item)
        else:
            expanded.append(item)
    return expanded


def get_profiles_dir(cfg: dict) -> Path:
    """获取 profiles 目录路径"""
    script_dir = Path(__file__).parent
    return script_dir / cfg.get("profiles_dir", "profiles")


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
    """
    # 确定使用哪个方案
    if not profile:
        profile = cfg.get("default_profile", "default")

    # 列出可用方案
    available = list_available_profiles(cfg)
    if available:
        logger.info("可用方案: %s", ", ".join(available))

    # 加载方案
    group_defs = load_profile(cfg, profile)

    if not group_defs:
        logger.error("方案 %s 中没有 proxy_groups 定义", profile)
        sys.exit(1)

    groups = []
    skipped = []
    for gdef in group_defs:
        group = OrderedDict()
        for key, val in gdef.items():
            if key == "proxies" and isinstance(val, list):
                group[key] = expand_proxy_list(val, categories)
            else:
                group[key] = val

        # 空组保护：如果没有 proxies 也没有 use，跳过该组
        has_proxies = bool(group.get("proxies"))
        has_use = bool(group.get("use"))
        if not has_proxies and not has_use:
            skipped.append(group.get("name", "?"))
            continue
        groups.append(group)

    if skipped:
        logger.warning("⚠️  以下分组因无可用节点被跳过: %s", ", ".join(skipped))

    return groups


def build_proxy_providers(cfg: dict) -> OrderedDict:
    """构建 proxy-providers 配置"""
    providers_cfg = cfg.get("proxy_providers", {})
    if providers_cfg:
        # 直接使用配置文件中定义的 providers
        providers = OrderedDict()
        for name, pdef in providers_cfg.items():
            providers[name] = OrderedDict(pdef.items()) if isinstance(pdef, dict) else pdef
        return providers

    # 兼容旧格式
    provider_name = cfg.get("sub_store_provider_name", "sub3in1")
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


def load_rules_template(rules_file: str) -> list:
    """加载 rules 模版文件"""
    path = Path(rules_file)
    if not path.exists():
        logger.error("规则模版文件不存在: %s", rules_file)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rules = data.get("rules", [])
    logger.info("已加载规则模版: %s（共 %d 条规则）", rules_file, len(rules))
    return rules


def fixup_rules(result: dict) -> list:
    """
    自动修复 rules 中引用的缺失组名。
    如果 rules 引用的代理组/节点名在当前配置中不存在，
    自动替换为第一个 select 类型的组（通常是 Proxy）。
    """
    # 收集所有有效的目标名
    builtin = {"DIRECT", "REJECT"}
    group_names = {g["name"] for g in result.get("proxy-groups", [])}
    proxy_names = {p["name"] for p in result.get("proxies", [])}
    valid_targets = builtin | group_names | proxy_names

    # 找到第一个 select 类型的组作为回退目标（支持 proxies 和 use 两种方式）
    fallback_target = "DIRECT"
    for g in result.get("proxy-groups", []):
        if g.get("type") == "select" and (g.get("proxies") or g.get("use")):
            fallback_target = g["name"]
            break

    # 需要跳过的规则参数（不是代理组名）
    rule_params = {"no-resolve"}

    rules = result.get("rules", [])
    fixed_rules = []
    replaced = {}  # 被替换的组名 → 次数

    for rule in rules:
        parts = rule.split(",")

        if len(parts) >= 3 and parts[-1].strip() in rule_params:
            # 含参数（如 "IP-CIDR,1.1.1.1/32,Proxy,no-resolve"），target 在倒数第二段
            target_idx = -2
        elif len(parts) >= 2:
            # 普通规则（如 "MATCH,Proxy" 或 "DOMAIN,xxx,Proxy"），target 在最后
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
        logger.info("⚡ 自动回退: %d 条规则的目标替换为 %s", total, fallback_target)
        for name, count in sorted(replaced.items()):
            logger.info("   %s → %s (%d 条)", name, fallback_target, count)

    return fixed_rules


def build_base_config(glados_data: dict = None) -> OrderedDict:
    """构建基础配置。优先从 GlaDOS 订阅提取，无则使用内置默认值。"""
    # 内置默认基础配置
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
        # 用 GlaDOS 订阅中的值覆盖默认值
        for key in defaults:
            if key in glados_data:
                defaults[key] = glados_data[key]

    return defaults


def profile_needs_glados(cfg: dict, profile: str = None) -> bool:
    """检测 profile 是否需要 GlaDOS 节点（通过 {分类名} 引用或 needs_glados 标志）。"""
    if not profile:
        profile = cfg.get("default_profile", "default")

    profiles_dir = get_profiles_dir(cfg)
    profile_file = profiles_dir / f"{profile}.yaml"
    if not profile_file.exists():
        return True

    with open(profile_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # 方式1: profile 文件中显式声明 needs_glados: true
    if data.get("needs_glados", False):
        return True

    # 方式2: 检测是否引用了 {分类名}
    for gdef in data.get("proxy_groups", []):
        proxies = gdef.get("proxies", [])
        for item in proxies:
            if isinstance(item, str) and REF_PATTERN.match(item):
                return True
    return False


def merge_and_output(cfg: dict, profile: str = None) -> None:
    """主合并逻辑"""
    script_dir = Path(__file__).parent

    # 确定实际使用的方案名
    if not profile:
        profile = cfg.get("default_profile", "mihomo")

    # 1. 检测是否需要 GlaDOS 订阅
    needs_glados = profile_needs_glados(cfg, profile)
    glados_data = None
    proxies = []
    glados_status = "skip"

    if needs_glados:
        # 从 profile 文件读取 glados_client 字段确定客户端类型
        profiles_dir = get_profiles_dir(cfg)
        profile_file = profiles_dir / f"{profile}.yaml"
        glados_client = profile  # 默认用 profile 名作为客户端名
        if profile_file.exists():
            with open(profile_file, "r", encoding="utf-8") as f:
                pdata = yaml.safe_load(f)
            glados_client = pdata.get("glados_client", profile)

        # 从 glados_urls 中获取 URL（兼容旧格式 glados_url）
        glados_urls = cfg.get("glados_urls", {})
        glados_url = glados_urls.get(glados_client, cfg.get("glados_url", ""))

        if glados_url:
            cache_dir = script_dir / cfg.get("glados_cache_dir", "cache")
            cache_file = str(cache_dir / f"glados_{glados_client}.yaml")
            try:
                resp = requests.get(glados_url, timeout=30)
                resp.raise_for_status()
                glados_data = yaml.safe_load(resp.text)
                glados_status = "ok"
                Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(resp.text)
                logger.info("成功获取 GlaDOS %s 订阅", glados_client)
            except requests.RequestException as e:
                logger.warning("获取 GlaDOS %s 订阅失败: %s", glados_client, e)
                if Path(cache_file).exists():
                    glados_status = "cache"
                    with open(cache_file, "r", encoding="utf-8") as f:
                        glados_data = yaml.safe_load(f)
                    logger.info("⚠️  回退使用本地缓存: %s", cache_file)
                else:
                    glados_status = "fail"
                    logger.error("无本地缓存可用，无法继续")
                    sys.exit(1)
            proxies = glados_data.get("proxies", [])
            logger.info("GlaDOS %s 订阅共 %d 个节点", glados_client, len(proxies))
        else:
            glados_status = "no-url"
            logger.warning("未配置 %s 的订阅链接，跳过 GlaDOS 节点", glados_client)
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

    # 4. 加入 proxies（可能为空）
    if proxies:
        result["proxies"] = proxies

    # 5. 分类节点 & 构建 proxy-groups
    categories = classify_proxies(proxies) if proxies else {}
    result["proxy-groups"] = build_proxy_groups(cfg, categories, profile=profile)
    logger.info("已构建 %d 个代理组", len(result["proxy-groups"]))

    # 6. 加载 rules
    rules_file = script_dir / cfg.get("rules_template_file", "rules_template.yaml")
    result["rules"] = load_rules_template(str(rules_file))

    # 7. 自动修复 rules 中引用的缺失组名
    n_rules_before = len(result["rules"])
    result["rules"] = fixup_rules(result)
    # 计算回退数（fixup_rules 中已打印详细日志）

    # 8. 输出 YAML（固定名 + 生成日志）
    from datetime import datetime
    now = datetime.now()

    output_dir = script_dir / cfg.get("output_dir", "output")
    log_dir = script_dir / cfg.get("log_dir", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 生成 YAML 内容
    yaml_header = f"# Clash Config - profile: {profile}\n# Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}\n# By merge_glados.py\n\n"
    yaml_content = yaml.dump(
        dict(result),
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )

    # 写入固定名文件（方便 Clash 导入）
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
        default=str(Path(__file__).parent / "conf" / "config.yaml"),
        help="配置文件路径（默认: conf/config.yaml）",
    )
    parser.add_argument(
        "-p", "--profile",
        default=None,
        help="选择代理组方案（对应 profiles/ 目录下的文件名，如 -p vps）",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="列出所有可用的代理组方案",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)

    # 列出可用方案
    if args.list_profiles:
        available = list_available_profiles(cfg)
        default_profile = cfg.get("default_profile", "mihomo")
        if available:
            profiles_dir = get_profiles_dir(cfg)
            print(f"可用的代理组方案（{profiles_dir}/）:")
            for name in available:
                marker = " (默认)" if name == default_profile else ""
                # 读取方案获取分组数
                profile_data = yaml.safe_load(open(profiles_dir / f"{name}.yaml", encoding="utf-8"))
                count = len(profile_data.get("proxy_groups", []))
                print(f"  - {name}: {count} 个分组{marker}")
        else:
            print("profiles/ 目录为空或不存在")
        return

    merge_and_output(cfg, profile=args.profile)


if __name__ == "__main__":
    main()