# 宿主接入

公开仓库没有完整 Tauri/React 工程，因此以下是私有源码接入契约，不是可直接启动的独立应用。前端仅把已验收的注入模块拆为纯逻辑模块与显式依赖工厂；业务语句不变。

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
  parseSeason, findOtherSeasons,
  Cover: ExistingCover, coverFallback: existingFallback
});
```

| 依赖 | 契约 |
| --- | --- |
| api.setFavorite(item, value) | 原生收藏唯一写入口，Promise |
| api.favorites()/history() | 返回原生条目列表；工厂包装后异步补关系 |
| api.validationStatus() | 返回受信本机服务 `{baseUrl: 'http://127.0.0.1:端口'}` |
| api.search/searchExplorer/searchNovelfm/validationSearch | 存在的入口全部包装进同一个调度队列 |
| parseSeason(title) | 宿主已有标题解析，成功返回含 base 的对象，否则空值 |
| findOtherSeasons(proxyApi, seed, live) | 宿主已有“查找其他季”，返回 `{items, incomplete}`；经 proxyApi.searchNovelfm 请求，每步检查 live |
| Cover | 既有 React 封面组件，接收 `{item, fallback, lazy}`；封面缓存继续由此组件负责 |
| jsxRuntime | React 的 jsx/jsxs runtime |

条目最少含 `seriesId: string`、`title: string`，可含 `episodeCount` 和既有封面等字段。历史另含 `lastEpisode` 与可比较的 `updatedAt`，时间相同或缺失时沿用原生“最新在前”的输入顺序。不把64位ID转成 JavaScript Number。

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

根层单季收到 navigation.open/entryKey，封面和标题共用 onOpen；系列页内各季没有根入口，继续打开原播放详情。卡片补充以下接线：

1. 有 libraryEntryKey 时给封面加 `desktop-series-entry`、`data-collection-key`，aria-label 说明“进入系列”；不显示原播放三角。
2. 封面内渲染 `<libraryUI.CoverLabels kind={libraryKind} progress={libraryProgress}/>`。底部原总集数标签保留，收藏/移除按钮不触发导航。
3. 保留 `.library-page`、`.headline-row`、`.series-card`、`.cover-button`、`.card-copy`、`.card-title`、`.episode-chip`、`.cover-shade` 类名，供范围内样式使用。不要把库样式应用到发现页和播放器。
4. 监听 `desktoplibrarymembership` 后走原加载方法重读收藏与历史；`desktoplibrarychange` 的关系与队列刷新由组件自己监听。

移除原播放详情的补季面板、根卡片下方两个额外入口及手动归组 UI。不要再同时渲染旧片单分组组件。普通收藏后的推荐搜索回调移除，原应用启动推荐搜索 effect 保留。顶部全局搜索横条不渲染，不取消队列或启动搜索本身。

## 原有下一季/其他季入口

已有查找器通过同一个 `seasonSearch(api, item, check, finder, label)` 包装。finder 使用传入 proxyApi 请求，不能闭包调用未包装的原生搜索。下一季也核验相同 albumId，关系不可靠时不自动跳转。

下一季查找由明确按钮触发，打开详情本身不搜索新季；连续播放本季下一集沿用原实现。原启动推荐搜索仍使用包装后的 API。不要把队列任务内的请求再次送回队列，否则产生自等待。

## 维护者验收

在私有源码中完成真实 Tauri 构建后重验普通收藏、异步关系、合集返回、分页、播放详情、全部搜索入口、取消等待与重启。将未知关系、失败、窄窗口和键盘焦点一起验证。本包截图记录本机已接线版本，不替代维护者接入后验收。
