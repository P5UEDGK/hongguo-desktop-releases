# 提前预热与首帧交接

当前集还剩12秒实际播放时间时，创建下一集的隐藏播放器。按倍速和完整时间轴判断，当前集缓冲时优先当前。没有缓存时正常下载；备用未就绪时仍可能等待，不能保证任意网络都无停顿。

这是发行仓库的接入材料，依赖#187、#204和#212；不依赖#205。维护者须移入应用源码、接线并发布，合并本PR不会改变已有发行包。依赖摘要见BASELINES.json。

## 接线

对#204公开的frontend-native.js、frontend-codec.js应用两个补丁，再加入src/frontend-seamless.js。沿用w0、desktopLegacyHls、ek和原callbacks契约，不能直接覆盖发行bundle。BASELINES.json记录LF规范化前后SHA。

React保留preparation引用，在timeupdate/倍速变化后检查desktopShouldPrewarm(media)。连播开启且确有紧邻下一集时解析URL，返回后重查当前集身份，再调用desktopPrepareNext(nextUrl, media, windowed)，每集只创建一次。自动切到该集时，将preparation传给desktopNativePlayback(nextMedia, nextUrl, resolvedResumePosition, callbacks, preparation, windowed)。手动跳其他集、换剧、关闭连播或退出时dispose，忽略旧解析回执。

React在确认本集已结束、开启连播且确有下一集时，在旧控制器dispose之前调用desktopHoldForNext(media)。将返回的holder保存在解析流程的ref中，下一播放器接收已准备的preparation或该holder；取消、换剧和关闭时释放它。最后一集不创建holder，沿用现有结束处理。这样无预热或预热失败后的普通加载也能保留末帧；不固定提前截掉片尾。holder不是准备成功的备用，claimRecord/claim返回null，交由正常加载。

旧控制器dispose通过desktopRetainPicture保留原生会话或HLS最后一帧。遮罩应挂在跨集保留的.player-stage；新控制器确认交接前不要另行删除旧会话。claim后的资源由新控制器负责释放；未claim资源90秒到期清理。

原生预热隐藏、暂停、静音。接管复用已经确认的源和播放模式，不再次协商；首次控制同时包含位置、可见性、播放、倍速和音量，避免显示一张暂停首帧后再等250ms。control及可见/输出/revision ACK共用2秒期限，POST activate成功后释放旧画面并开始ready轮询。取消、超时或失败均释放资源并抑制过期回调。

预热和正式播放共用 desktopNativeSurfaceRect，读取实际 .player-chrome 位置并考虑 DPI；没有控件时回退84px。原生会话注册后、等待首帧前下发隐藏布局，避免把1×1输出当成正式尺寸就绪。模式选择回执不代表原生会话已注册，必须看到有效 revision 后才能提交控制；后续仍等待输出及布局 ACK，不提前显示或跳过片头。

冷启动也等待原生会话注册后再排版，避免模式选择刚返回就发送控制而被拒绝。等待受原准备期限约束；已准备的备用会话直接接管，不增加这次等待。源读取失败与解码失败仍分别处理。

HLS的activate请求、替换会话ID等待及重查共用2秒截止；POST期间copy回退换了ID时激活新ID，确认ID稳定后才清除备用父标记。激活期间记录用户的pause/play意图，不在ACK后无条件恢复播放。activate或play失败只拆除失败备用，旧画面由普通加载的onReady释放；用户取消仍立即释放。冷启动原生确认可见、输出与布局ACK后才释放旧画面。

HLS接管先保留旧帧，activate成功后清除codec控制器的备用父标记并播放新视频，新帧回调后释放旧资源。后续copy→H264回退使用普通前台会话，不再引用已释放的父ID。会话ID随当前transport读取，替换POST未返回时等待新ID；恢复宿主前保存实时倍速、音量和静音。接管失败撤销属性/监听器并转普通加载。

## 控制栏跨集继承

同时载入 src/frontend-controls.js。控制栏组件放在跨集保留的播放器层，不要以集号或片源URL作为控制栏组件的key，也不要在session变化时重设可见状态。沿用宿主现有鼠标、点击、焦点、快捷键和2.5秒自动隐藏计时器，不把隐藏状态写成新的全局偏好。

宿主向控制栏提供实时 isTransitioning 回调，通过既有ref读取“正在解析/选集，或当前媒体尚未就绪”。选集owner必须先写入pending，再暂停和释放旧播放器；控制栏的事件回调ref也同步保存这个getter。媒体状态仍正常同步，仅决定是否需要展开控制栏时使用：

```js
if (desktopControlsShouldReveal(event, media, {
  disabled: controls.current.disabled,
  autoContinue: controls.current.autoContinue,
  hasNext: controls.current.canNext,
  transitioning: controls.current.isTransitioning?.()
})) revealControls();
```

不要仅凭 media.ended 判断自动续播：宿主的结束监听器可能先释放旧控制器，导致该属性恢复false，而控制栏随后才收到同一个ended事件。该策略同时识别事件类型，屏蔽选集/加载内部pause造成的误展开；末集结束和普通用户暂停仍可显示。鼠标、点击和焦点显示入口直接沿用，不经过这个媒体生命周期判断。

```pwsh
node contributions/desktop-seamless-transition/tests/test_controls_visibility.cjs
```

## 中途续播复用

后台仍从0准备下一集，保持隐藏、暂停、静音，播放位置最多0.05秒；可继续下载和缓冲。codec会阻止备用视频的legacy自动play，直到activate明确完成。超过0.05秒的续播目标不再直接丢弃备用：仅在正式claim后，先在隐藏静音暂停状态跳到该位置，再确认目标帧和回执，随后交接。原生校验revision、outputReady、seeking和目标时间；HLS等待目标视频帧或seeked，并校验完整时间轴位置。不会识别或跳过片源黑帧。

定位等待最多2秒，受原90秒备用寿命限制。无效位置、身份不匹配和过期备用不接管；跳转失败则释放备用，保留旧画面到普通兼容加载ready，并按原目标续播。该次原生跳转失败走普通HLS协商，避免立刻再次加载刚失败的原生路径；不永久禁用原生或修改格式支持判断。preparation提供resumePosition、resumeFailed和实时settings供现有桥接使用，取消仍释放所有资源。定位期间新增的用户暂停意图也必须保留。

接入时还须修改两个既有HLS控制器的“初始续播距结尾不足3秒则回零”分支：仅当callbacks.preserveResumePosition不为true时才执行回零。补丁后的codec只对本次备用接管失败留下的明确续播目标设置该标记；其他场景保留原规则。窗口HLS的restart(0)条件与整集HLS计算初始target的回零条件都需增加此判断，例如：

```js
if (!explicitSeek && initialPosition > 0 && initialPosition >= duration - 3 &&
    !callbacks.preserveResumePosition) restart(0);
```

这是现有宿主HLS owner的接线要求，两个bridge补丁不包含宿主控制器源码；漏接会让片尾续播的失败回退重新从头播放。本机融合候选已修改这两处并做真实窗口HLS回退验收。原生补丁同时移除旧的强制控制栏opacity样式，与跨集隐藏策略一致。

## 验证与回滚

```pwsh
pwsh -NoProfile -Command "python -I contributions/desktop-seamless-transition/tests/check_patches.py --native-package <native-contribution-dir>"
```

补丁应用/SHA/语法、原codec/native回归、冷请求、隐藏首帧、设置继承、取消/到期、挂起fetch/JSON、ACK超时、交接首批控制和接管后HLS回退均通过。真实Tauri本机同源1x/2x/3x状态对照中，已显示后仍暂停的额外等待不再出现；EOF到下一集推进约250–485ms，旧版约921–1093ms。计时含隔离CDP转发，仅单机合成输入，不能代替连续像素、实际声画或跨设备性能验收。

用户先前确认长黑屏明显改善，最新反馈多部剧切集仍一闪黑，估计不足100ms。已确认预热的固定84px与安装版实际控件高度不一致；本轮修复该几何差异及排版时机，尚不能据此断言闪黑的完整根因或画面已无空档。最近缓存的5个片头前200ms未检测到近黑画面，但未与用户具体切集绑定。正常片源的连续画面验收仍待完成，不能跳过黑帧掩盖问题。

本轮新增实际控件高度、DPI、无控件回退、原生会话注册门禁及首帧前排版回归。上游接入发布仍需维护者完成。回滚撤销两份补丁、模块与React接线，保留原片及观看记录。[Issue关闭条件](ISSUES.md)，本PR不自动关闭Issue。

用户随后授权安装本轮末帧holder/HLS回执修复。本机主环境14文件SHA核对及安装后回读一致，候选真实Tauri原生32项/HLS21项通过；安装后真实Tauri原生33项/HLS22项，以及无预热保帧原生11项/HLS10项全部通过。覆盖1×/2×/3×自动下一集、设置继承、手动3→1→3实例复用；故意禁用预热并延迟解析800ms时，旧画面保持到下一集就绪，末集不创建下一集holder。关闭后资源槽归零，测试进程已退出，并行功能更新保留。

此前隔离Edge/真实libmpv检查仍保留：预热原生32项/HLS21项、无预热原生10项/HLS9项通过，Node及实际React结束owner回归通过。测试使用自有合成媒体、隔离接口与缓存，功能状态不证明正常短剧连续像素无闪黑或物理音频无空档。上游接入发布、正常片源观感及最新提交复审仍待完成。

本轮控制栏回归：策略18项及完整公开前端回归通过；候选Tauri无预热原生14项/HLS12项、安装后原生Tauri14项通过。后续并行更新保留相同控制栏owner；当前安装资源隔离Edge/HLS11项通过，切集时未展开且opacity为0。覆盖自动切集、显示/隐藏、手动选集、慢解析、暂停、鼠标事件、焦点与末集。当前整包Tauri/HLS因其他运行实例占用未重启验收，不干扰该实例。

修复8720cb7回执：原生激活等待控制队列清空并确认最新revision，提前刷新新增暂停；HLS接管补发准备阶段记录的onAcceptanceHlsTransition及原参数。两个失败回归修改前失败、修改后通过，完整公开Node/补丁及控制栏18项通过；隔离Edge+真实libmpv原生13项、HLS11项通过，资源槽归零。当前软件仍运行，本批只完成候选，未安装；此前进度条继承修复已安装。

本轮中途续播：本轮公开补丁/Node全部通过，新增32个续播边界用例；最新版候选隔离真实媒体原生/HLS续播、失败回退和控制栏共69项通过，关闭后资源槽归零。预热保持暂停静音隐藏，停在开头0.05秒以内；正式切集时再定位该集续播目标，成功复用会话。定位失败保留旧画面及目标，转普通HLS加载；宿主两个末3秒回零分支须接入preserveResumePosition。软件仍运行，未安装本轮候选；候选Tauri、安装后验证及正常片源画面验收待完成。

用户授权安装后，本机核对源/候选/回滚备份与4032个后端清单文件，候选真实Tauri原生/HLS共25项通过后，已安装本轮候选并回读EXE摘要一致。安装后真实Tauri原生/HLS共89项通过，覆盖中段与极短片尾续播、失败普通加载保留目标、0.05秒预热限制、自动/手动切集的控制栏显隐、暂停/鼠标/焦点/末集，关闭后资源槽归零。观看记录、原片和并行功能保留，后端未改动。

原生起播位置在可见/播放控制提交前检查目标帧，晚到的JavaScript进度另行记录，不混作首帧时间。极短片尾可能在首次JS轮询前播放结束；本轮修正验收脚本跨集事件监听并保留早期采样失败报告。测试使用合成媒体及隔离配置，不代表正常短剧连续像素无闪黑或物理音频无空档；正常片源观感和上游接入发布仍待完成。

修复[失败续播设置继承回执](https://github.com/waligoraamodio288-rgb/hongguo-desktop-releases/pull/213#discussion_r4241350344)：preparation提供实时settings，native在失败delegate前先写入目标media，既有delegate/restore据此继承倍速、音量和静音；成功接管复用同一设置来源。差异宿主回归修改前失败、修改后通过，完整公开Node/补丁回归通过；候选真实Tauri故障回退26项、安装后正常接管及故障回退53项通过。实际从界面选择3x、音量0.2、静音，并把新宿主故意重置为默认1x/音量1/未静音，回退后仍继承3x/0.2/静音。本机已重新安装本次修复，EXE/回滚备份及4032个后端文件核对一致，关闭后资源槽归零。前一批89项为e54f安装证据，本批只复测受影响的正常/失败路径，控制栏与其他实现未改动；正常片源观感和上游接入发布仍待完成。

## 剩余审查回归（2026-10-11）

无效或超出完整时长的续播位置归零后再冷加载；有效位置的跳转失败仍按原目标回退。失败准备保留上一集画面到冷加载就绪；暂停HLS交接确认后直接释放旧画面。替换会话ID空窗返回null，不暴露已退役ID。原生表面隐藏或零几何时保持隐藏暂停，等待可显示后再开始2秒可见ACK期限，仍受90秒寿命限制。公开补丁及全部前端回归通过；本批本机候选、安装验证尚待完成。

两份前端补丁及BASELINES已同步#204的d2c86d078695570f0dbd6f9870f3b3bbcd87b8ee。预热直接使用原生包的desktopNativeSurfaceRect，隐藏控制栏不预留84像素；移除重复函数。补丁应用/SHA和全部Node交接、续播、几何回归通过，本批安装验收待完成。

最新三条复审已修复：准备失败仍校验已知时长，未知续播位置不跳过冷加载校验；冷HLS终止错误立即释放保帧；activate返回后在同一2秒期限内排空新控制并核验revision。同步原生基线 6223e50a7f470065f6cbd5d4dc520690c2e8e516，预热也携带当前Tauri物理客户区上下文。40项原生/HLS续播场景和全部前端交接回归通过，三个新缺陷在旧补丁上均失败。本机安装待完成。


## 本轮二次反馈修复

claim 携带原准备 expiresAt；隐藏表面等待与交接沿用这一期限，不重新获得90秒。旧实现的原期限回归失败；修改后的完整前端补丁及原有交接测试通过。


## 本轮三次反馈修复

准备会话的control flush失败后立即停止交接，不再请求null会话状态或重复终止回调；隐藏等待和二次flush也使用相同终止门禁。旧回放失败，当前完整交接与前端补丁测试通过。基础原生同步未知时长/失败续播归零和过期窗口绑定回退，原准备expiry、目标帧、音频意图与ACK要求保持。

本机候选与安装仍待完成。


本轮审查回归（2026-10-12，第四批）：4242245633/5635/5636/4242315880/5881/5887：activate后隐藏状态停泊；文档传实际resume；创建前刷新parent；HLS预热windowed匹配；未知时长resume失败允许冷路径复核；等待claim期间新设置不被旧快照覆盖。

真实M0组合验收发现，未创建父会话的预热占位结果不能接管末帧holder；该结果现在标记 failed。EOF解析前调用 desktopHoldForNext 后，下一播放器必须优先接收其返回值（endHold || preparation），因为它已经选择有效备用或新冷加载holder，不能再被旧失败/空 preparation 覆盖。窗口HLS宿主同时接入原生包的 desktopAcceptWindowOrigin；保留连续origin检查。新增公开回归与真实候选验收正在进行，尚未安装本批。


本轮第六批审查（2026-10-12）：4242530283/0285/0287：windowed不匹配保帧转冷加载，activate失败传最新暂停意图，native显示前隐藏回停泊等待；保留真实M0 holder接线回归。

本轮审查修复：4242708637/8641/8644/8647：unclaimed失败保帧、父替换等待、冷holder继承控制与失败fallback传live seek。

2026-10-12 追加复核：同步native前端入口修复，重放备用桥接且保持既有保帧/ACK控制契约。

`hasNext` 必须由当前剧集和可用下一集计算；不存在下一集或解析失败时传 `false`。只开启自动连播不能压住最终 EOF 的控件。

2026-10-12 第十轮复核：4242853044/3048/3054：activate在途隐藏也暂停；HLS接管前显式seek重放；EOF显隐依赖实际下一集/过渡。

2026-10-12 第十一轮复核：4242904879：未claim备用过期及过期claim仍保留EOF图片，释放备用资源后由cold readiness/error或保帧定时器结束。同步native/codec责任包修复。

2026-10-12 第十二轮复核：4243003130/3133：刷新controls策略摘要并运行公开check_patches；record重放seek更新有效resumePosition供近EOF冷回退使用。

2026-10-12 第十三轮复核：4243056108/6113：claimed准备等待受原deadline/abort约束；公开runner纳入pending/expiry/unclaimed回归；依赖204重新生成native桥接patch。

2026-10-12 第十五轮复核：4243144691：已adopt的HLS终止错误在转交consumer前释放retained picture。

2026-10-12 第十六轮复核：4243201745：claim和seek等待期追踪用户暂停意图。

2026-10-12 第十七轮复核：4243250039/0041：claimed未adopt失败保留前帧；adopt后seek同步更新resumePosition，含currentTime写入。

2026-10-12 第十八轮复核：4243346507/6511/6512：EOF返回preparation即记录hold；native激活前回放并ACKseek；确认delegate已重新同步seek失败后的当前设置并增加回归。

2026-10-12 第十九轮复核：4243425474/5478：URL身份冷降级保留前帧；已激活HLS暂停/ended完成前帧释放；同步直接HLS恢复桥接。

2026-10-12 第二十一轮复核：4243502283/2290/2295：无效进度重置不覆盖claim等待中的新seek；隐藏等待仅提交所需pause修订；续播标记使用已接受的50ms误差。

2026-10-12 第二十二轮复核：4243539029/9033：预热开始即缓存父session ID和stage，后续可用时刷新父ID，异步准备跨越EOF仍可用；同步CSS显隐与续播桥接。

2026-10-12 第二十三轮复核：4243659552/9556：claim返回空时显式seek仍保留近EOF目标；激活等待中的新seek必须落到目标帧后才能释放前帧。

2026-10-12 第二十四轮复核：4243740522：活跃parent accessor返回空时等待替换session，只有teardown accessor消失时使用缓存父ID；同步native补丁。

验证：398项融合后端无跳过、5套评论、28套播放器前端、251项公开备用组合（1项可选片源跳过）、126项暂停补丁（1项可选片源跳过）及88项社交浏览器检查通过。12项冻结前版反例失败、当前通过；候选Tauri原生/HLS播放、CSS隐藏实测及退出释放通过。当前预加载验证器的真实长片检查通过。本机安装验收随后执行，上游尚未合并发布。
