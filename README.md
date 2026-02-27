# Clash 订阅合并工具

自动合并多个订阅源（GlaDOS、Sub-Store 等），生成 Clash/OpenClash YAML 配置文件。支持多客户端（Mihomo/Clash）和多套代理组方案。

## 目录结构

本工具采用解耦式设计，将配置、规则、下载、合并拆分为独立模块，保证数据的纯洁性和方案的可追溯性：

```
clash-sub-merger/
├── 脚本程序层
│   ├── run.sh                    # 交互菜单 & 命令行入口
│   ├── merge_glados.py           # 核心合并脚本
│   ├── sync_profiles.py          # 同步脚本（从 GlaDOS 更新 profile 分组结构）
│   └── utils.py                  # 公共模块（统一日志、下载校验、脱敏）
│
├── 静态配置与策略层
│   ├── conf/                     # 配置目录
│   │   ├── config.example.yaml   #   配置模版（提交 Git）
│   │   └── config.yaml           #   私有配置（.gitignore 排除）
│   ├── profiles/                 # 节点代理组方案定义
│   │   ├── mihomo.yaml           #   Mihomo 客户端（sync 自动生成）
│   │   ├── clash.yaml            #   Clash Standard（sync 自动生成）
│   │   ├── custom.yaml           #   自定义高级方案（手动维护）
│   │   └── vps.yaml              #   极简方案（仅 VPS）
│   └── rules/                    # 分流规则模版（与 profiles 包严格对应）
│       ├── mihomo.yaml / clash.yaml / vps.yaml / custom.yaml
│
├── 动态数据层
│   └── download/                 # 原生订阅数据落地区（含 5 节点防污染校验，.gitignore 排除）
│
└── 输出与日志层
    ├── output/                   # 合并生成的最终配置（直接喂给 Clash/Mihomo）
    └── logs/                     # 运行日志
```

## 快速开始

```bash
# 1. 安装依赖
pip install pyyaml requests

# 2. 创建配置
cp conf/config.example.yaml conf/config.yaml
# 编辑 conf/config.yaml，填入 GlaDOS 订阅链接等信息

# 3. 推荐：使用交互菜单完成一切操作
./run.sh
```

## 使用方式（命令行模式）

除了直接输入 `./run.sh` 调出交互菜单，你也支持直接在命令行追加参数：

```bash
./run.sh download              # 下载并校验所有订阅到 download/
./run.sh download mihomo       # 仅下载 mihomo

./run.sh sync                  # 同步所有客户端 profiles (拉取分组结构)
./run.sh sync mihomo           # 只同步 mihomo

./run.sh merge mihomo          # 组装合成最终的 mihomo.yaml
./run.sh merge clash           # 合并生成 clash 配置
./run.sh merge custom          # 合并生成 custom 配置
./run.sh merge vps             # 合并生成 vps 配置

./run.sh list                  # 查看当前可用的所有方案
./run.sh log                   # 查看生成日志
```

## 代理组配置方案 (`profiles/`)

| 方案     | 说明                                             | 维护方式                    |
| -------- | ------------------------------------------------ | --------------------------- |
| `mihomo` | Mihomo/Clash Meta                                | `sync_profiles.py` 自动同步 |
| `clash`  | Clash Standard                                   | `sync_profiles.py` 自动同步 |
| `custom` | 自定义分组（支持 `{US}`, `{Balancer}` 动态引用） | 手动编辑                    |
| `vps`    | 极简（仅 Sub-Store VPS 节点，无需 GlaDOS 订阅）  | 无需维护                    |

### 日常维护指北

当你需要在 GlaDOS 面板更新链接/重置 Token 后：
1. 编辑 `conf/config.yaml` 更新 `glados_urls`。
2. 运行 `./run.sh` 依次选择：下载 -> 同步 -> 合并。或者运行命令流：
   ```bash
   ./run.sh download
   ./run.sh sync
   ./run.sh merge mihomo
   ```

## 高级特性

- **防节点污染**：当 GlaDOS 请求不稳定返回空节点或超小列表时，`download` 命令会通过 `min_proxy_count` (默认 5) 拦截阻断并保留上一次成功的数据。
- **动态组件引流**：在 `profiles/custom.yaml` 的 proxies 数组中，你可以书写 `{US}`、`{TW}` 等标签，脚本将在合并时自动把属于这类国家的节点全部展开填入组内。
- **零盲区规则自动修复**：如果订阅方案未绑定分流规则里需要的组别（比如你没建 Scholar 但规则里要求用 Scholar），合并脚本会自动感知并将盲区回退至 `Proxy` 组或主入口。

## 注意事项

- `conf/config.yaml` 和 `download/` 目录包含敏感链接和节点密钥，严格受到 `.gitignore` 的保护，请勿随意提交。
- `profiles/mihomo.yaml` 和 `profiles/clash.yaml` 会被 `sync_profiles.py` **暴力覆写**。如需自定义，请直接修改 `custom.yaml`，或新建方案。
