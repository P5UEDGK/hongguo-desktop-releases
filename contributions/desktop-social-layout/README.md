# 固定播放器外框、抽屉与顶部选集避让

这是发行仓库的源码接入材料，合并不会改变已发布应用。维护者仍需移入应用源码、完成真实播放器验收并发布。这里只提交新写功能、最小接线和匿名测试，不包含完整应用或安装包。

## 依赖

依赖上述两个前端与表情包；bootstrap.mjs 提供组合入口。原生布局补丁基于 #204 加 desktop-danmaku-backend 的两个补丁，不能直接应用到未接入的私有源码。

## 接入与行为

bootstrap.mjs 导出 createSocialUI({React,jsxRuntime,resolveEndpoint})，返回 Drawer、Controls、Selection 及依赖对象。它引用 contributions 下其他三个前端包，需共同检出。只调用一次工厂，不要在每次 render 创建新组件类型。

```js
import {createSocialUI,desktopNativeControlsOverlay,desktopControlsCanHide} from './src/bootstrap.mjs';

const {Drawer,Controls,Selection,toggleSidebar}=createSocialUI({React,jsxRuntime,resolveEndpoint:trustedEndpoint});
// 原 header: <Selection media={mediaRef}/>
// 原 .player-toolbar: <Controls media={mediaRef} sessionKey={session.streamUrl}/>
// 原 aside（保留选集正文）: <Drawer session={session} media={mediaRef}/>
// 原剧场按钮及 T 快捷键共用的回调：onTheater: () => toggleSidebar(mediaRef.current)
```

宿主保留 .app-shell、.desktop-player、header、.desktop-player-layout、.player-stage、.player-toolbar、aside、.window-controls、.window-pin、.player-mini-toggle 类。外框尺寸由现有窗口 owner 固定，layout 使用剩余空间的 grid、min-height:0/min-width:0；不得按评论内容重算窗口大小。抽屉开时右列占空间，视频缩窄；关时恢复。CSS只装一次。

顶部逐个测量控件：把原绝对定位的置顶按钮纳入窗口按钮行，选集放在迷你窗口及窗口按钮左侧，留12px间隔。使用 ResizeObserver 响应尺寸变化，不用固定右偏移覆盖实际测量。没有隐藏任何原生窗口按钮，也没有改置顶/快捷键。

宿主窗口控制组件应在普通窗口始终渲染已有置顶按钮，不要用 `dark || pinned` 决定是否渲染；`dark` 只决定配色，`pinned` 决定图标及按下状态。继续调用原窗口 owner 的查询和切换 API，避免新增第二套置顶状态。迷你模式沿用宿主原有窗口控制策略。验收同时检查普通窗口及播放窗口的按钮可见性、置顶/取消置顶的实际窗口状态和顶部边界。

原生模式依次应用 patches/native-layout.patch、patches/native-layout-events.patch（前提为弹幕后端两个补丁），并将上方导入的 `desktopNativeControlsOverlay` 保持在原生前端适配器的作用域内。rect/occlusion 改动立即 flush。进入播放器即使用完整区域，首张控件位图准备期间也不挖除底部区域；控制栏背景透明，显示、隐藏及再次显示都不改变视频尺寸。现有 DOM 控件按原布局绘制为带 alpha 的位图，由 libmpv 合成到完整视频上。绘制沿用宿主解析后的尺寸、间距和字体，避免 SVG 自身视口改变按钮位置。DOM 继续处理按钮、拖动、键盘焦点和无障碍，不复制播放状态机。设置面板保留自己的卡片背景，仅该面板需要窗口 region 避让。

位图协议只接受有界尺寸和压缩后的预乘 BGRA 像素，解压上限4MiB；不接受路径、指针或 mpv 命令。原生后端自行创建内存缓冲并同步调用 overlay-add，复用引擎前移除旧位图。前端最多每120ms检查一次，只提交变化的画面，销毁时取消绘制和观察器。需要支持 SVG foreignObject、Canvas 和 CompressionStream 的 WebView2；绘制失败会保留原 DOM 避让入口以便操作，并在 `media.desktopControlsOverlayError` 留下诊断。该降级路径仍可能出现原黑底，不能当作透明验收通过。

宿主还需应用 `patches/native-session-rate-limit.patch`。状态轮询、位图更新和释放会话不能共用普通数据接口的每分钟额度，否则持续播放会收到429，释放也可能失败，留下遮挡界面的原生视频窗口。补丁仍先验证密钥，对当前托管进程的会话密钥与回环客户端跳过所有接口的通用计数，片库浏览、切剧、切集和持续播放不再累计本机额度；其他密钥与远程请求沿用原限流。媒体路由的来源检查、会话数、控制队列和像素上限继续生效。控制栏通过最终序列化画面比较去重，普通状态 DOM 变化不会清空上次画面，时钟、进度与布局的真实变化仍会刷新。

接入 #213 连续切集时，再应用 patches/standby-layout.patch，使备用帧与当前画面使用相同完整区域。该补丁只删除原先扣除控制栏高度的逻辑，不改预热、切集和播放状态。

原生接线需要 #204 的控制栏自动显隐修复。本包的事件补丁已兼容移除永久可见样式后的版本；不要重新添加强制 `.player-chrome` 的 opacity 或 pointer-events 覆盖。显隐由宿主现有控制器处理，弹幕设置面板打开时的临时保持显示仍有效。将原控制器的隐藏等待改为1000ms，计时回调在 `desktopControlsCanHide(stage.current, dragRef.current)` 为真且媒体仍在播放时隐藏；存在拖动、悬停控制栏、键盘焦点或设置面板时重新计时。继续使用原鼠标、焦点与拖动事件，不另建显隐控制器。暂停沿用原策略。

抽屉取消独立标题行，关闭按钮与页签同排。仅选集页可收起整层右列；两个评论页关闭后返回选集并保持右列展开。底部评论开关关闭时隐藏两个评论页签，只保留选集；开启时恢复页签并进入本集评论。

底部控制栏始终单行。按 `.player-stage` 可用宽度使用容器查询缩小按钮、音量滑条和间距，保留全部控制；宽屏图标按钮32×32 CSS像素，窄视频区域缩至28或20像素宽，SVG 与悬停背景居中。宿主需保留 `.player-clock`、`.player-toolbar-spacer`，倍速 select 和音量 range 作为控制栏直接子节点。进度条和按钮沿用宿主原有位置、样式和事件，不因这次画面修复而移动。原生表面不再永久扣除 `.player-chrome` 高度，也不把其透明顶部 padding 变成黑色占位；监听原控制栏显隐和尺寸变化，只更新控件位图及设置面板遮挡，显隐不改变视频缩放。画面单击继续由宿主现有处理器执行暂停/继续，本包不重复绑定 click 或键盘监听。

剧场按钮和 T 快捷键共用 `toggleSidebar`：右侧栏展开时收起，关闭时打开选集；从评论页收起后再点也进入选集。宿主移除独立的剧场状态及 `.theater` 类切换，按钮保持“剧场模式”名称，提示可用“切换右侧栏（T）”。选集、评论、关闭和缓存继续由现有侧栏 owner 管理，窗口、播放和弹幕不随此动作改变。浏览器回归覆盖二次点击、宽窄窗口、评论页及侧栏已关闭的情况。

tests/run.mjs 是跨包唯一浏览器回归入口，覆盖评论前端和布局，不在两个 PR 重复维护测试。评论关闭时仅隐藏页面，后台读取及会话缓存由评论包统一管理；测试覆盖重开复用、请求合并、分页、刷新和换集取消。真实 Chrome headless 使用匿名 HTTP fixture；不能替代 Tauri 原生 Win32 接入验收。

## 验证

Python 3.10+、Node 18+；命令以 pwsh 为入口，在包含对应 contributions 的检出根运行。Python API 测试先安装本包 requirements-test.txt。浏览器组合测试需要 Chrome；也可传 --channel msedge。其他模块没有 npm 运行时依赖，React/JSX runtime 由宿主提供。

```pwsh
npm --prefix contributions/desktop-social-layout ci
node contributions/desktop-social-layout/tests/run.mjs --channel chrome
# 按依赖顺序应用原生补丁后：
node contributions/desktop-social-layout/tests/test_native_layout.cjs contributions/desktop-native-playback/src/frontend-native.js
python contributions/desktop-social-layout/tests/test_overlay_control.py contributions/desktop-native-playback/src/desktop_native.py
# 接入会话限流补丁后，指向宿主实际后端：
python contributions/desktop-social-layout/tests/test_session_rate_limit.py backend/server.py
# 同时接入 #213 并应用 standby-layout.patch 时：
node contributions/desktop-social-layout/tests/test_native_layout.cjs contributions/desktop-native-playback/src/frontend-native.js contributions/desktop-seamless-transition/src/frontend-seamless.js
```

公开测试为人工构造输入，不连接上游。新导出模块已经独立验证；跨包 Chrome 用例由布局包统一维护。此前本机安装还完成53项窗口功能与21项原生像素检查，快/中/慢档（8/14/24秒）实测为161.25/92.5/53.75物理像素/视频秒；这些属于当时本机接线证据，不是本公开包在所有设备或上游发布后的保证。

回滚时撤回本包接线及新增模块，保留原播放入口、用户偏好和原片，不修改其他播放/缓存贡献。原快捷键不新增、不拦截。Issue 关闭以应用发布并验证为前提，见 [ISSUES.md](ISSUES.md)。

## 首轮审查修复

迷你模式恢复单列视频、隐藏已经展开的 aside；ResizeObserver 也观察迷你按钮本身。新增无需窗口 resize 的按钮变宽测试及迷你模式回归。本轮补充抽屉关闭、无标题布局、播放按钮对齐和单击暂停/继续的组合回归；原生桥接测试覆盖完整区域、DPI、resize、透明控件及设置面板、暂停/继续命令和监听清理；浏览器用例确认背景 alpha、预乘像素、拖动/焦点保护和销毁清理。

选集紧凑样式沿用宿主的 `.player-series-summary`、`.episode-heading`、`.season-continuation`、`.episode-navigation`、`.episode-page-buttons`、`.episode-locate`、`.desktop-episode-grid` 和 `.episode-expand` 类。分组容器包含范围状态及前后按钮：范围在左，前后按钮在右同排；宿主保留原事件与DOM顺序，样式不添加监听。定位和季查询继续由宿主负责。侧栏320px及以上验收同排，长列表保留滚动空间。


## 透明控制栏验收

本机用匿名竖屏 HEVC 夹具完成真实 Tauri/WebView2 和 libmpv 验收：首次布局即完整，展开时底部仍显示视频与烧录字幕，隐藏前后画面尺寸一致；设置面板、播放/暂停、拖动、键盘焦点及抽屉继续可用。评论与弹幕按钮保留原位置和尺寸，加深关闭与开启状态的底色。原生视频与控件以 libmpv 合成输出截图及像素比较核验，不能用不包含原生 HWND 的浏览器截图代替。HLS 回退使用透明背景和同一隐藏计时。维护者接入宿主计时回调后仍需在目标安装包完成同样验收。

2026-10-12 已在本机最新片库修改基础上完成组合安装验收：原生播放25项、HLS回退16项及8项播放回归通过，4037个安装包文件校验通过。前端逆变换逐字还原片库资源，片库、封面缓存和导航后端哈希保持不变。正常应用已重启。上游正式版是否包含该功能，以维护者合并并发布的版本为准。

同日补测本机请求额度修复：9项鉴权与限流边界测试、114项浏览器组合检查通过。真实安装记录约197秒，媒体就绪后观察180秒，覆盖6个播放会话、自动连播、手动切集、暂停/继续及进度条拖动；6次释放返回204，另发800次本机请求未出现429。测试中的404来自故意不存在的路径和已释放会话，用于确认失败请求也不会耗尽本机额度；无效密钥仍返回401。本次不改布局与原生引擎，上述结果只代表本机验收范围。
