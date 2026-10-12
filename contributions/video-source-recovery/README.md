# 批量取流空响应恢复

批量取视频模型返回 HTTP 200、零字节正文时，原调用链拿不到地址，播放中断。新增共享解析器：仅对该空响应或成功响应缺项，逐集请求单集接口；明确鉴权、风控、429及其它异常直接传播。相同视频的播放、预取和下载入口共享缓存与串行请求，失败的批量路径冷却300秒后再探测。

同时接入上游实际返回的 `backup_url_1` 等编号备用地址。渐进源最多4个候选；传输故障或CDN 403/404/410/5xx可切换，429及协议/内容校验错误不切换。已有字节时要求强ETag和总长度一致，无法确认同一对象则失败，避免混读。仅第一次主链未交付字节时允许无ETag备用源。

这是发行仓库的集成材料，合并PR不会更新已发布安装包。包含自写解析模块、测试及最小接入补丁，不含应用完整源码、签名实现、账号配置、真实媒体、完整签名地址或解密密钥。维护者须在实际应用源码适配、验收并发布。

- `src/desktop_video_resolver.py`：解析、缓存、冷却和候选地址顺序。
- `patches/host-adapters.patch`：既有取流入口及备用字段接线。
- `patches/progressive-backups.patch`：扩展既有 `desktop_stream.py`，不复制第二个读取器。
- [INTEGRATION.md](INTEGRATION.md)：依赖、接口契约、验证与回滚。

## 可复现测试

Python 3.10+。解析器10项测试不联网、无额外依赖：

```powershell
pwsh -NoProfile -Command "python -I contributions/video-source-recovery/tests/run.py"
```

增加备用源7项测试，需要Requests、Git及已有公开原生播放包的 `desktop_stream.py`。测试在临时目录应用补丁，不修改传入文件：

```powershell
pwsh -NoProfile -Command "python -I contributions/video-source-recovery/tests/run.py --stream-base ../desktop-native-playback/contributions/desktop-native-playback/src/desktop_stream.py"
```

本轮验证所用公开依赖来自 XX-Trader/hongguo-desktop-releases 的 `contrib/desktop-native-playback` 提交 `575eaab642bfb1a9edb6b17c072cc14134609195`；输入文件SHA-256为 `b73eac537e583a2564b04adc6fefab48cef20d5228eda3652eab9521fbb6d66e`。已有暂停预加载扩展也可保留；本补丁不改变其reader/cache接口。

## 本机验证

本机组合回归104项：103通过，1项因未指定独立HEVC fixture跳过。另以实际故障集完整解码73.171995秒、2195视频帧和3152音频帧至片尾；下一集取流成功。局部注入主链连接失败后，真实备用链首64KiB与主链相同；三个入口复用解析结果，整个验收只发生1次失败批量请求和2次成功单集请求。此结果不代表所有网络或所有播放故障已解决，也不是正式UI整集播放或物理音频验收。

批量接口为何空响应仍未得到服务端确认，不能把它直接称为封IP或风控。修复不改身份、签名、代理和TLS，不以切换接口绕过明确拒绝。

[失败原因与请求风险研究](FAILURE-RESEARCH.md)记录了证据边界、错误分类与统计缺口，以及已实施和待实施的减少无效请求措施。
