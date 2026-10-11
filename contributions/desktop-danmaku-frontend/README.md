# 弹幕设置与浏览器连续运动

这是发行仓库的源码接入材料，合并不会改变已发布应用。维护者仍需移入应用源码、完成真实播放器验收并发布。这里只提交新写功能、最小接线和匿名测试，不包含完整应用或安装包。

## 依赖

注入 desktop-comments-frontend 的 read/preference/set 和 desktop-social-emojis；CSS 来自 desktop-social-layout；原生模式还需 desktop-danmaku-backend 补丁。

## 接入与行为

createDanmaku 接收 React、jsxRuntime、read/preference/set 和 emojis。Settings 放在原弹幕开关位置，点击开关、悬停显示设置，无单独齿轮、无发送入口。与评论开关分别保存本机状态，移开延迟250ms收起；不改快捷键。

defaults={opacity:80,lanes:3,fontSize:28,duration:14}。duration 是单条完整滚动时间，滑块向右映射为更短时间/更快。旧版本速度按1.8比例迁移一次，版本标记为2，保留其他偏好。恢复默认、行数、字号、透明度、当前播放附近列表均走同一 owner。

start(media,endpoint,status) 返回清理函数。DOM 回退使用 requestAnimationFrame 和亚像素 translate3d，按媒体时间计算位置；暂停时间不变，seek 取消过期 generation，分页保留已有轨道。原生模式隐藏 DOM 层，通过 desktopdanmaku 事件向原生轨道发送有界日程，不能再用轮询重绘 OSD。只保留附近600条原始数据与最多300条已排轨条目；轨道满时丢弃过密弹幕。

请求返回时以当前视频时间判断新弹幕是否仍可入场，已错过入场时间的条目只留在原始列表，避免突然补到画面中段。分页及设置变更保留在途条目的时间和轨道，迟到项不会因设置调整重新出现。普通 DOM 与原生轨道共用同一份准入日程。rows 的第四个参数仍是视口宽度，可选第五个参数 notBefore 指定新条目的最早入场时间（毫秒）；默认值为 0，原调用方式兼容。

同一集的弹幕按 ID 合并后，再按精确毫秒时间戳与完整原文去重，跨页保留先加载条目的 ID。列表、DOM 与原生轨道共用过滤结果，去重后才应用缓存上限。不同时间的相同内容仍显示，文本在截断前比较，不把长文本尾部差异误判为重复。seek、换集和重新开启后可重新加载显示；普通评论与回复不受影响。

网络错误5秒后重试，退出 abort 请求、取消帧、移除监听和节点，并清空原生日程。宿主更新 native currentTime 时仍需遵守原播放时钟契约；不能用每次轮询替换原生字幕。

## 验证

Python 3.10+、Node 18+；命令以 pwsh 为入口，在包含对应 contributions 的检出根运行。Python API 测试先安装本包 requirements-test.txt。浏览器组合测试需要 Chrome；也可传 --channel msedge。其他模块没有 npm 运行时依赖，React/JSX runtime 由宿主提供。

```pwsh
node contributions/desktop-danmaku-frontend/tests/test_motion.cjs
node contributions/desktop-danmaku-frontend/tests/test_ingress.cjs
```

公开测试为人工构造输入，不连接上游。新导出模块已经独立验证；跨包 Chrome 用例由布局包统一维护。此前本机安装还完成53项窗口功能与21项原生像素检查，快/中/慢档（8/14/24秒）实测为161.25/92.5/53.75物理像素/视频秒；这些属于当时本机接线证据，不是本公开包在所有设备或上游发布后的保证。

回滚时撤回本包接线及新增模块，保留原播放入口、用户偏好和原片，不修改其他播放/缓存贡献。原快捷键不新增、不拦截。Issue 关闭以应用发布并验证为前提，见 [ISSUES.md](ISSUES.md)。

## 首轮审查修复

独立 start 响应开关，关闭清空 DOM 与原生日程；seek 取消旧请求并立即释放 busy。轨道按宽度和共同运动区间两端计算安全间距；设置支持 focus/blur 与 Tab 访问，不注册或修改快捷键。新增挂起请求、开关恢复、160字追尾与焦点回归。

迟到准入回归使用可控的延迟响应，覆盖响应期间视频继续前进、首帧位于右边界、分页位置连续、设置不复活迟到项、seek 过期响应及清理；不连接上游接口。

同一回归还覆盖异 ID 的单页／跨页重复、代表 ID 和在途位置稳定、不同毫秒及完整原文边界、缓存上限、设置与 seek，以及 DOM／原生日程一致。
