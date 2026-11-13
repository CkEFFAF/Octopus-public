# T018 / v1 实验设计模板

任务编号: T018

设计版本: v1

设计状态: draft

这是待填写模板，不是已通过的 T018 设计，不应直接登记为可运行实验。复制后可将任务号改为权威 `TASK_QUEUE.md` 中真实的任务号。每份设计和评审回执都应使用相同任务号和设计版本。

建议落点为设备项目目录 `agent/designs/<任务号>/<设计版本>/DESIGN.md`，评审落点为同目录 `REVIEW.json`，实际评审证据为 `REVIEW_EVIDENCE.json`。这些都是设备原生路径，不是专家 `/.agent/` 路径。设计路径及评审路径必须真实可读，批准前对最终字节计算 SHA256。

设计版本 `design_revision` 是 v1、v2 等设计编号，和执行账本用于 CAS 的整数 `revision` 不同。提案阶段需修订时，以当前账本 revision 执行允许的 reopen、revise、approve 流程，换用新的设计版本及路径，保留原稿与旧评审。已经训练过的实验禁止换设计后重跑同一 ID，独立后续实验在原表申请新的 T 号，并用 previous 关联前版。

GPU 忙碌时可以读取现有材料、做设计和高级模型审阅。设计阶段不能启动训练、GPU 评估、数据重建等占用共享资源的工作；实现和预检所需资源也应在设计中写清楚。

## 代码设计

### 事实依据与授权范围

填写原表任务行、读取时间、原表摘要或 SHA256、当前状态、用户已认可的方向、引用的准则和来源路径。若原表已经终止、否决、完成、归档，停止登记为新的可执行工作。旧记忆和旧排期不能覆盖最新原表。

说明灵感、已有现象及其原始证据，写出可证伪假设和唯一主要改动。区分观察事实、推断与待验证内容。对 T018，可引用原表的物理反事实增广方向，但具体接触点、旋转、标签映射、穿模检查及失败策略必须由设计者依据真实数据和代码补全。

### 修改位置与数据流

逐项填写真实代码路径、类或函数、现有行为、拟修改行为、输入输出张量形状、损失或评分定义、配置开关、参数初始化和 optimizer 参数组。列出会被复用的已有实现，以及不应改动的共享源码、论文权重和运行中实验。

记录基础仓库 commit 或文件 SHA256、配置版本、数据版本和既有依赖。实现放在独立版本副本，不能覆盖共享训练代码。不能凭空编造未读取的文件名、接口或启动参数。

### 固定执行清单

批准前必须填写下列实际值，不能保留占位符。执行账本中的 argv、cwd、baseline、metric、direction、threshold、candidate_version、scope、dependencies 和 previous 应与此一致。

```json
{
  "id": "T018",
  "design_revision": "v1",
  "design_path": "",
  "design_review_path": "",
  "candidate_version": "",
  "base_code_revision": "",
  "argv": [],
  "cwd": "",
  "baseline": "",
  "metric": "",
  "protocol": "",
  "direction": "maximize",
  "threshold": null,
  "scope": "",
  "dependencies": [],
  "previous": null
}
```

这里列出的是设计信息模板，不是可直接执行的 helper 请求。科学假设、命令、对照设置或代码范围变更都需要新设计版本及重新审阅，DeepSeek 实现节点不能临场改成另一项创新。

## 实施步骤

按顺序填写可以由编码 Agent 直接执行的步骤。每一步至少说明输入路径、准确改动、产出路径和完成判据。

1. 核对原表仍允许该任务，核对设计、评审和冻结哈希；不一致时停止准备。
2. 从已记录的基础版本建立独立工作副本，记录实际代码路径。不得复制或重启已有运行中的同号实验。
3. 按代码设计实现列明的函数、配置和数据处理，不添加设计外的新方法。
4. 执行设计允许的轻量预检，例如语法、shape、有限值、开关关闭的逐位等价、参数是否进入 optimizer。逐位比较涉及随机层时先固定随机种子。
5. 检查实际 argv/cwd/config/checkpoint 与设计一致，输出准备回执和文件摘要；本节点不启动训练。
6. 只在容量检查通过且本版本真实领取成功后，通过持久 Job 执行固定命令，记录真实日志与运行回执。不能把后台提交成功视为训练完成。
7. 根据评估验收规则归档结果、现象、问题与解决方法、分析和后续版本建议。新的创新建议进入新的设计阶段。

在上面骨架中补全本任务的具体实施顺序和算法细节。遇到缺失信息或设计错误时，写准备失败说明或退回修订，不让编码 Agent 即兴补科学方案。

## 评估验收

填写候选与基线的实际日志、权重、数据与指标文件路径。明确相同 seed、相同训练预算、best 选择规则和数据管线；不跨不可比管线比较绝对值。

训练指标来自真实 `Eval:` 块，按 epoch 对齐，不使用进度条跨 batch 平均值。报告训练期趋势、逐次验证变化和同等预算的 best 对比，保留不利指标。3 至 6 epoch 冒烟只能证明能运行，不能证明科学提升。具体 epoch 预算以最新原表及用户要求为准，不机械套用旧手册的 30、70 或 100 epoch。

写清主指标、方向、逐指标阈值、噪声或置信区间、护栏指标、零训练前置探针、早停条件、无效实验条件和失败判据。采用 A/B/C/F 口径和当前指标弹性规则时，记录引用版本；D/E 仅作附表。T018 原表中的支撑/接触组 mA@1、standing/lying 混淆率与真伪分类 AUC 属于不同的验收或反例条件，不能合并为一个方便的标量来掩盖失败。

为 helper 准备可比的候选与 baseline JSON，至少含 `metric`、`protocol`、有限数值 `value`。单个 helper outcome 只是一项机器判定，不能代替完整的多指标科学审阅。进程 exit 0、报告归档完成与最终指标提升是不同结论。

列出报告目录和版本关系：启发来源、代码/config/checkpoint 标识、真实运行日志、评估日志、现象记录、问题及解决、分析、优化建议、前版/后版报告位置。按原准则增量更新 TASK_QUEUE、EXPERIMENT_LOG、WEEKLY_REPORT 和 MECHANISM_LOG，不整表覆盖。

## 依赖/风险/资源

### 依赖和执行门槛

列出哪些前置是已完成的事实，哪些只是条件。区分 previous 的研究沿革与 dependencies 的执行前置：当前 helper 只允许 dependencies 全部 succeeded 后领取，不能将失败前版机械填进 dependencies 导致永久阻塞。若需要从失败版吸取教训，用新任务号和 previous 表达，并审阅新的前置。

只满足设计条件，不代表可以运行。例如 T013 依赖有效性结论；T007 在旧原表中有已失效的 ep60 触发条件且 T006 探针不通过；T015 需要先得到规范推理 dump。这些冲突应写成 blocked 和解锁证据，不能由设计文档自动抹去。

### 资源和维护边界

填写 GPU 张数与编号、显存上限、CPU/IO 需求、预计时长、训练/评估预算、磁盘需求与现有可用量、日志和权重保留位置。默认自发实验一张卡，不挤占他人。当前执行器固定 GPU0，旧原表中 GPU1 或双卡的排期不能直接沿用，必须先核对当前授权和实际设备状态。

记录共享路径只读约束、原始论文权重保护和禁止修改的文件。维护准则要求保留代码与长期档案，不为实验启动自动清理其他用户的文件。不得将 shell 访问不到的 `/.agent/` 专家路径传给设备命令。

### 高级审阅与真实回执

使用 `gpu-experiment-review-template.json` 创建 pending 评审。设计可由 Grok 4.7 或已授权且具备相应权限的 ACP 高级 Agent 审阅纠正；DeepSeek 负责实现和常规工作，不能仅自填高级模型名称就成为高级审阅证据。

approved 回执的六个字段是 task_id、design_revision、design_sha256、verdict、reviewer_model、review_evidence_path。task_id 和 design_revision 必须与本文件的独立行一致。设计修改后重新计算 SHA256 并重新评审；批准时冻结设计和评审文件的双 SHA，claim/run 复核。

review_evidence_path 应指向设备可读、非空的实际调用证据。建议由审阅节点完成后的确定性步骤从真实 Graph 记录导出，而非让模型写一句“已调用”。证据至少关联已发布 Graph 版本、run、node、activation、实际 delivery/thread，以及被审阅的设计 SHA；模型身份从真实配置和调用记录获取。ACP 还应包含真实 tool call、runner/session、结束状态和结果摘要，不能只记录包装节点的 DeepSeek 输出。

当前 helper 检查文件、字段和哈希，不认证这些文件的来源，也不证明 reviewer_model 字符串真的对应高级模型。现有 Graph Agent output.evidence 提供 delivery_id/thread_id，不能单凭这两个值证明实际 ACP 调用。没有可核验的真实调用记录时保持 pending，不伪造 approved。

### 设计图归档脚本的输入

`gpu_innovation_designs.py` 与 queue helper 放在同一设备目录。它读取 `OCTOPUS_WORKFLOW_INPUT` 或标准输入中的 JSON。manifest_path 指向设备 JSON 文件，其 items 为完整 helper proposal，每项另有显式布尔 approved 和可选 blockers。每批 0 至 10 项，前置项先登记；更多设计分批接续，不能截掉或遗忘原表任务。没有新设计时 items 和 reviews 可以为空，脚本只刷新索引，不创建或审批实验。

Graph 将已完成审阅节点的完整 output 绑定为 review_output，不能让设计 Agent 重新拼装其 evidence。审阅结果的格式为：

```json
{
  "evidence": {
    "delivery_id": "由引擎提供",
    "thread_id": "由引擎提供"
  },
  "result": {
    "reviews": [
      {
        "task_id": "T018",
        "design_revision": "v1",
        "design_sha256": "实际设计文件的SHA256",
        "verdict": "pending",
        "comments": ["基于原表和实际设计的审阅意见"]
      }
    ]
  }
}
```

reviewer_model 和 authorized_scopes 来自 Graph 固定配置，不能来自设计 Agent 的 manifest。当前认可任务的窄 scope 为 `3dssg-existing-approved-backlog`，不授予新方向通用授权。只有显式 approved=true、无 blockers、scope 命中且高级审阅 verdict=approved 的对应实际设计，才调用 helper approve。缺配置、未命中、pending、rejected 和 approved=false 均保持 proposed，脚本以 auto_approve=false 禁止从父项绕过本次批准。

固定 scope 也不能证明某项创新属于用户原授权。高级审阅者仍需逐项核查当前原表、用户认可依据、前置和否决状态；T007、T008、T013 等未决冲突必须列出 blockers，并保留 approved=false。

脚本保存收到的真实 wrapper 和评审模型配置，生成不可覆盖的证据文件和六字段评审回执。它不独立认证调用来源，信任边界是 Graph 对 output 的绑定。更换模型字符串、手写 delivery_id 或手写 ACP 调用声明不会因此变成可认证的模型调用。

`DESIGNS.md` 列出任务号、设计版本、代码设计与步骤文件、评审链接和状态。单个条目有哈希/身份/旧 ID 冲突时记录 needs_review，整次脚本退出非零，已成功登记的真实条目仍保留。原始已领取、运行或终态项不会被覆盖或复活。未执行项换设计只通过 helper 的 reopen、revise 和 approve CAS 操作，不能改写既有 argv 等不可变提案字段。
