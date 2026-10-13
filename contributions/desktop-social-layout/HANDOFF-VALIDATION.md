# 快速音画交接验证

原生控制栏每 120ms 克隆 DOM、读取样式、SVG/Canvas 栅格化、压缩并上传位图。完整 React 播放器时序中，该工作与 EOF/下一集接管重叠，声音空档约 300ms。组合修复将原生控制与状态调度提前，并在接管及片尾暂缓位图工作。

## 已测范围

2026-10-13，单台 Windows 机器，完整播放器 React 结束 owner/控件和原生桥置于隔离 Edge 宿主；实际 libmpv、默认共享 WASAPI、已就绪的隐藏备用，合成 HEVC/AAC 的 997Hz 与 1499Hz 声音。Windows 回环用约 4ms 窗口判别；不包含物理扬声器或蓝牙链路。对照前后使用同源、同设置与相同测量流程，每个倍速一个记录，不是大样本统计。

| 倍速 | 修改前声音空档 | 组合修复后 |
| --- | ---: | ---: |
| 1x | 291.3ms | 12.0ms |
| 2x | 291.3ms | 39.9ms |
| 3x | 327.2ms | 55.9ms |

这些数字来自本机完整接线实现，不能当成仅合并公开材料后的性能保证。安装程序主界面、启动资源和实际加载 JS 摘要已回读；安装版真实短剧自动续播的最终声音验收未完成。此前局部中心像素采样未出现黑帧，但未连续录制整个画面，不能证明没有短暂冻结、全画面闪黑或声画完全零间隙。音频数字不能直接用于画面。网络、片源、设备和调度变化仍可能产生等待。

没有加入过渡音、交叉淡化、提前结束或跳过片头；旧音频暂停 ACK、首帧、最新控制 revision、设置继承、暂停竞争和取消释放门禁保留。临时 DOM 避让可能露出原 DOM 背景，不将它作为全程透明验收。

## 公开回归

在按 README 依赖顺序拼装的贡献包中运行：

```pwsh
pwsh -NoProfile -Command "python -I contributions/desktop-native-playback/tests/run.py --prefetch-package contributions/desktop-prefetch-cache"
pwsh -NoProfile -Command "python contributions/desktop-seamless-transition/tests/check_patches.py --native-package <未打补丁的最新native包>"
pwsh -NoProfile -Command "node contributions/desktop-social-layout/tests/test_handoff_overlay.cjs"
pwsh -NoProfile -Command "node contributions/desktop-social-layout/tests/test_native_layout.cjs contributions/desktop-native-playback/src/frontend-native.js contributions/desktop-seamless-transition/src/frontend-seamless.js"
pwsh -NoProfile -Command "python contributions/desktop-social-layout/tests/test_overlay_control.py contributions/desktop-native-playback/src/desktop_native.py"
```

源码、补丁应用、语法、合成协议和调度测试与安装版业务验收分别报告。公开材料不含原发行 bundle、EXE、DLL、真实视频、用户资料、本机打包及诊断文件。维护者仍需移入应用源码、接线、复测并发布。
