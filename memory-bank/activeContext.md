# Active Context — V2.0 终极里程碑归档 ✅

## Current Session
Sprint 5C 终极里程碑归档与面试演示准备。所有 Sprint 1-5 模块已合龙，881 测试通过。

## Sprint 5 (Final) Completed Features

### 1. 设置中心 (Settings Hub) — AD-005
- **文件**: `ui/settings_modal.py`, `config/settings_manager.py`, `config/defaults.py`
- 5 个标签页：外观（字体/字号/模式/色彩）、API（Key 混淆存储）、调仓参数（5 滑块）、影子对比（3 参数）、高级（温度/信念衰减/反思间隔）
- **实时热更新**: SettingsManager.subscribe() → MainWindow._on_settings_changed() 通知链，运行时动态修改字体/外观/字号，无需重启
- **递归字体穿透**: `_apply_font_recursive()` 遍历 widget 树，统一更新所有 CTk 组件字体
- 恢复默认 + 保存按钮，collect_values() 统一收集

### 2. 多模态附件 (Multimodal Attachment) — AD-006
- **文件**: `ui/intake_bar.py`, `ui/chat_panel.py`, `intelligence/ocr_reader.py`
- IntakeBar [+] 按钮 → filedialog 文件选择（图片/PDF/MD/TXT/CSV）
- ChatPanel._handle_attachment_task: 后台线程异步读取 → build_vision_messages → TaskQueue.submit
- OCRReader: read_files() I/O 抽象 + build_vision_messages() 消息构建
- 附件文件标签状态显示

### 3. MainWindow 整合与一键日报
- 四象限 1400x900 布局（Dashboard:Chat = 4:6）
- 齿轮按钮 → SettingsModal
- 一键日报全链路：Position → Optimizer → ShadowComparator → Translator → Reporter
- Hot-apply 订阅注册

## 启动方式

### 模式 A: python -m 模式（推荐开发调试）
```bash
python -m projects.command_center.app
```
- 自动 Mock 模式（无 API Key 时降级）
- 日志输出到 stderr（格式: `%H:%M:%S [LEVEL] name: message`）

### 模式 B: .bat 批处理（一键启动）
```bash
launch_command_center.bat
```
- 双击运行，跨目录安全
- 自动调用 `python -m projects.command_center.app`

## 视觉规范（Sprint 5 强制执行）

1. **零 Emoji 策略**: 所有按钮、标签、欢迎界面不使用 Emoji。按钮使用纯文本（如 "设置"、"发送"、"+", "添加附件"、"恢复默认"、"保存设置"、"一键战报"）
2. **字体规范**: 默认 `font_family = "Microsoft YaHei"`（微软雅黑），基础字号 14pt，Slider 范围 10-24pt
3. **语言规范**: 所有 UI 文本为简体中文（欢迎信息、状态栏、报告内容、标签页名）
4. **报告规范**: 最终报告文件零数学符号泄漏（通过 `test_markdown_no_math_leakage` 验证）
5. **色彩主题**: 默认 `dark` 模式，`blue` 色彩主题，支持 `light/system` 切换

## Red Lines (已验证)
- 最终报告中禁止数学符号泄漏 — test_markdown_no_math_leakage ✅
- PDF 导出优雅降级 — weasyprint 缺失时返回 None，不崩溃 ✅
- Markdown 是核心输出，PDF 是可选附加 ✅
- 全链路 100% 畅通 — test_end_to_end_pipeline ✅
- 零 Emoji 纯文本按钮 — 全部 UI 验证通过 ✅

## 关键架构决策
| AD | 决策 | 影响 |
|----|------|------|
| AD-005 | 设置中心使用 SettingsManager subscribe/notify 热更新模式 | 运行时修改字体/外观，无需重启应用 |
| AD-006 | 多模态附件使用后台线程异步 I/O + OCR 解析 | 主线程不阻塞，附件处理不影响 UI 响应 |
| AD-004 | SemanticTranslator 纯函数式变换层 | 无 I/O，无副作用，可独立测试 |
| AD-003 | Reporter 分段模板模式 | 每节独立构建，便于扩展 |
| AD-002 | PDF 导出 try-except 零侵入降级 | weasyprint 缺失不崩溃 |
| AD-001 | ReportViewer 回调注入解耦 | 不需要全栈 UI 也可测试 |

## Memory Bank Status
- [x] progress.md — V2.0 全功能已同步
- [x] activeContext.md — V2.0 终极归档 ✅
- [x] decision_log.md — AD-005 + AD-006 已写入
- [x] transcript_ledger.md — V2.0 结项日志已追加

## Pending (已清零 — V2.0 全链路就绪)
- [x] Sprint 1-4 所有组件已编码
- [x] Sprint 5 设置中心 + 多模态附件已编码
- [x] 881 项测试 100% PASS
- [x] Memory Bank 四文件同步完成
- [x] .gitignore 包含 config.json 和 .env