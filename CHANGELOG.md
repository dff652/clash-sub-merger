# 更新日志 (CHANGELOG)

## [Unreleased] / 最新重构 (2026-02-27)
这是项目建立以来最大规模的重构，侧重于架构解耦、代码维护性和对错误数据的防渗透能力：

### 新增 (Added)
- 新增 `download/` 层：订阅数据现在会被严格物理保存在本地 `download/` 目录供随时查验，代替旧版临时的 cache。
- 新增 **防数据污染拦截**：通过 `utils` 在下载订阅时，检查 proxies 节点数目如果小于 5 个将被定义为“脏数据”并拒绝复写本地安全版本。
- 新增 `rules/` 分流规则分类化目录：针对不同方案（Mihomo/Clash/Custom/VPS）解耦定制规则，实现**零强行规则回退**。不再强行把所有自定义规则塞入不支持此组别的标准订阅中。
- 新增 `utils.py` 共享函数库，大幅缩减 `merge_glados.py` 和 `sync_profiles.py` 的臃肿和重复度。
- 为 `run.sh` 追加全套 `download` 子命令。
- `merge_glados.py` 追加真正的 `argparse` subparsers 解析器（支持 `download`, `merge`, `list` 等子命令）。

### 更改 (Changed)
- 全面调整架构目录说明，清晰化：脚本、配置层、下载缓冲区、输出层。
- 移除不再需要的 `cache/` 目录及其在代码、配置中的遗留选项（如删除了 `glados_cache_dir` 配置项）。
- `sync_profiles.py` 在遇到缺乏 `proxy-groups` 元数据的客户端时，由报错退出降级为提示警告并正常结束（防止阻断批处理）。

### 修复 (Fixed)
- 修正了一处因为未指派 `with` 语法糖而产生的潜在 File Descriptor 句柄泄漏（L589 in old merge_glados.py）。
- 修缮了因为导入位置处于代码段落中部、全局日志未共享使用带来的警告。
- 将 `.gitignore` 更新以屏蔽新引入包含敏感凭据的 `download/` 目录。
