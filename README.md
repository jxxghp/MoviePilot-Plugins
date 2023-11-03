# MoviePilot-Plugins
MoviePilot官方插件市场：https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/

## 第三方插件库开发说明

- 需要保持与本项目一致的目录结构，`plugins`存放插件代码，一个插件一个子目录，**子目名名必须为插件类名的小写**，插件主类在`__init__.py`中编写。
- `package.json`为插件仓库中所有插件概要信息，用于在MoviePilot的插件市场显示，其中版本号等需与插件代码保持一致，通过修改版本号可触发MoviePilot显示插件更新。
- 插件图标可复用官方插件库中`icons`下已有图标，否则需使用http格式的图片链接（包括package.json中的icon和插件代码中的plugin_icon）。
- 插件命名请勿与官方库插件中的插件冲突，否则会在MoviePilot版本升级时被官方插件覆盖。
- 可在插件目录中放置`requirement.txt`文件，用于指定插件依赖的第三方库，MoviePilot会在插件安装时自动安装依赖库。
- 请不要开发用于破解MoviePilot用户认证、色情、赌博等违法违规内容的插件，共同维护健康的开发环境。