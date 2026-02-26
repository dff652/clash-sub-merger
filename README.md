# Clash 订阅合并工具

自动合并多个订阅源（GlaDOS、Sub-Store 等），生成 Clash/OpenClash YAML 配置文件。支持多客户端（Mihomo/Clash）和多套代理组方案。

## 文件结构

```
clash-sub-merger/
├── run.sh                    # 交互菜单 & 命令行入口
├── merge_glados.py           # 合并脚本
├── sync_profiles.py          # 同步脚本（从 GlaDOS 更新 profiles）
├── conf/                     # 配置目录
│   ├── config.example.yaml   #   配置模版（提交 Git）
│   ├── config.yaml           #   私有配置（.gitignore 排除）
│   └── rules_template.yaml   #   分流规则（1200+ 条）
├── profiles/                 # 代理组方案
│   ├── mihomo.yaml           #   Mihomo 客户端（sync 自动生成）
│   ├── clash.yaml            #   Clash Standard（sync 自动生成）
│   ├── custom.yaml           #   自定义方案（手动维护）
│   └── vps.yaml              #   极简方案（仅 VPS）
├── output/                   # 生成结果（.gitignore 排除）
│   ├── mihomo.yaml
│   ├── clash.yaml
│   └── vps.yaml
├── logs/                     # 日志目录（.gitignore 排除）
│   └── generate.log
├── cache/                    # 订阅缓存（.gitignore 排除）
└── .gitignore
```

## 快速开始

```bash
# 1. 安装依赖
pip install pyyaml requests

# 2. 创建配置
cp conf/config.example.yaml conf/config.yaml
# 编辑 conf/config.yaml，填入 GlaDOS 订阅链接

# 3. 使用交互菜单
./run.sh
```

## 使用方式

### 交互菜单

```bash
./run.sh
```

### 命令行模式

```bash
./run.sh sync                  # 同步所有客户端 profiles
./run.sh sync mihomo           # 只同步 mihomo
./run.sh merge mihomo          # 合并生成 mihomo 配置
./run.sh merge clash           # 合并生成 clash 配置
./run.sh merge vps             # 合并生成 VPS 配置
./run.sh list                  # 查看所有方案
./run.sh log                   # 查看生成日志
```

### 直接调用 Python

```bash
python sync_profiles.py                    # 同步所有客户端
python sync_profiles.py -t mihomo          # 只同步 mihomo
python merge_glados.py                     # 默认 mihomo 方案
python merge_glados.py -p clash            # Clash 方案
python merge_glados.py --list-profiles     # 列出方案
```

## 代理组方案

| 方案 | 说明 | 维护方式 |
|------|------|----------|
| `mihomo` | Mihomo/Clash Meta | `sync_profiles.py` 自动同步 |
| `clash` | Clash Standard | `sync_profiles.py` 自动同步 |
| `custom` | 自定义分组（`{分类名}` 引用） | 手动编辑 |
| `vps` | 极简（仅 VPS，无需 GlaDOS） | 无需维护 |

### 日常维护

```bash
# GlaDOS 更新链接后：
# 1. 编辑 conf/config.yaml 更新 glados_urls
# 2. 一键同步 + 生成
./run.sh sync
./run.sh merge mihomo
```

## 生成日志

`logs/generate.log` 统一记录同步和合并操作：

```
2026-02-26 13:27:07 | SYNC  | mihomo     | ok   | 11 groups | from: online
2026-02-26 13:27:08 | SYNC  | clash      | ok   | 11 groups | from: online
2026-02-26 13:27:09 | MERGE | mihomo     |  36 nodes | 12 groups | 1201 rules | glados: ok    | 53KB
2026-02-26 13:27:10 | MERGE | vps        |   0 nodes |  1 groups | 1201 rules | glados: skip  | 41KB
```

## 注意事项

- `conf/config.yaml` 包含敏感链接，已被 `.gitignore` 排除
- `mihomo.yaml` 和 `clash.yaml` 由 `sync_profiles.py` 自动生成，不要手动编辑
- GlaDOS 链接变化时需重新同步：`./run.sh sync`
