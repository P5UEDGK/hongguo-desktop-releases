# 收藏与历史按系列归组

同一剧的多个季度在收藏、观看历史里合并为文件夹。单季与合集使用同一个系列页：单季显示一季，合集共用本地已知各季；进入页面不触发搜索。需要补齐时，用户点击“查找并收藏各季”。

这是发行仓库的独立源码贡献。仓库不含完整应用源码，合并本目录不会改变已发布应用；维护者需按 [接入说明](INTEGRATION.md) 移入私有源码、完成宿主验收后发布。本包不包含安装包、完整应用资源、账号或用户数据库。

## 行为

- 普通收藏立即调用原生保存接口，随后异步读取关系，不搜索其他季。取消再收藏复用已经成功保存的关系。
- 按详情 `related_album_id` 归组，按 `season_index` 排序，全部 ID 保持十进制字符串。标题相似或搜索返回同名，不能单独作为归组依据。
- 主动补季使用统一的分季搜索模块，再核验每个候选的关系。相同合集自动收藏；已有收藏、本轮取消的季跳过；关系未知候选由用户选择，关系冲突候选排除。搜索可能漏季，仍可手动搜索再收藏。
- 原标题和中文标点完整保存。搜索先用原始标点、去掉末尾季序号的标题；无有效同合集匹配时，再用首个 `？?！!：:` 前的主标题回退。副标题不同可进入合集ID核验，未知关系仍需手动选择。网络失败、超时或分页截断不触发更宽搜索。
- 合集展示名只清理去季号后末尾的中英文冒号和空白，例如“持械入宋：”显示“持械入宋”；各季原标题、搜索词和合集ID不变，问号与叹号保留。
- 合集默认按季号倒序，支持切换正序，未知季号放最后。收藏、历史根列表可按名称正序/倒序或最近添加/最近观看排序；合集取该页原生成员的最新时间，三处选择独立保存。主题选择框不重复显示“排序”文字，键盘操作与辅助名称保留。
- 已搜索到的候选不再被20条结果上限截断；支持“40季”这样省略“第”的季号写法。后续分页/关系查询失败或超时仍保留候选，最终由收藏编排再次核验；未知或冲突关系不会自动加入。
- 各搜索入口共用一个队列，相同任务复用 Promise。取消后等待在途原生请求结束，再让下一个任务执行；不做定时更新或自动发现新季。
- 收藏与历史的同一合集共用本地已知季度列表、季数、排序、封面和观看进度。根页只显示原记录中出现过的系列，未看过的季度标为“未观看”，不伪造历史。
- 已有及以后归入可靠合集的本地季度自动加入原生收藏；仅查详情的候选、关系未知条目和孤立单季不触发。按 ID 去重，不增加搜索。手动取消的季跨重启保持取消，主动再收藏才清除排除；删除收藏不删除历史或关系。
- 合集内一次显示所有已知季度，向下滚动查看；根列表每页12项，待确认候选每页8项。返回保留原页、滚动位置和入口焦点；关系晚到、单季变为合集时系列页不丢失。
- 封面区分“合集”“单季”，合集标季数。右下角进度为最近观看集序号÷该季总集数，向下取整并限制0–100%；合集注明最近季，未观看和总集数未知分别显示对应文字。标签统一为11px、24px高，背景不透明度40%。
- 搜索的等待、核验、完成、失败和取消文字只替换按钮右侧的同一个位置，不增加下方状态行或移动季列表。长文字省略，`title` 和 `aria-live` 保留完整内容。
- 根卡片没有重复“补齐合集”或“进入合集查看各季”入口；播放详情不再放补季面板；界面不提供手动归组。旧指定关系保留读取兼容。
- 顶部全局搜索横条不渲染，原启动推荐搜索保留。

## 代码与验证

`src/desktop_library.py` 负责持久关系及本机路由；`src/library-core.mjs` 负责队列、归组、进度与收藏编排；`src/frontend-library.mjs` 提供显式宿主工厂及组件；`src/season-search.mjs` 统一标题解析、原词/前缀查询与其他季/下一季查找。React、封面组件、搜索接口与原生存储由宿主提供，不另建一套应用。

Python 3.10+、Node 18+。在仓库根以 pwsh 执行：

```pwsh
python -m pip install -r contributions/desktop-library-collections/requirements-test.txt
python contributions/desktop-library-collections/tests/test_desktop_library.py
node contributions/desktop-library-collections/tests/test_library_core.cjs
node contributions/desktop-library-collections/tests/test_library_adapter.mjs
node contributions/desktop-library-collections/tests/test_season_search.mjs
node contributions/desktop-library-collections/tests/test_season_integration.mjs
node contributions/desktop-library-collections/tests/test_library_sort.mjs
node --check contributions/desktop-library-collections/src/frontend-library.mjs
```

后端8项、前端核心20项及工厂接线4项、分季搜索17项、排序6项及搜索/收藏集成2项回归均使用隔离或固定输入，不连接上游。实际窗口证据与范围见 [验证说明](VALIDATION.md)，31张原始截图及逐图说明见 [界面截图](docs/SCREENSHOTS.md)。

## 接入限制

成功关系持久保存；无关系结果冷却1天，失败冷却5分钟；每批详情最多20个 ID。provider 必须沿用宿主有超时的请求实现。队列不会抢占无法取消的原生请求，宿主若永不返回，后续搜索仍会等待。

本包保留旧 `manual_groups` 数据与接口以兼容历史数据，但不渲染手动归组入口。若宿主已经接入封面缓存等扩展，应合并关系接口和 schema 迁移，不能用本包基线覆盖其新增列；封面组件继续由已有封面 owner 提供。
