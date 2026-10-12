# 单项 Bug 的修复、发布与回写

## 范围和连接

只处理 job 指定的仓库、分支和 Bug。读取该仓库的 AGENTS.md、PROJECT.md 等实际规则，检查工作区，不覆盖用户修改。SDK 默认不修改；不能因自动化而扩展业务功能或权限。

使用当前安装的 `zentao` REST API v1 MCP。现有 Windows launcher 是用户目录下 `.codex/mcp/zentao-v1/start.ps1`，它自行读取 DPAPI 凭据；不复制、不输出凭据或 Token，不调用会返回 Token 的 get_token。只向 `call` 提供相对 API 路径，不能将其 Token 发给外部绝对 URL。缺少授权连接时报告 blocked，不静默改成浏览器或 API v2。

通过 `/user` 核对账号，只输出必要账号字段；通过 `/bugs/{id}` 或 getBugDetail 读取完整详情。核对 product/project、active 状态和 assignedTo；如果关闭、解决或改派，不继续修改并输出 skipped。

## 证据与修复

- 阅读原步骤、实际/期望、图片和视频。使用 downloadBugAttachments 下载到明确的临时目录，实际查看；stepsImages 不是完整附件清单。未读附件不能宣称已看过。
- 区分代码缺陷、配置错误、旧构建、缺失功能和 SDK 问题。需求不明时不猜测产品行为。
- Android 按明确真机序列号操作，不占用他人的模拟器。优先覆盖安装，不清空数据或卸载来简化测试；恢复测试改变的语言、权限、A/B 面和设备设置，只清理测试自建数据。
- 验证对应失败路径和修复效果；编译通过不能代替 UI/权限/通知/播放的真机验证。缺设备时可以分析和准备修复，但保持 blocked，不能标记已解决。
- 遵守项目的文档维护规则。提交只包含这个 Bug 的实现、必要验证与文档；不得混入其他未提交修改。

## 独立提交和发布

每 Bug 一个可追踪的修复提交，提交说明包含 ID。先检查 upstream，fetch 后只 rebase 未发布提交，不改写已发布历史；冲突按双方意图解决，不能整文件选 ours/theirs。整合后运行相关检查再正常 push。若远端再次推进，只再整合、验证、重试一次；仍失败则 blocked。不 force push、不发布应用版本。

已有修复可以复用已发布提交，无需制造空提交，但必须验证当前问题已被该修复覆盖。网络超时不能直接重试外部写：先读取远端分支或 Bug 历史判断是否已经成功。

## 解决并核验

只有验证通过、提交已确认推送后，才重新读取 Bug 并执行：

```json
{
  "method": "POST",
  "path": "/bugs/12345/resolve",
  "body": {
    "resolution": "fixed",
    "resolvedBuild": "版本ID",
    "comment": "[zentao-watch:任务runId] 原因、修复、验证、最终提交和分支"
  }
}
```

优先使用同产品/项目、确实包含修复的登记版本；尚无新版时使用该 Bug 的 openedBuild，说明测试需取包含提交的新包。不能借用其他项目版本或擅自创建版本。让正常解决流程指派回 opener/QA，显式 qaAccount 优先。不要只改 status，也不要使用不能传 build 的简化 helper。

回读详情必须确认 status=resolved、resolution=fixed、resolvedBuild、QA 指派和包含 job.marker/提交的解决历史；若 QA 同时已关闭且仍为 fixed，保留其操作。HTTP 200 不等于核验完成。响应丢失先读，确认未写入且无并发修改后只重试一次。

监控器会再次用 Git 验证提交存在且属于配置远端分支，并核对禅道解决动作。worker 的成功声明不会跳过这一步。

## 请求补充信息

将缺失的具体信息写到 Bug 并指派回 opener 或 qaAccount，保持 active。不要为了“打回”选择 wontfix、notrepro 或关闭。

当前 ZenTao 实例的通用 PUT 忽略 `comment` 字段。使用 `PUT /bugs/{id}` 的 `steps` 和 `assignedTo`：写前重读最新 steps，将带 job.marker 的补充说明追加到末尾，完整保留图片、步骤及已有记录，不改其他字段。写后回读确认标记、指派和 active 均存在；如已有同一 marker，不重复追加。

仅要求有助复现的缺失材料，例如具体入口/步骤、实际/期望、安装包及 SDK 版本、设备/Android 版本、完整相关日志和录屏，避免机械要求全部项目。SDK 待办写明已定位的边界，保留 active；信息够用后可人工 retry，或测试补充并重新指派后自动再次处理。

## 暂停与恢复

权限审批由 Codex 原有机制决定，脚本不会自动批准。用户明确停止/限制任务时立即服从；计划模式输出 blocked 并 pauseMonitor，不切回执行模式。无法确定外部写是否完成时保留证据和原提交，禁止开始重复修复。

结果文件是 worker 的交接证据，state.json 由监控器单独维护。任务中断后先核对 Git 和禅道，再手动 retry；不要删除任务历史来“解锁”。多个项目可以有独立队列，但同一仓库不能有两套监控同时修改。
