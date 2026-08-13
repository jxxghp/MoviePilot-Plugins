# 动漫视频超分

本插件将 MoviePilot 接入 [anime-upscale](https://github.com/RWDai/anime-upscale) GPU 服务，提供服务状态、模型管理和视频超分任务操作。

## 部署要求

1. 按 anime-upscale 项目说明部署 GPU 服务。
2. 将同一个宿主机模型目录同时挂载到 MoviePilot 容器和 anime-upscale 容器的 `/models`。
3. 在插件配置中填写 MoviePilot 容器内看到的模型目录，以及 anime-upscale 服务地址。

例如宿主目录为 `/mnt/appdata/anime-upscale/models`：

```yaml
services:
  moviepilot:
    volumes:
      - /mnt/appdata/anime-upscale/models:/anime-upscale-models
  anime-upscale:
    volumes:
      - /mnt/appdata/anime-upscale/models:/models:ro
```

插件的“共享模型目录”应填写 `/anime-upscale-models`。anime-upscale 服务仍使用默认的 `/models`。

## 模型

可以手动将模型放入共享目录，也可以在配置中填写模型下载 URL 后从插件详情页发起下载。启用“自动下载缺失模型”后，插件会在启用或重新加载配置时顺序下载已配置 URL 的缺失模型；已有但校验失败的文件不会被自动覆盖。插件不内置第三方镜像地址；所有模型无论来自手动放置还是自动下载，都会按下列 SHA256 校验：

```text
2x-StarSample-V2-Lite.safetensors
4008dfc72295bb48574a389bf4bd4e55d9af3766f34b6b68cc7bc0c78bd22a0b

AnimeSR_v2.pth
d0f29c8966b53718828bd424bbdc306e7ff0cbf6350beadaf8b5b2500b108548
```

下载先写入隐藏的 `.part` 文件，校验通过后再原子替换正式文件。单个下载最大允许 10 GiB，同时只执行一个下载任务。
详情页首次读取已有的大模型时会执行完整 SHA256 校验，可能需要等待一段时间；只要文件大小和修改时间不变，后续会使用缓存结果。

## 任务

插件配置页可保存默认输入路径、输出子目录、模型、CQ 和递归选项，详情页的“提交默认任务”会把这些参数发送给 anime-upscale。路径均按 anime-upscale 容器内的挂载视角解释：输入路径相对于其 `MEDIA_ROOT`，输出路径相对于其 `OUTPUT_ROOT`。

插件 API 也支持创建、查询、取消和重试任务，适合后续接入 MoviePilot 工作流。anime-upscale 当前没有身份验证，仅应部署在可信 Docker 网络或局域网中，不应直接暴露到公网。
