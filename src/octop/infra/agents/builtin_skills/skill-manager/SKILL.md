---
name: skill-manager
description: 必须用于通过对话管理当前专家实例的 Skill，包括查找、检查、安装、导入、更新、编辑、列出、恢复或删除。支持 skillhub.cn/skills/... 页面 URL、SkillHub CLI、本地及上传文件、SKILL.md、ZIP/TAR、Git/GitHub 和普通下载 URL；也用于把 PDF、Markdown、文档、代码、图片等任意资料整理成新 Skill。Must use for conversational Skill management from files, URLs, Git repositories, archives, or SkillHub.
metadata:
  octop:
    emoji: "🧩"
    label:
      zh: "技能管理"
      en: "Skill Manager"
    summary:
      zh: "在当前实例中查找、安装、导入、更新或删除技能。"
      en: "Find, install, import, update, or delete skills on this instance."
---

# Skill Manager

只管理当前实例的 `{{OCTOP_SKILLS}}/`。当前实例工作区固定为 `{{OCTOP_WORKSPACE}}`；上传文件通常位于其中的 `inbound/`。系统文件（skills、内置 skills、会话等）在 `{{OCTOP_SKILLS}}` 所在目录。不要用 `pwd`、`$HOME`、`~/.octop-harness/workspace`、记忆文件或搜索结果重新猜测工作区。不要改其他实例、全局 Skill 目录或 `{{OCTOP_BUILTIN_SKILLS}}/`。

## 操作入口

优先使用当前对话的原生管理工具，它们沿用已认证用户的身份和当前专家工作区，不需要宿主 Shell 或管理员登录：

- `octop_skill_list` 查看已安装技能；`octop_skill_search` 搜索 SkillHub；`octop_skill_install` 从一个 SkillHub slug 或支持的 URL 安装。
- `octop_skill_save` 编写合法的 SKILL.md 和可选 UTF-8 附属文件；已有目标必须得到明确替换授权后设置 overwrite=true。`octop_skill_set_enabled` 控制启用状态。
- 原生技能工具使用现有包验证、Harness 工作区存储和动态加载。安装不执行包内脚本、不安装依赖；会话显式技能筛选仍有效。内置、挂载和锁定包保持原有保护。
- 增加实际工具能力时，使用 `octop_mcp_list/upsert/test` 配置用户自己的 MCP，再用 `octop_connector_attach` 挂接。`octop_tool_list/set_enabled` 管理工具开关。`octop_plugin_catalog/install/set_enabled` 管理插件；全局插件安装需要 plugins 模块权限，可能执行插件及其依赖，图绑定能力等当前回合结束再加载。
- 不能读取宿主 CLI 登录、JWT 密钥或其他用户凭据来代替会话身份。缺少模块权限时报告具体权限，不要建议通过 Shell 绕过。

原生工具尚未覆盖的本地资料检查、回收站恢复等操作，可在现有工作区和执行权限内使用内置脚本；不要因为没有 Shell 就声称原生 URL 下载和 SkillHub 安装不可用：

```bash
python "{{OCTOP_BUILTIN_SKILLS}}/skill-manager/scripts/manage_skills.py" <command>
```

```bash
# 列出已安装技能
... list

# 检查来源，不写入已安装 skills 目录
... inspect "<file-directory-url-or-skillhub:slug>"

# 安装；仓库或压缩包内的多个 Skill 可一次安装
... install "<source>" [--subpath "path/in/repo"] [--name "slug"]

# 仅在用户明确同意替换后覆盖
... install "<source>" --force

# SkillHub 搜索；结果可用 skillhub:<slug> 检查或安装
... skillhub-search "<query>" --limit 10

# 仅在用户明确同意删除后执行；实际移动到 skills/.trash/
... remove "<slug>" --yes

# 从回收站恢复
... restore "<trash-name>"
```

## 来源处理

1. **现成 Skill、目录或 ZIP/TAR**：先 `inspect`；检查通过且用户已要求安装时执行 `install`。
2. **Git/GitHub URL**：可直接处理仓库、GitHub `tree` 子目录和指向 `SKILL.md` 的 `blob` URL。复杂仓库使用 `git+<url>` 和 `--subpath`。
3. **SkillHub 页面 URL**：`https://skillhub.cn/skills/<namespace>/<slug>` 可直接传给 `inspect` 或 `install`；脚本会解析 namespace 和 slug。不要自行安装/升级 CLI，不要直接运行 `skillhub install`。
4. **普通 HTTP(S) URL**：脚本处理直接文件和压缩包。若 URL 是其他介绍网页，先用现有网页工具读取并找到公开仓库、下载地址或 `SKILL.md`，再交给脚本。不得绕过登录、付费墙或访问控制。
5. **SkillHub 搜索**：用户只描述能力时，先搜索并给出 1–3 个候选的 slug、名称、用途和来源，让用户选择；用户已点名具体 Skill 时，可直接检查并安装。
6. **任意非 Skill 文件**：普通资料不会因复制而自动成为 Skill。先读取和理解材料，再使用内置 `skill-creator` 工作流，将可复用知识、步骤和必要资源整理为合法 Skill，写入 `{{OCTOP_SKILLS}}/<slug>/`，然后执行 `inspect` 校验。

## 变更规则

- 新安装请求本身即表示同意新增；目标已存在时停止并说明冲突，只有获得明确同意才使用 `--force`。
- 编辑现有 Skill 前先读取其 `SKILL.md` 和相关资源，只改该 Skill 目录；修改后重新 `inspect`。
- 删除前点名目标并取得明确确认。使用 `remove --yes`，不要直接 `rm -rf`。需要恢复时使用 `restore`。
- 安装后报告 slug 和最终路径。当前会话会在下一次模型请求时重新读取技能目录；新安装、更新、删除及启用状态无需新建会话。安装不代表已执行或验证技能中的第三方代码。

## 安全边界

- 脚本限制下载及解包体积、文件数，拒绝路径穿越和符号链接，并通过暂存目录安装。
- 不执行、导入或 source 下载包中的代码。安装表示部署 Skill 内容，不代表第三方代码已通过安全审计。
- 不在输出中回显 URL 凭据；私有来源只使用环境中已有的 Git 或 SkillHub 凭据。
- 若当前实例没有 Shell 执行能力，仍可用文件工具处理简单文本 Skill，但必须说明 URL 下载、安全解包和 SkillHub CLI 无法完成，不能假装成功。
