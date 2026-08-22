import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,vModelText:_vModelText,withDirectives:_withDirectives,withModifiers:_withModifiers,renderList:_renderList,Fragment:_Fragment,createTextVNode:_createTextVNode,createStaticVNode:_createStaticVNode} = await importShared('vue');


const _hoisted_1 = { class: "lunatv-page" };
const _hoisted_2 = { class: "lunatv-header" };
const _hoisted_3 = { class: "header-status" };
const _hoisted_4 = { class: "lunatv-actions" };
const _hoisted_5 = ["disabled"];
const _hoisted_6 = ["disabled"];
const _hoisted_7 = {
  key: 0,
  class: "alert error"
};
const _hoisted_8 = {
  key: 1,
  class: "alert success"
};
const _hoisted_9 = { class: "setup-strip" };
const _hoisted_10 = { class: "panel search-panel" };
const _hoisted_11 = ["disabled"];
const _hoisted_12 = {
  key: 2,
  class: "panel"
};
const _hoisted_13 = { class: "result-list" };
const _hoisted_14 = { class: "result-main" };
const _hoisted_15 = { key: 0 };
const _hoisted_16 = {
  key: 0,
  class: "matched"
};
const _hoisted_17 = {
  key: 1,
  class: "muted"
};
const _hoisted_18 = { class: "association-row" };
const _hoisted_19 = ["value", "onChange"];
const _hoisted_20 = ["value"];
const _hoisted_21 = { key: 0 };
const _hoisted_22 = ["disabled", "onClick"];
const _hoisted_23 = {
  key: 2,
  class: "warning-text"
};
const _hoisted_24 = {
  key: 0,
  class: "episode-list"
};
const _hoisted_25 = ["disabled", "title", "onClick"];
const _hoisted_26 = {
  key: 1,
  class: "muted"
};
const _hoisted_27 = { class: "grid" };
const _hoisted_28 = { class: "panel" };
const _hoisted_29 = { class: "section-title" };
const _hoisted_30 = { class: "muted" };
const _hoisted_31 = {
  key: 0,
  class: "empty"
};
const _hoisted_32 = { class: "panel" };
const _hoisted_33 = { class: "section-title" };
const _hoisted_34 = { class: "muted" };
const _hoisted_35 = {
  key: 0,
  class: "empty"
};
const _hoisted_36 = { key: 0 };
const _hoisted_37 = { key: 1 };
const _hoisted_38 = { class: "task-actions" };
const _hoisted_39 = ["onClick"];
const _hoisted_40 = { class: "panel" };
const _hoisted_41 = { class: "section-title" };
const _hoisted_42 = { class: "muted" };
const _hoisted_43 = {
  key: 0,
  class: "empty"
};
const _hoisted_44 = { key: 0 };
const _hoisted_45 = ["title"];

const {computed,onMounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'AppPage',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'LunaTVSource' },
  navKey: { type: String, default: 'main' },
},
  setup(__props) {

const props = __props;

const query = ref('');
const searching = ref(false);
const syncing = ref(false);
const loading = ref(false);
const error = ref('');
const notice = ref('');
const results = ref([]);
const sources = ref([]);
const tasks = ref([]);
const history = ref([]);
const status = ref({});
const selectedCandidates = ref({});
const tmdbSearching = ref({});

const apiCall = (method, path, payload) => {
  if (typeof props.api?.[method] === 'function') return props.api[method](`plugin/${props.pluginId}${path}`, payload)
  return Promise.reject(new Error('MoviePilot API 客户端未注入'))
};

function unwrap(response) {
  const body = response?.data ?? response;
  if (body?.success === false) throw new Error(body.message || '请求失败')
  return body?.data ?? body ?? {}
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const [statusResponse, sourceResponse, taskResponse, historyResponse] = await Promise.all([
      apiCall('get', '/status'),
      apiCall('get', '/sources'),
      apiCall('get', '/tasks'),
      apiCall('get', '/history'),
    ]);
    status.value = unwrap(statusResponse);
    sources.value = unwrap(sourceResponse) || [];
    tasks.value = unwrap(taskResponse) || [];
    history.value = unwrap(historyResponse) || [];
  } catch (loadError) {
    error.value = loadError?.message || '加载 LunaTV 状态失败';
  } finally {
    loading.value = false;
  }
}

async function retry(task) {
  try {
    await apiCall('post', `/tasks/${task.task_id}/retry`);
    notice.value = '失败任务已重新排队';
    await load();
  } catch (retryError) {
    error.value = retryError?.message || '重新排队失败';
  }
}

async function search() {
  if (!query.value.trim() || searching.value) return
  searching.value = true;
  error.value = '';
  notice.value = '';
  try {
    const response = await apiCall('post', '/search', { query: query.value.trim() });
    results.value = unwrap(response) || [];
    notice.value = results.value.length ? `找到 ${results.value.length} 个结果` : '没有找到资源';
  } catch (searchError) {
    error.value = searchError?.message || '搜索失败';
  } finally {
    searching.value = false;
  }
}

async function enqueue(result, episode) {
  error.value = '';
  try {
    const candidate = selectedCandidate(result);
    await apiCall('post', '/download', {
      source_key: result.source_key,
      vod_id: result.vod_id,
      media_id: `${result.source_key}:${result.vod_id}`,
      title: candidate?.title || result.normalized_title || result.title,
      year: candidate?.year || result.year,
      media_type: result.media_type,
      tmdb_id: candidate?.tmdb_id,
      tmdb_media_id: candidate?.media_id,
      episode,
    });
    notice.value = '已加入串行下载队列';
    await load();
  } catch (enqueueError) {
    error.value = enqueueError?.message || '加入下载队列失败';
  }
}

function resultKey(result) {
  return `${result.source_key}:${result.vod_id}`
}

function tmdbCandidates(result) {
  return result.association?.candidates || []
}

function selectedCandidate(result) {
  const candidates = tmdbCandidates(result);
  const selectedId = selectedCandidates.value[resultKey(result)] || result.association?.media_id;
  return candidates.find(candidate => candidate.media_id === selectedId) || null
}

function selectCandidate(result, mediaId) {
  selectedCandidates.value = { ...selectedCandidates.value, [resultKey(result)]: mediaId };
}

async function searchTmdb(result) {
  const key = resultKey(result);
  tmdbSearching.value = { ...tmdbSearching.value, [key]: true };
  try {
    const response = await apiCall('post', '/tmdb/search', {
      title: result.search_title || result.title,
      year: result.year,
      media_type: result.media_type,
    });
    const candidates = unwrap(response) || [];
    result.association = { ...(result.association || {}), candidates };
    const selected = result.association.media_id && candidates.some(item => item.media_id === result.association.media_id)
      ? result.association.media_id
      : candidates[0]?.media_id || '';
    selectCandidate(result, selected);
    notice.value = candidates.length ? `找到 ${candidates.length} 个 TMDB 候选` : '没有找到 TMDB 候选';
  } catch (searchError) {
    error.value = searchError?.message || 'TMDB 搜索失败';
  } finally {
    tmdbSearching.value = { ...tmdbSearching.value, [key]: false };
  }
}

function episodesFor(result) {
  if (!result.season_ambiguous) return result.episodes || []
  const candidate = selectedCandidate(result);
  const counts = candidate?.season_counts || {};
  const seasons = Object.keys(counts).map(Number).filter(season => counts[season] > 0).sort((a, b) => a - b);
  const total = seasons.reduce((sum, season) => sum + Number(counts[season] || 0), 0);
  if (!seasons.length || total !== (result.episodes || []).length) return result.episodes || []
  const mapped = [];
  let offset = 0;
  for (const season of seasons) {
    const count = Number(counts[season]);
    for (let index = 0; index < count; index += 1) {
      mapped.push({ ...(result.episodes[offset + index] || {}), season, episode: index + 1, season_known: true });
    }
    offset += count;
  }
  return mapped
}

function canEnqueue(result) {
  return !result.season_ambiguous || episodesFor(result).every(episode => episode.season_known !== false)
}

async function sync() {
  if (syncing.value) return
  syncing.value = true;
  try {
    const response = await apiCall('post', '/sync');
    notice.value = unwrap(response)?.started === false ? '刷新正在执行' : '已开始刷新订阅';
  } catch (syncError) {
    error.value = syncError?.message || '刷新订阅失败';
  } finally {
    syncing.value = false;
  }
}

const pendingTasks = computed(() => tasks.value.filter(task => task.state === 'pending').length);
const directoryStatus = computed(() => status.value.directories || {});
const stateLabel = (state) => ({ pending: '排队中', running: '下载中', completed: '已完成', failed: '失败' }[state] || state);

onMounted(load);

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[2] || (_cache[2] = _createElementVNode("div", null, [
        _createElementVNode("div", { class: "lunatv-eyebrow" }, "THIRD-PARTY CMS / M3U8"),
        _createElementVNode("h1", null, "LunaTV 资源订阅"),
        _createElementVNode("p", null, "搜索、订阅、串行下载；播放继续交给既有 Emby。")
      ], -1)),
      _createElementVNode("div", _hoisted_3, [
        _cache[1] || (_cache[1] = _createElementVNode("span", { class: "chip" }, "串行队列", -1)),
        _createElementVNode("span", {
          class: _normalizeClass(['chip', status.value.ai?.available ? 'ready' : 'muted-chip'])
        }, "AI " + _toDisplayString(status.value.ai?.available ? '已就绪' : '未启用'), 3),
        _createElementVNode("span", {
          class: _normalizeClass(['chip', status.value.media_server_sync_running ? 'busy' : 'muted-chip'])
        }, "媒体库 " + _toDisplayString(status.value.media_server_sync_running ? '同步中' : '自动刷新'), 3)
      ]),
      _createElementVNode("div", _hoisted_4, [
        _createElementVNode("button", {
          class: "button secondary",
          disabled: syncing.value,
          onClick: sync
        }, _toDisplayString(syncing.value ? '刷新中…' : '刷新订阅'), 9, _hoisted_5),
        _createElementVNode("button", {
          class: "button",
          disabled: loading.value,
          onClick: load
        }, "重新加载", 8, _hoisted_6)
      ])
    ]),
    (error.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_7, _toDisplayString(error.value), 1))
      : _createCommentVNode("", true),
    (notice.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_8, _toDisplayString(notice.value), 1))
      : _createCommentVNode("", true),
    _createElementVNode("section", _hoisted_9, [
      _createElementVNode("span", null, "目录：" + _toDisplayString(directoryStatus.value.configured_root || directoryStatus.value.auto_roots?.[0]?.download_path || '未配置'), 1),
      _createElementVNode("span", null, "来源：" + _toDisplayString(directoryStatus.value.source || '未配置'), 1),
      _createElementVNode("span", null, "TMDB：" + _toDisplayString(status.value.tmdb_association ? '自动关联' : '关闭'), 1),
      _cache[3] || (_cache[3] = _createElementVNode("span", null, "缓存：完成后才整理", -1))
    ]),
    _createElementVNode("section", _hoisted_10, [
      _cache[4] || (_cache[4] = _createElementVNode("div", { class: "section-title" }, "资源搜索", -1)),
      _createElementVNode("form", {
        class: "search-row",
        onSubmit: _withModifiers(search, ["prevent"])
      }, [
        _withDirectives(_createElementVNode("input", {
          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((query).value = $event)),
          placeholder: "搜索电影或剧集",
          "aria-label": "搜索电影或剧集"
        }, null, 512), [
          [_vModelText, query.value]
        ]),
        _createElementVNode("button", {
          class: "button",
          disabled: searching.value
        }, _toDisplayString(searching.value ? '搜索中…' : '搜索'), 9, _hoisted_11)
      ], 32)
    ]),
    (results.value.length)
      ? (_openBlock(), _createElementBlock("section", _hoisted_12, [
          _cache[5] || (_cache[5] = _createElementVNode("div", { class: "section-title" }, "搜索结果", -1)),
          _createElementVNode("div", _hoisted_13, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(results.value, (result) => {
              return (_openBlock(), _createElementBlock("article", {
                key: `${result.source_key}:${result.vod_id}`,
                class: "result-card"
              }, [
                _createElementVNode("div", _hoisted_14, [
                  _createElementVNode("strong", null, [
                    _createTextVNode(_toDisplayString(result.title), 1),
                    (result.year)
                      ? (_openBlock(), _createElementBlock("span", _hoisted_15, " (" + _toDisplayString(result.year) + ")", 1))
                      : _createCommentVNode("", true)
                  ]),
                  _createElementVNode("small", null, _toDisplayString(result.source_name) + " · " + _toDisplayString(result.media_type === 'tv' ? '电视剧' : '电影'), 1),
                  (result.association?.status === 'matched')
                    ? (_openBlock(), _createElementBlock("small", _hoisted_16, "已关联 TMDB：" + _toDisplayString(result.association.title || result.association.media_id), 1))
                    : (result.association?.status === 'unmatched')
                      ? (_openBlock(), _createElementBlock("small", _hoisted_17, "未匹配 TMDB，将按原始名称处理"))
                      : _createCommentVNode("", true),
                  _createElementVNode("div", _hoisted_18, [
                    (tmdbCandidates(result).length)
                      ? (_openBlock(), _createElementBlock("select", {
                          key: 0,
                          value: selectedCandidates.value[resultKey(result)] || result.association?.media_id || tmdbCandidates(result)[0]?.media_id,
                          "aria-label": "选择匹配的 TMDB 作品",
                          onChange: $event => (selectCandidate(result, $event.target.value))
                        }, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(tmdbCandidates(result), (candidate) => {
                            return (_openBlock(), _createElementBlock("option", {
                              key: candidate.media_id,
                              value: candidate.media_id
                            }, [
                              _createTextVNode(_toDisplayString(candidate.title || candidate.media_id), 1),
                              (candidate.year)
                                ? (_openBlock(), _createElementBlock("span", _hoisted_21, " (" + _toDisplayString(candidate.year) + ")", 1))
                                : _createCommentVNode("", true)
                            ], 8, _hoisted_20))
                          }), 128))
                        ], 40, _hoisted_19))
                      : _createCommentVNode("", true),
                    _createElementVNode("button", {
                      class: "link-button",
                      disabled: tmdbSearching.value[resultKey(result)],
                      onClick: $event => (searchTmdb(result))
                    }, _toDisplayString(tmdbSearching.value[resultKey(result)] ? '搜索中…' : '重新搜索 TMDB'), 9, _hoisted_22)
                  ]),
                  (result.season_ambiguous)
                    ? (_openBlock(), _createElementBlock("small", _hoisted_23, "检测到 " + _toDisplayString(result.season_range?.[0]) + "-" + _toDisplayString(result.season_range?.[1]) + " 季，但源地址没有季边界，暂不自动下载", 1))
                    : _createCommentVNode("", true)
                ]),
                (episodesFor(result).length)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_24, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(episodesFor(result), (episode) => {
                        return (_openBlock(), _createElementBlock("button", {
                          key: `${episode.season}-${episode.episode}-${episode.url}`,
                          class: "episode-button",
                          disabled: !canEnqueue(result),
                          title: !canEnqueue(result) ? '请先选择能确定季边界的 TMDB 作品' : '加入串行队列',
                          onClick: $event => (enqueue(result, episode))
                        }, _toDisplayString(result.media_type === 'tv' ? `S${String(episode.season).padStart(2, '0')}E${String(episode.episode).padStart(2, '0')}` : '下载'), 9, _hoisted_25))
                      }), 128))
                    ]))
                  : (_openBlock(), _createElementBlock("small", _hoisted_26, "该结果没有可用播放地址"))
              ]))
            }), 128))
          ])
        ]))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_27, [
      _createElementVNode("section", _hoisted_28, [
        _createElementVNode("div", _hoisted_29, [
          _cache[6] || (_cache[6] = _createTextVNode("资源站 ", -1)),
          _createElementVNode("span", _hoisted_30, _toDisplayString(sources.value.length), 1)
        ]),
        (!sources.value.length)
          ? (_openBlock(), _createElementBlock("div", _hoisted_31, "暂未读取到资源站配置"))
          : _createCommentVNode("", true),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(sources.value, (source) => {
          return (_openBlock(), _createElementBlock("div", {
            key: source.key,
            class: "source-row"
          }, [
            _createElementVNode("span", null, _toDisplayString(source.name), 1),
            _createElementVNode("small", null, _toDisplayString(source.key), 1)
          ]))
        }), 128))
      ]),
      _createElementVNode("section", _hoisted_32, [
        _createElementVNode("div", _hoisted_33, [
          _cache[7] || (_cache[7] = _createTextVNode("下载队列 ", -1)),
          _createElementVNode("span", _hoisted_34, "待处理 " + _toDisplayString(pendingTasks.value), 1)
        ]),
        (!tasks.value.length)
          ? (_openBlock(), _createElementBlock("div", _hoisted_35, "暂无任务"))
          : _createCommentVNode("", true),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(tasks.value.slice(0, 12), (task) => {
          return (_openBlock(), _createElementBlock("div", {
            key: task.task_id,
            class: "task-row"
          }, [
            _createElementVNode("div", null, [
              _createElementVNode("strong", null, _toDisplayString(task.title), 1),
              (task.media_type === 'tv')
                ? (_openBlock(), _createElementBlock("small", _hoisted_36, "S" + _toDisplayString(String(task.season).padStart(2, '0')) + "E" + _toDisplayString(String(task.episode).padStart(2, '0')), 1))
                : (_openBlock(), _createElementBlock("small", _hoisted_37, "电影"))
            ]),
            _createElementVNode("div", _hoisted_38, [
              _createElementVNode("span", {
                class: _normalizeClass(['status', task.state])
              }, _toDisplayString(stateLabel(task.state)), 3),
              (task.state === 'failed')
                ? (_openBlock(), _createElementBlock("button", {
                    key: 0,
                    class: "link-button",
                    onClick: $event => (retry(task))
                  }, "重试", 8, _hoisted_39))
                : _createCommentVNode("", true)
            ])
          ]))
        }), 128))
      ])
    ]),
    _createElementVNode("section", _hoisted_40, [
      _createElementVNode("div", _hoisted_41, [
        _cache[8] || (_cache[8] = _createTextVNode("整理历史 ", -1)),
        _createElementVNode("span", _hoisted_42, "最近 " + _toDisplayString(Math.min(history.value.length, 12)) + " 条", 1)
      ]),
      (!history.value.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_43, "暂无已完成记录"))
        : _createCommentVNode("", true),
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(history.value.slice(0, 12), (item) => {
        return (_openBlock(), _createElementBlock("div", {
          key: item.task_id,
          class: "task-row"
        }, [
          _createElementVNode("div", null, [
            _createElementVNode("strong", null, _toDisplayString(item.title), 1),
            _createElementVNode("small", null, [
              _createTextVNode(_toDisplayString(item.mode === 'strm' ? 'STRM' : '本地下载'), 1),
              (item.media_type === 'tv')
                ? (_openBlock(), _createElementBlock("span", _hoisted_44, " · S" + _toDisplayString(String(item.season).padStart(2, '0')) + "E" + _toDisplayString(String(item.episode).padStart(2, '0')), 1))
                : _createCommentVNode("", true)
            ])
          ]),
          _createElementVNode("small", {
            class: "history-output",
            title: item.output
          }, _toDisplayString(item.output), 9, _hoisted_45)
        ]))
      }), 128))
    ]),
    _cache[9] || (_cache[9] = _createStaticVNode("<section class=\"panel help-panel\" data-v-7bce8add><div class=\"section-title\" data-v-7bce8add>使用说明</div><div class=\"help-grid\" data-v-7bce8add><p data-v-7bce8add><strong data-v-7bce8add>目录</strong>：目录留空时按媒体类型读取 MoviePilot 的本地目录；填写插件目录则优先使用插件目录。</p><p data-v-7bce8add><strong data-v-7bce8add>多季合集</strong>：有明确季号或 TMDB 季集数能完整对应时才会自动分季；无法确认时会暂停，避免错放。</p><p data-v-7bce8add><strong data-v-7bce8add>媒体库</strong>：目录内没有正在下载的缓存文件后才显示完整文件夹；完成后可请求 Emby/Jellyfin 刷新。</p><p data-v-7bce8add><strong data-v-7bce8add>播放</strong>：插件不内置 m3u8 播放器，播放仍由已有 Emby/Jellyfin 页面负责。</p></div></section>", 1))
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-7bce8add"]]);

export { AppPage as default };
