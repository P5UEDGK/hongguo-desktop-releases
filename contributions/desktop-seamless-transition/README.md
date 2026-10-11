# 提前预热与首帧交接

当前集还剩12秒实际播放时间时，创建下一集的隐藏播放器。按倍速和完整时间轴判断，当前集缓冲时优先当前。没有缓存时正常下载；备用未就绪时仍可能等待，不能保证任意网络都无停顿。

这是发行仓库的接入材料，依赖#187、#204和#212；不依赖#205。维护者须移入应用源码、接线并发布，合并本PR不会改变已有发行包。依赖摘要见BASELINES.json。

## 接线

对#204公开的frontend-native.js、frontend-codec.js应用两个补丁，再加入src/frontend-seamless.js。沿用w0、desktopLegacyHls、ek和原callbacks契约，不能直接覆盖发行bundle。BASELINES.json记录LF规范化前后SHA。

React保留preparation引用，在timeupdate/倍速变化后检查desktopShouldPrewarm(media)。连播开启且确有紧邻下一集时解析URL，返回后重查当前集身份，再调用desktopPrepareNext(nextUrl, media)，每集只创建一次。自动切到该集时，将preparation传给desktopNativePlayback(nextMedia, nextUrl, 0, callbacks, preparation)。手动跳其他集、换剧、关闭连播或退出时dispose，忽略旧解析回执。

旧控制器dispose通过desktopRetainPicture保留原生会话或HLS最后一帧。遮罩应挂在跨集保留的.player-stage；新控制器确认交接前不要另行删除旧会话。claim后的资源由新控制器负责释放；未claim资源90秒到期清理。

原生预热隐藏、暂停、静音。接管复用已经确认的源和播放模式，不再次协商；首次控制同时包含位置、可见性、播放、倍速和音量，避免显示一张暂停首帧后再等250ms。control及可见/输出/revision ACK共用2秒期限，POST activate成功后释放旧画面并开始ready轮询。取消、超时或失败均释放资源并抑制过期回调。

HLS接管先保留旧帧，activate成功后清除codec控制器的备用父标记并播放新视频，新帧回调后释放旧资源。后续copy→H264回退使用普通前台会话，不再引用已释放的父ID。会话ID随当前transport读取，替换POST未返回时等待新ID；恢复宿主前保存实时倍速、音量和静音。接管失败撤销属性/监听器并转普通加载。

## 验证与回滚

```pwsh
pwsh -NoProfile -Command "python -I contributions/desktop-seamless-transition/tests/check_patches.py --native-package <native-contribution-dir>"
```

补丁应用/SHA/语法、原codec/native回归、冷请求、隐藏首帧、设置继承、取消/到期、挂起fetch/JSON、ACK超时、交接首批控制和接管后HLS回退均通过。真实Tauri本机同源1x/2x/3x状态对照中，已显示后仍暂停的额外等待不再出现；EOF到下一集推进约250–485ms，旧版约921–1093ms。计时含隔离CDP转发，仅单机合成输入，不能代替连续像素、实际声画或跨设备性能验收。

用户已确认上一批本机安装版黑屏消失，继续反馈短暂停顿；本轮改动针对该停顿。上游接入发布和真实片源观感仍需维护者验收。回滚撤销两份补丁、模块与React接线，保留原片及观看记录。[Issue关闭条件](ISSUES.md)，本PR不自动关闭Issue。
