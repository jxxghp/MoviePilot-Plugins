# Third-party notices

本项目使用或调用以下第三方组件。组件及其版权仍归各自权利人所有；使用时请遵循对应许可证。本文仅作声明与索引，不复制许可证全文。

## N_m3u8DL-RE

- 项目：[nilaoda/N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE)
- 用途：LunaTV 的 M3U8/VOD 下载与混流。
- 许可证：MIT License，详见上游仓库的 `LICENSE` 文件。

插件随发布包再分发 N_m3u8DL-RE 官方 `v0.5.1-beta` Linux x64/arm64 release 原包，并在 `plugins.v3/lunatvsource/vendor/n_m3u8dl_re/LICENSE` 保留 MIT 许可证全文。安装前会校验固定 SHA-256；内置包缺失时才从同一官方 release 获取。具体版本与校验值以仓库代码为准。

## FFmpeg

- 项目：[FFmpeg](https://ffmpeg.org/)
- 用途：仅作为 N_m3u8DL-RE 的混流依赖。
- 许可证：具体构建可能适用 LGPL 或 GPL；请以所使用构建附带的许可与配置为准，参见 FFmpeg 官方法律说明。

本项目不将 FFmpeg 作为独立的插件下载器或回退下载器发布。第三方组件的许可义务不因本声明而改变。
