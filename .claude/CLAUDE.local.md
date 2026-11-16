# MoviePilot-Plugins Fork（TraktCleaner 专用）

本仓库从 `jxxghp/MoviePilot-Plugins` fork，**当前专门用于开发与发布 TraktCleaner 插件**（`plugins.v2/traktcleaner/`）。后续也可能提 PR 回官方插件市场。

## 仓库定位

- **上游**：`jxxghp/MoviePilot-Plugins`（remote `upstream`，只读同步官方更新）
- **fork**：`Guoyin-Wen/MoviePilot-Plugins`（remote `origin`，SSH，日常推送）
- **当前焦点插件**：TraktCleaner（作者 Guoyin-Wen），单文件 `plugins.v2/traktcleaner/__init__.py`

## 详细经验

- 开发要点、oes 调试环境、Trakt API、踩坑清单：详见 [EXPERIENCE.local.md](./EXPERIENCE.local.md)
- `.claude/*.local.md` 含敏感环境信息（token、地址），**不要 `git add`**（保持本地）。

## 完整开发-测试-发布工作流

1. **改代码**：编辑 `plugins.v2/traktcleaner/__init__.py`，顺手改 `plugin_version`。
2. **本地语法校验**：`python3 -m py_compile plugins.v2/traktcleaner/__init__.py`（MP 核心不在本仓库，无法本地 import，只能编译检查）。
3. **单元测试**：用 mock 的 `MetaInfo`/`self.chain` 写测试脚本，在 oes 容器内跑（容器有完整 MP 模块）。见 EXPERIENCE.local.md「oes 调试」。
4. **部署到 oes 试运行**：dev-plugin 热重载（见 EXPERIENCE.local.md），开「试运行模式」跑一次，看通知/数据页确认。
5. **真实数据验证**：直接拿容器内 live token 调 Trakt API 交叉核对（如 progress 过滤后 completed 总和应等于 watched/episodes 总量）。
6. **版本号与一致性校验**：只要 `plugin_version` 变了就走「发版 SOP」（见下），同步 `package.v2.json` 并跑校验脚本。
7. **commit**：代码与索引一起提交；当前以 trakt 插件为主，可直接在 main 上本地 commit（用户偏好），正式发布前再开分支提 PR。
8. **发布**：`gh pr create --repo jxxghp/MoviePilot-Plugins`（PR 前确认 SOP 校验通过）。

## 关键原则（TraktCleaner 专属）

- **Trakt 是唯一事实来源**：以 `/sync/watched/*` 为准，不引入 `/sync/playback` 等第二数据源去覆盖 Trakt 的 watched 判定；不要把"看没看完"甩锅给媒体服务器。
- **fail-safe**：任何信息不足（取不到文件列表、解析不全、无集数详情）时**跳过**而非删除，宁可漏删不可误删。
- **集数权威来源**：`/sync/watched/shows` 常不返回 seasons（疑似接口更新），需按剧回退 `/shows/{id}/progress/watched`，且其 `episodes` 数组含全部已播出集，**必须按 `last_watched_at` 非空过滤**才是真正看过的。

## 发版 SOP：版本号与一致性校验（每次 `plugin_version` 变更必做）

只要改了 `plugin_version`，就必须同步走完这套流程，**缺一步即为未完成**：

1. **同步索引**：编辑 `package.v2.json` 的 `TraktCleaner` 条目
   - `version` 改为与代码 `plugin_version` 完全一致
   - `history` 追加 `"vX.Y": "<本次变更一句话说明>"`
   - `icon` 不动（除非 `plugin_icon` 也改了，须同步）
2. **一致性校验**（在仓库根执行，三项全 ✅ 才算通过）：

```bash
python3 - <<'EOF'
import json, re, os
d=json.load(open('package.v2.json')); e=d['TraktCleaner']
src=open('plugins.v2/traktcleaner/__init__.py').read()
def attr(n):
    m=re.search(rf'{n}\s*=\s*["\']([^"\']+)["\']', src); return m.group(1) if m else None
cv, ci = attr('plugin_version'), attr('plugin_icon')
print('JSON 合法，插件数:', len(d), '-> ✅' if len(d)>0 else '-> ❌')
print('version:', cv, '==', e['version'], '->', '✅' if cv==e['version'] else '❌')
print('icon  :', '✅' if ci==e['icon'] else '❌')
print('目录名小写:', '✅' if os.path.isdir('plugins.v2/traktcleaner') else '❌')
assert cv==e['version'] and ci==e['icon'] and os.path.isdir('plugins.v2/traktcleaner'), '一致性校验失败'
print('全部一致 ✅')
EOF
```

3. **一起提交**：代码与索引同一次 commit（或紧接的 commit），保证二者不脱节。校验脚本的 assert 不通过就别提交。

## 注意事项

- 目录名 = 插件类名小写（`traktcleaner`）。
- `package.v2.json` 的 `version`/`icon` 必须与代码一致。
- 不要硬编码 Client ID/Secret 等敏感信息，一律走配置表单。
- `EXPERIENCE.local.md` 含敏感信息，不提交 git。
