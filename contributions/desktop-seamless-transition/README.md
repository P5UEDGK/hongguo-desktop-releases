# 提前预热与首帧交接

当前集还剩12秒实际播放时间时，创建下一集的隐藏播放器。按倍速和完整时间轴判断，当前集缓冲时优先当前。没有缓存时正常下载；备用未就绪时仍可能等待，不能保证任意网络都无停顿。

这是发行仓库的接入材料，依赖#187、#204和#212；不依赖#205。维护者须移入应用源码、接线并发布，合并本PR不会改变已有发行包。依赖摘要见BASELINES.json。

## 接线

对#204公开的frontend-native.js、frontend-codec.js应用两个补丁，再加入src/frontend-seamless.js。沿用w0、desktopLegacyHls、ek和原callbacks契约，不能直接覆盖发行bundle。BASELINES.json记录LF规范化前后SHA。

React保留preparation引用，在timeupdate/倍速变化后检查desktopShouldPrewarm(media)。连播开启且确有紧邻下一集时解析URL，返回后重查当前集身份，再调用desktopPrepareNext(nextUrl, media)，每集只创建一次。自动切到该集时，将preparation传给desktopNativePlayback(nextMedia, nextUrl, 0, callbacks, preparation)。手动跳其他集、换剧、关闭连播或退出时dispose，忽略旧解析回执。

React在确认本集已结束、开启连播且确有下一集时，在旧控制器dispose之前调用desktopHoldForNext(media)。将返回的holder保存在解析流程的ref中，下一播放器接收已准备的preparation或该holder；取消、换剧和关闭时释放它。最后一集不创建holder，沿用现有结束处理。这样无预热或预热失败后的普通加载也能保留末帧；不固定提前截掉片尾。holder不是准备成功的备用，claimRecord/claim返回null，交由正常加载。

旧控制器dispose通过desktopRetainPicture保留原生会话或HLS最后一帧。遮罩应挂在跨集保留的.player-stage；新控制器确认交接前不要另行删除旧会话。claim后的资源由新控制器负责释放；未claim资源90秒到期清理。

原生预热隐藏、暂停、静音。接管复用已经确认的源和播放模式，不再次协商；首次控制同时包含位置、可见性、播放、倍速和音量，避免显示一张暂停首帧后再等250ms。control及可见/输出/revision ACK共用2秒期限，POST activate成功后释放旧画面并开始ready轮询。取消、超时或失败均释放资源并抑制过期回调。

预热和正式播放共用 desktopNativeSurfaceRect，读取实际 .player-chrome 位置并考虑 DPI；没有控件时回退84px。原生会话注册后、等待首帧前下发隐藏布局，避免把1×1输出当成正式尺寸就绪。模式选择回执不代表原生会话已注册，必须看到有效 revision 后才能提交控制；后续仍等待输出及布局 ACK，不提前显示或跳过片头。

冷启动也等待原生会话注册后再排版，避免模式选择刚返回就发送控制而被拒绝。等待受原准备期限约束；已准备的备用会话直接接管，不增加这次等待。源读取失败与解码失败仍分别处理。

HLS的activate请求、替换会话ID等待及重查共用2秒截止；POST期间copy回退换了ID时激活新ID，确认ID稳定后才清除备用父标记。激活期间记录用户的pause/play意图，不在ACK后无条件恢复播放。activate或play失败只拆除失败备用，旧画面由普通加载的onReady释放；用户取消仍立即释放。冷启动原生确认可见、输出与布局ACK后才释放旧画面。

HLS接管先保留旧帧，activate成功后清除codec控制器的备用父标记并播放新视频，新帧回调后释放旧资源。后续copy→H264回退使用普通前台会话，不再引用已释放的父ID。会话ID随当前transport读取，替换POST未返回时等待新ID；恢复宿主前保存实时倍速、音量和静音。接管失败撤销属性/监听器并转普通加载。

## 验证与回滚

```pwsh
pwsh -NoProfile -Command "python -I contributions/desktop-seamless-transition/tests/check_patches.py --native-package <native-contribution-dir>"
```

补丁应用/SHA/语法、原codec/native回归、冷请求、隐藏首帧、设置继承、取消/到期、挂起fetch/JSON、ACK超时、交接首批控制和接管后HLS回退均通过。真实Tauri本机同源1x/2x/3x状态对照中，已显示后仍暂停的额外等待不再出现；EOF到下一集推进约250–485ms，旧版约921–1093ms。计时含隔离CDP转发，仅单机合成输入，不能代替连续像素、实际声画或跨设备性能验收。

用户先前确认长黑屏明显改善，最新反馈多部剧切集仍一闪黑，估计不足100ms。已确认预热的固定84px与安装版实际控件高度不一致；本轮修复该几何差异及排版时机，尚不能据此断言闪黑的完整根因或画面已无空档。最近缓存的5个片头前200ms未检测到近黑画面，但未与用户具体切集绑定。正常片源的连续画面验收仍待完成，不能跳过黑帧掩盖问题。

本轮新增实际控件高度、DPI、无控件回退、原生会话注册门禁及首帧前排版回归。上游接入发布仍需维护者完成。回滚撤销两份补丁、模块与React接线，保留原片及观看记录。[Issue关闭条件](ISSUES.md)，本PR不自动关闭Issue。

用户随后授权安装本轮末帧holder/HLS回执修复。本机主环境14文件SHA核对及安装后回读一致，候选真实Tauri原生32项/HLS21项通过；安装后真实Tauri原生33项/HLS22项，以及无预热保帧原生11项/HLS10项全部通过。覆盖1×/2×/3×自动下一集、设置继承、手动3→1→3实例复用；故意禁用预热并延迟解析800ms时，旧画面保持到下一集就绪，末集不创建下一集holder。关闭后资源槽归零，测试进程已退出，并行功能更新保留。

此前隔离Edge/真实libmpv检查仍保留：预热原生32项/HLS21项、无预热原生10项/HLS9项通过，Node及实际React结束owner回归通过。测试使用自有合成媒体、隔离接口与缓存，功能状态不证明正常短剧连续像素无闪黑或物理音频无空档。上游接入发布、正常片源观感及最新提交复审仍待完成。
