# GOAI 复赛提交前人工确认项

本文件只列平台行政项和展示选择，不表示科学证据缺失。科学终局仍为
`insufficient_evidence`。

## 已确认

| 字段 | 值 |
|---|---|
| 队伍名 | `source sequence` |
| 公开仓库 | <https://github.com/1ove9/yaf-goai-semifinal> |
| 仓库许可 | MIT License |
| 计划标签 | `goai-semifinal-2026-09-03` |
| 登记作品名 | 三维自由形空间中的非直觉天线拓扑发现 |
| 公开方式 | sanitized root snapshot；不公开原 commit/tree 时序及被排除的历史提示词或本机工具配置 blobs |

## 提交平台需人工确认

- 队员姓名、顺序、联系人、手机号和邮箱。
- 平台最终标题、摘要、关键词及声明勾选。
- 是否要求单独上传压缩包；若要求，记录文件名、大小与包级 SHA-256。
- 视频链接、格式、大小、时长与访问权限。
- GitHub tag 和最终公开提交的 40 位哈希是否已回填到平台。
- 截止时间与时区以组委会页面/通知为准。

## 展示材料边界

- `artifacts/analysis/semifinal-a-span-support-causal-probe-v1/dose-response.png` 可作附录图，
  图注必须包含 `counterfactual-only` 与 `display-only`。
- 旧几何 PNG/GIF 若使用，必须标明其真实历史 run/step，不能冒充终局 step 265。
- 所有媒体必须注明：
  “Visualization reconstructed from archived parameters; it does not participate in scientific
  scoring or validation.”
- 不使用 `YAF-M1`、`CONFIRMED`、“发明”“首创”“可制造”“实物验证”“自主自适应”或
  等价表述描述本次终局。

## 公开快照的已披露限制

- 私有 144-commit 原研究顺序不能从公开 Git 独立重放。
- 原提交 ID 只作溯源标签；公开审计依靠 255-entry SHA-256 总账、冻结文件哈希和
  `scripts/semifinal_public_snapshot_verify.py`。
- 历史 `scripts/semifinal_demo.py --verify` 需要已删除的原始 Git 对象，不是公开评审命令。
