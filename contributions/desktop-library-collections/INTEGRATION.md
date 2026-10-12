# 宿主接入

公开仓库没有完整 Tauri/React 工程，因此以下是私有源码接入契约，不是可直接启动的独立应用。前端仅把已验收的注入模块拆为纯逻辑模块与显式依赖工厂；公开工厂与本机接线沿用相同逻辑。

## 后端

把 `src/desktop_library.py` 放入宿主后端模块目录，在已有桌面验证服务初始化一次，使用同一个有超时的 provider：

```python
from desktop_library import LibraryRelations, make_router
relations = LibraryRelations(desktop_data_dir, provider)
app.include_router(make_router(relations))
```

`provider.api(method, path, body=..., max_retries=1)` 返回已解包 JSON，`provider._episodes_body(comma_separated_ids)` 构造既有详情请求。详情路径为 `/novel/player/multi_video_detail/v1/`；响应 `data[series_id].video_data` 至少提供 `series_id_str` 或精确整数 `series_id`、`series_title`，关系字段为 `related_album_id`、`season_index`。不匹配身份的响应拒绝归组。此模块不写原生 favorites/history 表。

后端仅绑定127.0.0.1。沿用已有 CORS，在允许来源 `http://tauri.localhost`、`tauri://localhost` 的列表中增补请求头 `x-desktop-library-client`、`x-desktop-library-token`、`content-type` 及 GET/POST；不要使用通配来源或删掉已有头。路由自己检查 Origin，POST 同时检查本进程随机 token。

| 路由 | 用途 |
| --- | --- |
| GET `/desktop/library` | 获取关系、旧指定关系和本进程 requestToken |
| POST `/desktop/library/relations` | `{seriesIds: string[]}`，最多100个，内部20个一批 |
| POST `/desktop/library/manual` | 只保留旧接口兼容；新界面不调用 |

关系库位于 `desktop_data_dir/library-relations.sqlite3`，WAL模式。现有封面缓存扩展若在同表加列，需保留它的显式列名写入与迁移逻辑，不回退为本包六列 INSERT。本包没有导出图片缓存实现。

## 前端初始化

在挂载根组件前执行一次，并复用返回对象；不能在组件 render 内重复执行工厂，否则会重复包装 API。

```js
import {createLibraryUI} from './frontend-library.mjs';
const libraryUI = createLibraryUI({
  React, jsxRuntime, api,
  Cover: ExistingCover, coverFallback: existingFallback
});
```

| 依赖 | 契约 |
| --- | --- |
| api.setFavorite(item, value) | 原生收藏唯一写入口，Promise |
| api.favorites()/history() | 返回原生条目列表；工厂包装后异步补关系，并补齐可靠合集的收藏 |
| api.validationStatus() | 返回受信本机服务 `{baseUrl: 'http://127.0.0.1:端口'}` |
| api.search/searchExplorer/searchNovelfm/validationSearch | 存在的入口全部包装进同一个调度队列 |
| parseSeason(title) | 可选覆盖，默认使用本包 parseSeasonTitle；base须保留原始标点，不能整体NFKC转写 |
| findOtherSeasons(proxyApi, seed, live) | 可选覆盖，默认使用本包 findOtherSeasons；旧宿主查找器若未迁移，将不能获得本次回退行为 |
| Cover | 既有 React 封面组件，接收 `{item, fallback, lazy}`；封面缓存继续由此组件负责 |
| jsxRuntime | React 的 jsx/jsxs runtime |

条目最少含 `seriesId: string`、`title: string`，可含 `episodeCount` 和既有封面等字段。收藏的 `updatedAt` 必须来自原生添加时间，历史的 `updatedAt` 来自原生观看时间，不得使用作品上游更新时间；历史另含 `lastEpisode` 与可比较的 `updatedAt`，时间相同或缺失时沿用原生“最新在前”的输入顺序。不把64位ID转成 JavaScript Number。

## 收藏与历史页面

保留原加载、收藏和清空/删除历史逻辑。仅在 favorites/history 视图使用 `LibraryGrid`，其他片单仍用原网格：

```jsx
<libraryUI.LibraryGrid
  items={visibleNativeItems}
  history={nativeHistory}
  view={view}
  renderCard={(item, navigation = {}) => (
    <ExistingCard
      item={item}
      libraryKind="单季"
      libraryProgress={libraryUI.progress([item], nativeHistory, libraryUI.library.relations)}
      libraryEntryKey={navigation.entryKey}
      onOpen={navigation.open || (() => openPlaybackDetails(item))}
      onFavorite={() => toggleNativeFavorite(item)}
      onRemoveHistory={() => removeNativeHistory(item)}
    />
  )}
/>
```

收藏与历史共用 `library.known` 中已有原生条目的完整合集成员；历史根列表仍按原生历史中出现过的系列过滤，不为全未观看的系列新建入口。`renderCard` 必须返回可接收 `reason`、`onRemoveHistory` 的 React 元素：历史中的未观看季度由网格覆盖 `reason="未观看"` 并移除删除历史操作。该卡片应优先显示 reason，避免以第1集作为缺失历史的默认文字。

原生收藏仍是成员事实的唯一持久 owner。自动补收藏只遍历已出现于收藏/历史且已有可靠合集关系的条目，同 ID 串行写入、去重；不启动搜索。用户取消先记录到 `localStorage` 的 `guoban:library-auto-favorite-exclusions:v1` 字符串 ID 数组，在途自动写入结束后由同 ID 取消操作覆盖；重启后仍跳过。手动再收藏清除该 ID 的排除。该小型偏好不是第二份收藏数据库；存储不可用时原生操作仍继续，跨重启排除无法保证，应由宿主处理其存储错误。自动写失败不会标完成，其他季度继续；30秒冷却后，在下一次记录或关系刷新时重试，不设轮询。

根层单季收到 navigation.open/entryKey，封面和标题共用 onOpen；系列页内各季没有根入口，继续打开原播放详情。卡片补充以下接线：

1. 有 libraryEntryKey 时给封面加 `desktop-series-entry`、`data-collection-key`，aria-label 说明“进入系列”；不显示原播放三角。
2. 封面内渲染 `<libraryUI.CoverLabels kind={libraryKind} progress={libraryProgress}/>`。底部原总集数标签保留，收藏/移除按钮不触发导航。
3. 保留 `.library-page`、`.headline-row`、`.series-card`、`.cover-button`、`.card-copy`、`.card-title`、`.episode-chip`、`.cover-shade` 类名，供范围内样式使用。不要把库样式应用到发现页和播放器。
4. 监听 `desktoplibrarymembership` 后走原加载方法重读收藏与历史；`desktoplibrarychange` 的关系与队列刷新由组件自己监听。

移除原播放详情的补季面板、根卡片下方两个额外入口及手动归组 UI。不要再同时渲染旧片单分组组件。普通收藏后的推荐搜索回调移除，原应用启动推荐搜索 effect 保留。顶部全局搜索横条不渲染，不取消队列或启动搜索本身。

## 排序与滚动

合集卡片、页内标题、辅助名称及根列表名称排序共用展示名。只去掉季序号后末尾的冒号和空白；不要改每季原标题、搜索词、关系键，也不要统一删问号和叹号。

合集默认季号倒序，支持正序，所有已知季度一次列出，不再渲染内部页码；Cover继续接收lazy。根列表仍每页12条，候选每页8条。根时间排序只取当前页所属原生列表中的成员，不能把收藏时间用在历史排序。单季根标题按完整可见名称排序，合集按可见主标题排序，中文数字采用自然顺序。

`guoban:library-sort:v1` 仅保存favorites/history/seasons三个排序偏好，不保存第二份成员或时间。切换根排序回第一页；切换季号排序回到系列区顶部，需保留该区scroll-margin以避开顶部栏。选择框使用现有`--paper`、`--ink`、`--line`、`--muted`、`--coral`主题变量，缺失时回退浅色；只有aria-label，不显示额外“排序”文字。样式由工厂唯一stylesheet提供，宿主不能再用旧library样式覆盖它。

## 原有下一季/其他季入口

从 `season-search.mjs` 导入 `findOtherSeasons` 和 `findNextSeason`，替换旧标题/查找函数，避免两套规则继续并存。已有查找器通过同一个 `seasonSearch(api, item, check, finder, label)` 包装。finder 使用传入 proxyApi 请求，不能闭包调用未包装的原生搜索。下一季也核验相同 albumId，关系不可靠时不自动跳转。

工厂代理额外提供 `resolveSeasonCandidates(seed, candidates, live)`，用共享关系缓存核验并返回 `{items, verified}`：items保留同合集和未知关系，冲突项排除；verified表示至少一个候选已确认与seed同合集。查找器依据该结果决定是否回退，而不是仅检查原搜索是否返回非空。副标题差异候选仍需主标题匹配和媒体类型一致；未知关系不会自动收藏。直接单独调用本包查找器时也应提供此代理；缺少核验只能返回待确认候选，不能自动播放。

原标题不改，比较键单独规范化。首轮保留原始中英文符号，仅剥离末尾季序号；完整首轮无有效匹配后，按 `？?！!：:` 前至少两字符的主标题回退一次。每个词最多两模式×三页，每页最多20条，共享30秒总预算；同词/模式/页去重。错误、重复页或超预算标未完成，不启动更宽回退；已经取得的候选保留供收藏编排最终核验，不再将结果截成20条。下一季先保留原有明确季序号搜索；不足时复用上述查找器和剩余预算，副标题回退候选只供选择，不扩大自动连播条件。

下一季查找由明确按钮触发，打开详情本身不搜索新季；连续播放本季下一集沿用原实现。原启动推荐搜索仍使用包装后的 API。不要把队列任务内的请求再次送回队列，否则产生自等待。

## 维护者验收

在私有源码中完成真实 Tauri 构建后重验普通收藏、异步关系、合集返回、分页、播放详情、全部搜索入口、取消等待与重启。将未知关系、失败、窄窗口和键盘焦点一起验证。本包截图记录本机已接线版本，不替代维护者接入后验收。
