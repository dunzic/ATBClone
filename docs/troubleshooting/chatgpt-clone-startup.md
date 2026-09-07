# ChatGPT 分身无响应：旧版安装与本地规则覆盖排查记录

## 结论

2026-09-08 在 macOS Apple Silicon 上排查了一例 ChatGPT 分身创建后无响应的问题。实际安装的 ATBClone 为 1.3.0，而检出的仓库源码为 1.4.0；用户规则目录还保存着旧的 `com.openai.codex.yaml`，会优先于内置规则加载。

使用仓库现有的 1.4.0 引擎和内置规则重新创建分身后，代码签名验证通过，原版与分身同时运行，分身正常显示独立登录页面。初次恢复没有新增引擎代码修改；相关隔离实现已包含在提交 `646ab43` 中。本分支随后补充了更新失败时恢复原 bundle 的代码，见下文。

这是“新版引擎 + 新版规则”组合的验证结果，没有分别回退每个设置进行对照实验，因此不能把初次无响应归因到某一个开关。此前更新操作中的文件权限错误是另一项已确认的故障，其具体权限来源未查明。

## 环境与证据

| 项目 | 排查结果 |
| --- | --- |
| 原应用 | `/Applications/ChatGPT.app`，版本 `26.901.31953` |
| 原应用 Bundle ID | `com.openai.codex` |
| 实际框架 | `Codex Framework.framework`，不能只根据应用显示名称或框架文件名认定为 Cocoa |
| 已安装 ATBClone | 1.3.0 |
| 用于恢复的源码 | 1.4.0，基于提交 `4f8b34d` |
| 自定义规则 | `~/ATBClone/recipes/com.openai.codex.yaml` |
| 恢复后的分身 | `~/ATBClone/Apps/ChatGPT2.app` |

`RecipeLoader.get()` 首先读取用户目录中的同名 YAML，之后才尝试内置规则。自定义规则按整个文件加载，不会自动与新版内置规则合并。因此，仅更新安装包不会消除旧规则的覆盖。

关键配置差异如下，完整规则以仓库内置 YAML 为准：

| 配置 | 本机旧规则 | 恢复时采用的内置规则 |
| --- | --- | --- |
| `app_type` | `cocoa` | `electron` |
| `strip_sandbox` | `false` | `true` |
| `patch_chatgpt_isolation` | 未配置，旧引擎没有对应专用实现 | `true` |
| `strip_url_schemes` | 未配置 | `true` |
| `CODEX_HOME` | 未配置 | `{{ATB_DATA_DIR}}/Codex` |
| `symlink_whitelist` | 空 | `Library/Keychains` |

`strip_sandbox` 分支也负责处理重签名所用的 entitlements，不能将这个选项简单理解成原应用一定启用了沙盒。新版 ChatGPT 路径使用 C 启动器和 Cocoa/POSIX 目录函数 hook，配合独立 `HOME`、`TMPDIR` 和 `CODEX_HOME`。

### 旧日志说明了什么

1. 旧引擎报告 Mach-O 头部空间不足：剩余 32 字节，需要 80 字节，随后回退到 C 启动器。这是一条回退警告，不能单凭它认定启动失败。
2. 日志记录 `Successfully triggered open`。这只能证明发出了打开应用的请求，不能证明窗口、渲染进程和后台服务已就绪。
3. 后续更新出现 `cp: ... Operation not permitted`，并记录一次重复操作被拒绝。日志不足以确定权限错误是由哪个进程或系统机制造成的。
4. 更新失败后再次启动提示分身文件不存在。原更新流程会先删除旧 bundle，硬克隆失败时又会清理目标 bundle，因此复制失败可能让记录保留、应用文件却已缺失。初次恢复未修改这一更新流程；本分支后续修复了这个问题。

## 本分支补充的代码修复

- CLI 和 GUI 不再提前删除原 bundle；应用探测和规则解析失败时，原应用保持原状。
- 软克隆与硬克隆共用 `bundle_transaction.replace_bundle()`，在同一 shell（需要时包含提权）内将原 bundle 移到同目录下的独立备份目录，再执行重建。重建期间目标路径可能暂时不存在，应先退出分身再更新。
- 复制、编译、签名或验证失败时，退出处理函数清理不完整 bundle 并恢复原 bundle。成功后才移除旧备份。分身的数据目录不参与 bundle 的移动或回滚。
- 若恢复也因权限等原因失败，保留备份并在错误输出中报告路径，避免清理掉最后一份原应用。
- 同一目标 bundle 使用目录锁防止多个创建或更新操作重叠。软克隆也必须通过签名及严格验证，不再忽略签名错误。

已通过 180 项相关测试，其中实际临时文件测试覆盖失败恢复、成功替换、首次创建失败、信号终止、锁冲突和恢复失败保留备份；CLI/GUI 测试覆盖探测或构建失败后原应用、数据和状态文件保持不变。测试未修改正在运行的正式 ChatGPT2，也未将这一后续代码修复重新部署到本机安装包。

这是针对可捕获失败的恢复机制，不是断电或 `SIGKILL` 下的原子更新保证。若进程被强制终止，可能遗留 `<分身路径>.atbclone-lock` 和同目录的 `.atbclone-backup.*`；先确认没有操作仍在运行，再检查备份中的 `original.app` 并恢复，不能直接批量删除这些目录。

## 恢复步骤

1. 查看 **正在运行的 ATBClone** 版本，不能把仓库中的版本号当成已安装应用的版本号。
2. 检查原应用 `Info.plist` 的 `CFBundleIdentifier`，据此定位规则。本案例为 `com.openai.codex`；其他 ChatGPT 版本可能使用 `com.openai.chat`。
3. 备份已安装 ATBClone、`clones.yaml`、对应用户规则和已有分身数据。将备份规则放到独立备份目录，避免仍以同名 YAML 留在活动规则目录内。
4. 安装包含 ChatGPT 专用隔离实现的版本，并核对用户规则。若没有必须保留的自定义内容，可把旧规则移到备份目录，使内置规则生效；若有代理或自定义路径等设置，应与新规则逐项核对后保留。
5. 完全退出旧分身，再重建分身。已有账号数据应保留，不能为了修复启动问题直接选择“同时删除数据”。若旧 bundle 已缺失，先确认原数据目录和备份，再创建或恢复记录。
6. 验证签名、实际界面和管理记录。不要在分身复制或更新期间再次启动或更新同一分身。

本案例先在临时目录构建并验证，再创建正式分身、保存管理记录和更新本地规则。已安装 ATBClone 使用原应用包中的 Python 运行环境装入仓库 1.4.0 源码，并完成本机 ad-hoc 重签名；这是本地恢复构建，不是新发布的官方安装包。

## 验证方法与结果

可先执行只读检查（应用名称不同或使用自定义路径时请替换路径）：

```bash
plutil -extract CFBundleShortVersionString raw /Applications/ATBClone.app/Contents/Info.plist
plutil -extract CFBundleIdentifier raw /Applications/ChatGPT.app/Contents/Info.plist
codesign --verify --deep --strict "$HOME/ATBClone/Apps/ChatGPT2.app"
```

本案例实际验证了：

- 正式分身通过 `codesign --verify --deep --strict`。
- 原版进程仍在运行，分身启动了独立主进程、渲染进程和后台服务。
- 正式分身显示 `Sign in to ChatGPT` 页面，含登录按钮。
- ATBClone 界面显示 1.4.0，并列出正式目录中的 `ChatGPT2` 管理记录。
- 分身日志及后台状态文件写入其独立数据目录。

本次未验证第二个账号登录完成后的 API 请求、所有登录回调方式、通知功能或所有数据类别的完全隔离。独立登录页说明启动已恢复，不等于这些功能均已通过验证。

## 分身的 Codex 配置目录

默认内置规则设置了 `CODEX_HOME={{ATB_DATA_DIR}}/Codex`。对于名为 `ChatGPT2`、使用默认数据路径的分身：

```text
~/ATBClone/Data/ChatGPT2/
├── Codex/                 # 分身 CODEX_HOME
│   ├── config.toml        # 模型、API 提供商等配置（按需创建）
│   └── auth.json          # 使用文件认证存储时的认证文件
├── Home/                  # 分身 HOME，包含应用支持文件与日志
└── Tmp/                   # 分身临时目录
```

原版默认使用 `~/.codex`；分身显式设置了 `CODEX_HOME`，因此应在 `<分身数据目录>/Codex` 配置，而不是 `<分身数据目录>/Home/.codex`。采用其他认证存储方式时，认证信息不一定写入 `auth.json`。

修改配置后完全退出并重启分身。新版创建流程只初始化独立的 Codex 目录，不自动复制原版 `~/.codex` 的认证和会话数据。问题反馈或 Git 提交中不要包含真实 API 密钥、认证文件或原始账号日志。
