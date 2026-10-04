# 皇室战争控制台：设计依据与实现规范

本次研究先读取官方产品文章、设计系统及书籍公开资料，再生成完整桌面界面参考，最后改造现有 Tk 控制台。书籍查看范围为作者／出版社介绍、公开目录及可取得的样页，未将未获得全文的书籍表述为已完整阅读。

## 在线参考

| 来源 | 已读取的内容 | 本次应用 |
| --- | --- | --- |
| [Linear 官方改版说明](https://linear.app/now/behind-the-latest-design-refresh) | 减少导航视觉干扰、柔化边界、降低冷蓝灰饱和度，突出任务内容 | 墨绿侧栏、浅色主内容、减少重复边框，保留原有三个页面 |
| [Vercel Geist 配色](https://vercel.com/geist/colors)与[排版](https://vercel.com/geist/typography) | 背景、边界、文字与交互状态分别承担职责；字号、字重与行距形成可重复规则 | 主次文字分层、有限语义色、统一组件状态、中文与数字分开设置字体 |
| [Stripe Workbench](https://stripe.com/blog/workbench-a-new-way-to-debug-monitor-and-grow-your-stripe-integration) | 运行总览与日志、错误等细节的组织关系 | 当前运行摘要、战绩、奖励分组，详细记录保持在各自页面 |

Agent-Reach 的 Exa 路由在本机返回 `Unknown MCP server 'exa'`，因此按失败回退规则使用普通网页工具读取以上官方来源。内置浏览器连接时缺少 `browser-service.mjs`，没有为设计任务修改浏览器或网络配置，也没有声称完成了所有参考网站的浏览器视觉检查。本项目是原生 Windows Tk 窗口，最终渲染检查使用 Windows 界面工具。

## 书籍公开资料

| 书籍 | 官方来源及实际查看范围 | 提炼到本项目的原则 |
| --- | --- | --- |
| Refactoring UI | [作者官网](https://refactoringui.com/)，目录与公开示意内容 | 减少次要元素的视觉权重；采用间距、字号系统；减少无意义边框 |
| Thinking with Type，Ellen Lupton | [Chronicle Books 第三版页面](https://www.chroniclebooks.com/products/thinking-with-type-1)，介绍与内容说明 | 排版同时考虑对齐、间距、顺序与可读性，不能仅换字体 |
| Grid Systems in Graphic Design，Josef Müller-Brockmann | [Niggli 出版社](https://niggli.ch/en/products/rastersysteme-fur-die-visuelle-gestaltung)，书籍介绍与示例索引 | 各分区共享网格和对齐基线，容器内边距一致 |
| The Non-Designer's Design Book，Robin Williams | [Pearson 出版社](https://www.pearson.com/en-us/subject-catalog/p/Non-Designer-s-Design-Book-The-4th-Edition/P200000000691?view=educator)及[公开样章](https://www.peachpit.com/content/images/9780133966152/samplepages/9780133966152.pdf) | 对比、重复、对齐与亲密性；将战绩指标与奖励指标按语义分别成组 |
| Envisioning Information，Edward Tufte | [作者官网](https://www.edwardtufte.com/book/envisioning-information/)，介绍与主题说明 | 信息分层；颜色用于识别结果；先看总况，再看趋势与单场记录 |
| The Design of Everyday Things，Don Norman | [Hachette 出版社](https://www.hachettebookgroup.com/titles/don-norman/the-design-of-everyday-things/9780465050659/)，书籍介绍 | 控件动作明确、状态可见、反馈及时，禁用状态与实际可执行动作一致 |

## 完整界面方案

[设计参考图](console-design-concept.png)覆盖侧栏、页头、当前运行、五项战绩指标、最近运行走势、奖励累计、对局表格和页脚。图中的数值只是设计参考；程序继续读取真实运行状态和历史记录。

采用以下项目规范，数值是本项目的实现选择，并非上述产品的官方 token：

- 侧栏 `#192d29`；页面 `#f5f6f3`；主表面 `#ffffff`；主要文字 `#23332d`；次要文字 `#738079`；边界 `#e2e7e1`；主色 `#326b56`；失败色 `#b15d55`；奖励区 `#f0f6f1`。
- 中文使用 Microsoft YaHei UI；指标数字使用 Segoe UI；日志时间使用 Consolas。稳定区分页面标题、运行标题、分区标题、指标值、正文与解释。
- 主界面保留“对局记录、策略对比、运行日志”三项导航。战绩范围继续只筛选历史，不更改当前机器人策略。
- 五项战绩在同一横向区域，以细分隔线组织；奖励数量和金币在独立浅绿区域，避免七个指标容器竞争。
- 表格正文统一深色，只为胜／负／未知／平局结果绘制标签；标签覆盖层保留原始数据、单击选中、双击查看和滚轮滚动。
- 所有按钮、文字、表格、趋势块都由原生代码生成。生成图作为视觉参考，不作为可点击界面背景。
- 以真实进程状态控制启动与停止按钮；无可领奖励、待确认结果、未知结果仍按原有含义呈现。

## 实现时的有意调整

设计参考中的数值、时间及策略文字替换为实时值；新增明确的金币核实说明，保留未知结果数量与全部统计口径。原生桌面窗口有系统标题栏；较小窗口减少同时可见的记录行数，保留滚动和固定口径说明。Canvas 按钮支持 Tab、Enter 和空格键，Ctrl+1／2／3切换原有三页。

最终运行截图与检查结果另见同目录的 `console-redesign-validation.md`。生成概念使用内置 Image Gen；完整提示词保存在本任务 `work/ui-redesign-20261003/design-prompt.txt`。
