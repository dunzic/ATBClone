# Codex 分身能聊天，但没有终端工具

## 结论和适用范围

2026-09-10 对 Codex Desktop 26.901.31953 / CLI 0.153.1 的排查确认：
分身有本地终端和文件编辑执行能力，但自定义 Responses API 网关未完整处理该版本发送的工具格式。
仅看到登录界面或收到聊天回复，不能视为分身开发功能验收通过。

本次恢复的是普通函数形式的终端调用。自定义工具、命名空间工具以及应用内 MCP 连接仍需要分别验收，不能据此宣称与原版功能完全一致。

## 诊断证据

| 测试 | 结果 |
| --- | --- |
| 原版和分身使用本机模拟接口 | 两者都生成了工具，默认放在 `input` 的 `additional_tools` 扩展消息中 |
| 真实网关，默认模型工具格式 | 模型回复没有终端/编辑工具，测试文件不变 |
| `use_responses_lite=false`，保留代码工具模式 | 工具移到标准 `tools` 字段，但 `exec` 仍为 `custom` 类型；网关下仍不能调用 |
| 同时使用 `tool_mode=standard` | `exec_command` 成为普通 `function`；GPT-6 Astra 实际读取并追加测试文件成功 |
| 本机模拟接口驱动分身执行器，携带 HOME 隔离 hook | 终端、独立 `apply_patch`、再次读取文件均成功，退出码 0 |
| 分身桌面现有测试聊天，GPT-5.6 Sol | 实际执行临时目录中的文件写入和读取，退出码 0 |

GPT-6 Astra 的多步骤在线验收在读取、追加完成后达到测试客户端的 100 秒上限；没有将该次测试的最终回复计为通过。桌面验收则完成了整个回合。

这组对照支持“网关工具格式兼容性”是本次终端缺失的原因。没有检查网关服务端实现，不能据此断言其具体丢弃或转换逻辑。

## 自定义 API 的兼容配置

仅当网关出现上述问题时启用。使用 ChatGPT 官方登录或已经兼容完整工具协议的网关，无需此配置。

1. 退出分身。
2. 使用 Python 3.11 或更新版本运行仓库中的脚本，传入分身及其独立的 `CODEX_HOME`：

```bash
python3 scripts/configure_codex_api_compat.py \
  --app "$HOME/ATBClone/Apps/ChatGPT2.app" \
  --codex-home "$HOME/ATBClone/Data/ChatGPT2/Codex"
```

脚本从当前分身内置的 `codex` 可执行文件提取该版本的模型目录，仅修改两项工具协议属性：

```json
{"use_responses_lite": false, "tool_mode": "standard"}
```

生成 `CODEX_HOME/models-api-compat.json`，并在 `config.toml` 的顶层添加 `model_catalog_json`。
原配置会保留注释并备份为 `config.toml.before-atb-api-compat-时间戳`。
脚本不读取、复制或修改 `auth.json`，不改变模型名称、API 地址、权限策略或登录状态。
如果已有其他模型目录、自定义模型不在内置目录中，或者无法识别此版本的内置目录，脚本拒绝修改。

3. 重启分身，用现有测试聊天实际创建、读取一个临时文件；检查工具调用记录、退出码和真实文件。

模型目录需要在更新 Codex 后重新生成。启用后仍需网关支持 `custom` 类型，才能使用独立 `apply_patch`；终端可以正常读写文件。完整工具能力应通过兼容完整 Responses 协议的服务验收。

回退时退出分身，恢复脚本生成的原配置备份，随后重启。生成的模型目录不再被引用，可保留。

## 另一个独立问题：应用内工具身份校验

桌面日志还出现了：

```text
dynamic_app_tools_peer_rejected reason=missing-code-signing-identity
MCP client for `codex_app` failed to start: Codex app tools pipe closed
```

这属于应用内工具连接问题，与终端执行器不是同一个故障。实验中恢复四个运行时文件的原始字节后，这个拒绝仍存在；因此没有把该实验作为引擎修复提交，也没有关闭或绕过身份校验。

当前机器上的原应用运行时也未通过独立 `codesign --verify --strict`，不能把恢复原文件等同于恢复有效签名。此问题尚未修复，影响依赖 `codex_app` 的应用内操作。

## 团队安装包验收要求

之前的 `team.1` 包没有覆盖真实 API 工具调用验收，不能宣称完整支持 Codex 分身开发。
在重新分发前，应在干净机器、有效签名的源应用及团队实际 API 网关上验证：

- 模型实际调用终端并取得退出码；
- 创建、修改、再次读取测试文件；
- 如需独立编辑器、浏览器或应用内工具，逐项验证对应调用；
- 重启后，任务、登录和独立配置仍可使用。

参考：[OpenAI Docs 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。
其中 `shell_tool` / `unified_exec` 默认启用；这两个开关打开并不证明 API 网关已把工具正确提供给模型。
