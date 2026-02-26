# Clash 订阅合并工具

自动合并多个订阅源（GlaDOS、Sub-Store 等），生成 Clash/OpenClash YAML 配置文件。支持多套代理组方案，GlaDOS 与 VPS 可独立使用。

## 功能

- 🔄 **多订阅合并** — GlaDOS + Sub-Store (RackNerd/Vultr)，按需加载
- 🎛️ **多方案切换** — `profiles/` 目录下每个文件即一套分组方案，命令行切换
- 🏷️ **智能分组** — 按节点名自动分类，`{分类名}` 语法引用
- ⚡ **自动回退** — 精简方案中缺失的规则目标自动替换为可用代理组
- 💾 **缓存机制** — GlaDOS 订阅获取失败自动回退本地缓存
- 🔒 **安全提交** — 敏感信息通过 `.gitignore` 排除

## 文件结构

```
clash_yaml/
├── merge_glados.py           # 核心脚本
├── config.example.yaml       # 配置模版（提交 Git）
├── config.yaml               # 私有配置（.gitignore 排除）
├── rules_template.yaml       # 分流规则（1200+ 条）
├── profiles/                 # 代理组方案
│   ├── default.yaml          #   完整方案（GlaDOS + VPS，12 个分组）
│   └── vps.yaml              #   极简方案（仅 VPS，1 个分组）
├── output/                   # 生成结果（.gitignore 排除）
│   └── update_glados_config.yaml
├── cache/                    # 订阅缓存（.gitignore 排除）
├── .gitignore
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install pyyaml requests
```

### 2. 创建配置

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入你的订阅链接
```

### 3. 运行

```bash
python merge_glados.py                    # 使用默认方案
python merge_glados.py -p vps             # 使用 VPS 方案
python merge_glados.py --list-profiles    # 查看所有方案
```

输出文件在 `output/update_glados_config.yaml`。

## 代理组方案

方案文件存放在 `profiles/` 目录，每个 `.yaml` 文件对应一套方案。

### default 方案（完整，12 个分组）

需要 GlaDOS 订阅，包含自动测速、故障转移、按用途分流等分组。

| 代理组 | 类型 | 节点来源 |
|--------|------|----------|
| RackNerd / Vultr | select | Sub-Store (filter) |
| Auto-Fast / Edge / Failover | url-test | GlaDOS R2/B1/US 节点 |
| Express / Auto | fallback | 多个自动测速组 |
| Proxy / Video / Netflix / Scholar / Steam | select | 按用途组合 |

### vps 方案（极简，1 个分组）

无需 GlaDOS 订阅，所有流量走 VPS。

```yaml
proxy_groups:
  - name: VPS
    type: select
    use: [sub3in1]
```

### 自定义方案

在 `profiles/` 下新建 `.yaml` 文件即可：

```yaml
# profiles/custom.yaml
proxy_groups:
  - name: MyProxy
    type: select
    use: [sub3in1]
    
  - name: AutoGlaDOS
    type: url-test
    proxies: ["{R2}", "{US}"]  # {分类名} 引用 GlaDOS 节点
```

### 引用语法

| 语法 | 说明 |
|------|------|
| `{R2}` | 展开为该分类的所有 GlaDOS 节点 |
| `Auto` | 引用其他代理组 |
| `DIRECT` / `REJECT` | Clash 内置 |

可用分类（自动识别 `GLaDOS-XX-NN` 格式）：`R2` `B1` `US` `JP` `TW` `SG` `D1` `S2` `P1` `Netflix`

## 注意事项

- `config.yaml` 包含敏感链接，已被 `.gitignore` 排除
- GlaDOS 链接可能变化，需登录 GlaDOS 后台获取最新链接
- 仅使用 VPS 方案时无需 GlaDOS 链接，脚本自动跳过
- `rules_template.yaml` 可独立编辑，不受脚本更新影响
