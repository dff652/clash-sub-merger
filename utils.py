#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils.py - Clash 订阅合并工具公共模块

提供配置加载、订阅下载、日志配置等共用功能。
"""

import logging
import sys
from pathlib import Path

import yaml
import requests


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

def setup_logger(name: str, log_dir: str = None) -> logging.Logger:
    """
    创建统一的 logger，同时输出到控制台和文件。

    Args:
        name: logger 名称
        log_dir: 日志目录路径，None 则不写文件
    """
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 控制台输出
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    # 文件输出
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path / "detail.log", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

def load_config(config_path: str, logger: logging.Logger = None) -> dict:
    """加载 YAML 配置文件"""
    if logger is None:
        logger = logging.getLogger(__name__)

    path = Path(config_path)
    if not path.exists():
        logger.error("配置文件不存在: %s", config_path)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    logger.info("已加载配置文件: %s", config_path)
    return cfg


# ---------------------------------------------------------------------------
# URL 脱敏
# ---------------------------------------------------------------------------

def mask_url(url: str, keep_prefix: int = 50) -> str:
    """
    对 URL 进行脱敏处理，隐藏 token 等敏感部分。
    保留前 keep_prefix 个字符 + '...'
    """
    if len(url) <= keep_prefix:
        return url
    return url[:keep_prefix] + "..."


# ---------------------------------------------------------------------------
# 订阅下载
# ---------------------------------------------------------------------------

def download_subscription(
    url: str,
    save_path: str,
    name: str = "订阅",
    min_proxies: int = 5,
    logger: logging.Logger = None,
) -> tuple:
    """
    下载订阅并保存到本地文件，带数据校验。

    流程：
      1. 从 URL 拉取 YAML
      2. 校验 proxies 数量 >= min_proxies
      3. 校验通过 → 保存到 save_path
      4. 校验失败 → 拒绝覆盖已有文件

    Args:
        url: 订阅链接
        save_path: 保存路径
        name: 订阅名称（用于日志）
        min_proxies: 最低节点数阈值
        logger: logger 实例

    Returns:
        (data, source) 元组
        - data: 解析后的 dict
        - source: "online" | "local" | "fail"
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    logger.info("正在下载 %s: %s", name, mask_url(url))

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = yaml.safe_load(resp.text)

        # 校验节点数量
        proxies = data.get("proxies", [])
        n_proxies = len(proxies)
        logger.info("成功获取 %s，共 %d 字节，%d 个节点", name, len(resp.content), n_proxies)

        if n_proxies < min_proxies:
            logger.warning(
                "⚠️  %s 节点数(%d)低于阈值(%d)，疑似异常数据，拒绝保存",
                name, n_proxies, min_proxies,
            )
            # 如果本地已有文件，回退使用
            save = Path(save_path)
            if save.exists():
                logger.info("回退使用已有文件: %s", save_path)
                with open(save, "r", encoding="utf-8") as f:
                    local_data = yaml.safe_load(f)
                return local_data, "local"
            else:
                logger.error("本地无已有文件，无法回退")
                return data, "fail"

        # 校验通过，保存文件
        save = Path(save_path)
        save.parent.mkdir(parents=True, exist_ok=True)
        with open(save, "w", encoding="utf-8") as f:
            f.write(resp.text)
        logger.info("✅ 已保存: %s", save_path)
        return data, "online"

    except requests.RequestException as e:
        logger.warning("获取 %s 失败: %s", name, e)
        save = Path(save_path)
        if save.exists():
            logger.info("⚠️  回退使用已有文件: %s", save_path)
            with open(save, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data, "local"
        else:
            logger.error("本地无已有文件，无法回退")
            return None, "fail"


def load_local_subscription(
    file_path: str,
    name: str = "订阅",
    logger: logging.Logger = None,
) -> dict:
    """
    从本地文件加载订阅数据。

    Args:
        file_path: 本地文件路径
        name: 订阅名称（用于日志）
        logger: logger 实例

    Returns:
        解析后的 dict，文件不存在则返回 None
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    path = Path(file_path)
    if not path.exists():
        logger.warning("%s 本地文件不存在: %s", name, file_path)
        return None

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    proxies = data.get("proxies", [])
    logger.info("已加载 %s: %s（%d 个节点）", name, file_path, len(proxies))
    return data
