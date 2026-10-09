# 动漫视频超分

本插件将 [anime-upscale](https://github.com/RWDai/anime-upscale) 的任务队列、GPU 推理和 FFmpeg 流水线直接集成到 MoviePilot。它不连接独立服务；安装插件后，超分任务在 MoviePilot 后端进程中执行。

## 运行要求

- Linux x86_64
- NVIDIA GPU 与可用驱动
- MoviePilot 容器通过 NVIDIA Container Runtime 获得 GPU 访问权限
- 容器内有 `ffmpeg` 和 `ffprobe`，并且 FFmpeg 包含 `hevc_nvenc`
- 插件安装时可访问 PyPI 和 PyTorch CUDA 12.6 wheel 源
- 建议为 MoviePilot 容器配置至少 2 GiB 共享内存
- 当前仅支持标准 `moviepilot-v3` 镜像；`moviepilot-v3t` 所需的 OpenCV 与 Safetensors free-threaded wheel 尚未发布

Docker Compose 至少需要为 MoviePilot 服务增加 GPU 访问，例如：

```yaml
services:
  moviepilot:
    gpus: all
    shm_size: 2gb
    environment:
      NVIDIA_DRIVER_CAPABILITIES: compute,utility,video
```

插件依赖会安装 `torch==2.13.0+cu126`、OpenCV、Spandrel 等推理包。依赖安装在 MoviePilot 的共享 Python 环境，体积较大；升级或重建 MoviePilot 镜像后可能需要重新安装插件依赖。

## 路径

- `输入根目录`：MoviePilot 进程可读取的视频根目录。
- `输出根目录`：超分结果写入目录，必须已存在且 MoviePilot 可写。
- 创建任务时填写的输入与输出路径都是对应根目录内的相对路径，插件拒绝绝对路径和目录越界。
- 输入文件不会被覆盖；已有输出或已登记目标不会重复加入队列。

## 模型

默认模型目录为 MoviePilot 的插件数据目录 `AnimeUpscale/models`，也可以指定持久化目录。支持手动放置模型，或填写可信下载 URL 后手动下载。开启自动下载后，插件启用时会顺序下载配置了 URL 的缺失模型；已有但校验失败的文件不会被自动覆盖。

```text
2x-StarSample-V2-Lite.safetensors
4008dfc72295bb48574a389bf4bd4e55d9af3766f34b6b68cc7bc0c78bd22a0b

AnimeSR_v2.pth
d0f29c8966b53718828bd424bbdc306e7ff0cbf6350beadaf8b5b2500b108548
```

模型下载先写入 `.part` 文件，最大允许 10 GiB，SHA256 匹配后才原子替换正式文件。首次检查已有模型会完整计算摘要，后续在文件大小和修改时间不变时使用缓存。

## 任务与生命周期

- 单个插件实例同一时间只执行一个任务，任务和日志保存在插件数据目录。
- MoviePilot 重启时，原本运行中的任务会标记失败，可以手动重试；排队任务会继续处理。
- 切换模型时释放旧模型显存并加载新模型。
- 停用或重新配置插件会请求取消当前任务，并等待 FFmpeg 与推理流水线退出。
- 输出固定为 2 倍分辨率 MKV，使用所配置 GPU 的 HEVC Main10/NVENC，并尽可能复制源音轨、字幕、附件、章节与元数据；MP4 的 `mov_text` 字幕会转为 Matroska 兼容的 SubRip 字幕。
- 当前版本只支持可识别固定帧率的视频，不覆盖已有输出，也不提供逐帧断点续跑。

AnimeSR v2 网络结构源自 TencentARC/AnimeSR，主体按 Apache-2.0 分发；上游许可证与第三方组件许可汇编见 `LICENSES/AnimeSR-GPL-3.0.txt`（沿用上游文件名）。
