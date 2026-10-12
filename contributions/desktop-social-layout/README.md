# 固定播放器外框、抽屉与顶部选集避让

这是发行仓库的源码接入材料，合并不会改变已发布应用。维护者仍需移入应用源码、完成真实播放器验收并发布。这里只提交新写功能、最小接线和匿名测试，不包含完整应用或安装包。

## 依赖

依赖上述两个前端与表情包；bootstrap.mjs 提供组合入口。原生布局补丁基于 #204 加 desktop-danmaku-backend 的两个补丁，不能直接应用到未接入的私有源码。

## 接入与行为

bootstrap.mjs 导出 createSocialUI({React,jsxRuntime,resolveEndpoint})，返回 Drawer、Controls、Selection 及依赖对象。它引用 contributions 下其他三个前端包，需共同检出。只调用一次工厂，不要在每次 render 创建新组件类型。

```js
const {Drawer,Controls,Selection,set}=createSocialUI({React,jsxRuntime,resolveEndpoint:trustedEndpoint});
// 原 header: <Selection media={mediaRef}/>
// 原 .player-toolbar: <Controls media={mediaRef} sessionKey={session.streamUrl}/>
// 原 aside（保留选集正文）: <Drawer session={session} media={mediaRef}/>
// 原剧场按钮及 T 快捷键共用的回调：onTheater: () => set(mediaRef.current, {social:false})
```

宿主保留 .app-shell、.desktop-player、header、.desktop-player-layout、.player-stage、.player-toolbar、aside、.window-controls、.window-pin、.player-mini-toggle 类。外框尺寸由现有窗口 owner 固定，layout 使用剩余空间的 grid、min-height:0/min-width:0；不得按评论内容重算窗口大小。抽屉开时右列占空间，视频缩窄；关时恢复。CSS只装一次。

顶部逐个测量控件：把原绝对定位的置顶按钮纳入窗口按钮行，选集放在迷你窗口及窗口按钮左侧，留12px间隔。使用 ResizeObserver 响应尺寸变化，不用固定右偏移覆盖实际测量。没有隐藏任何原生窗口按钮，也没有改置顶/快捷键。

宿主窗口控制组件应在普通窗口始终渲染已有置顶按钮，不要用 `dark || pinned` 决定是否渲染；`dark` 只决定配色，`pinned` 决定图标及按下状态。继续调用原窗口 owner 的查询和切换 API，避免新增第二套置顶状态。迷你模式沿用宿主原有窗口控制策略。验收同时检查普通窗口及播放窗口的按钮可见性、置顶/取消置顶的实际窗口状态和顶部边界。

原生模式依次应用 patches/native-layout.patch、patches/native-layout-events.patch（前提为弹幕后端两个补丁）。rect/occlusion 改动立即 flush，忙碌时下一轮不延迟250ms；设置弹层在现有原生表面切出可见区域，关闭恢复。SetWindowRgn 成功后所有权交给 Windows，失败路径释放本包 GDI 对象。不复制 #204/#205 的整个播放器。

原生接线需要 #204 的控制栏自动显隐修复。本包的事件补丁已兼容移除永久可见样式后的版本；不要重新添加强制 `.player-chrome` 的 opacity 或 pointer-events 覆盖。显隐由宿主现有控制器处理，弹幕设置面板打开时的临时保持显示仍有效。

抽屉取消独立标题行，关闭按钮与页签同排。仅选集页可收起整层右列；两个评论页关闭后返回选集并保持右列展开。底部评论开关关闭时隐藏两个评论页签，只保留选集；开启时恢复页签并进入本集评论。

底部控制栏始终单行。按 `.player-stage` 可用宽度使用容器查询缩小按钮、音量滑条和间距，保留全部控制；宽屏图标按钮32×32 CSS像素，窄视频区域缩至28或20像素宽，SVG 与悬停背景居中。宿主需保留 `.player-clock`、`.player-toolbar-spacer`，倍速 select 和音量 range 作为控制栏直接子节点。原生表面按 `.player-chrome` 实际顶部预留空间，并观察控制栏高度变化，避免固定84像素造成遮挡；宿主必须把进度条和按钮放在这个容器内。画面单击继续由宿主现有处理器执行暂停/继续，本包不重复绑定 click 或键盘监听。

剧场按钮和 T 快捷键只通过现有 `set` 关闭右侧栏。宿主移除独立的剧场状态及 `.theater` 类切换，按钮保持“剧场模式”名称，可将提示改为“收起右侧栏（T）”。点击后“选集”和“评论”仍按原规则打开右侧栏；重复点击只保持关闭。关闭、评论开关和缓存继续由现有侧栏 owner 管理，窗口、播放和弹幕不随此动作改变。浏览器回归覆盖宽窄窗口、评论页及侧栏已关闭的情况。

tests/run.mjs 是跨包唯一浏览器回归入口，覆盖评论前端和布局，不在两个 PR 重复维护测试。评论关闭时仅隐藏页面，后台读取及会话缓存由评论包统一管理；测试覆盖重开复用、请求合并、分页、刷新和换集取消。真实 Chrome headless 使用匿名 HTTP fixture；不能替代 Tauri 原生 Win32 接入验收。

## 验证

Python 3.10+、Node 18+；命令以 pwsh 为入口，在包含对应 contributions 的检出根运行。Python API 测试先安装本包 requirements-test.txt。浏览器组合测试需要 Chrome；也可传 --channel msedge。其他模块没有 npm 运行时依赖，React/JSX runtime 由宿主提供。

```pwsh
npm --prefix contributions/desktop-social-layout ci
node contributions/desktop-social-layout/tests/run.mjs --channel chrome
# 按依赖顺序应用原生补丁后：
node contributions/desktop-social-layout/tests/test_native_layout.cjs contributions/desktop-native-playback/src/frontend-native.js
```

公开测试为人工构造输入，不连接上游。新导出模块已经独立验证；跨包 Chrome 用例由布局包统一维护。此前本机安装还完成53项窗口功能与21项原生像素检查，快/中/慢档（8/14/24秒）实测为161.25/92.5/53.75物理像素/视频秒；这些属于当时本机接线证据，不是本公开包在所有设备或上游发布后的保证。

回滚时撤回本包接线及新增模块，保留原播放入口、用户偏好和原片，不修改其他播放/缓存贡献。原快捷键不新增、不拦截。Issue 关闭以应用发布并验证为前提，见 [ISSUES.md](ISSUES.md)。

## 首轮审查修复

迷你模式恢复单列视频、隐藏已经展开的 aside；ResizeObserver 也观察迷你按钮本身。新增无需窗口 resize 的按钮变宽测试及迷你模式回归。本轮补充抽屉关闭、无标题布局、播放按钮对齐和单击暂停/继续的组合回归；原生桥接测试覆盖实际控制栏高度、DPI、resize、暂停/继续命令和监听清理。

选集紧凑样式沿用宿主的 `.player-series-summary`、`.episode-heading`、`.season-continuation`、`.episode-navigation`、`.episode-page-buttons`、`.episode-locate`、`.desktop-episode-grid` 和 `.episode-expand` 类。分组容器包含范围状态及前后按钮：范围在左，前后按钮在右同排；宿主保留原事件与DOM顺序，样式不添加监听。定位和季查询继续由宿主负责。侧栏320px及以上验收同排，长列表保留滚动空间。
