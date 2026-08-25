import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createTextVNode:_createTextVNode,renderList:_renderList,Fragment:_Fragment,createStaticVNode:_createStaticVNode} = await importShared('vue');


const _hoisted_1 = { class: "lunatv-page" };
const _hoisted_2 = { class: "lunatv-header" };
const _hoisted_3 = { class: "header-status" };
const _hoisted_4 = { class: "lunatv-actions" };
const _hoisted_5 = ["disabled"];
const _hoisted_6 = {
  key: 0,
  class: "alert error"
};
const _hoisted_7 = { class: "setup-strip" };
const _hoisted_8 = { class: "panel" };
const _hoisted_9 = { class: "section-heading" };
const _hoisted_10 = { class: "section-title" };
const _hoisted_11 = { class: "muted" };
const _hoisted_12 = {
  key: 0,
  class: "empty"
};
const _hoisted_13 = {
  key: 1,
  class: "empty"
};
const _hoisted_14 = {
  key: 2,
  class: "source-table-wrap"
};
const _hoisted_15 = { class: "source-table" };
const _hoisted_16 = { class: "source-name" };
const _hoisted_17 = ["href"];
const _hoisted_18 = {
  key: 1,
  class: "muted"
};

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

const loading = ref(true);
const error = ref('');
const sources = ref([]);
const status = ref({});

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
    const [statusResponse, sourceResponse] = await Promise.all([
      apiCall('get', '/status'),
      apiCall('get', '/sources'),
    ]);
    status.value = unwrap(statusResponse);
    sources.value = unwrap(sourceResponse) || [];
  } catch (loadError) {
    error.value = loadError?.message || '加载 LunaTV 状态失败';
  } finally {
    loading.value = false;
  }
}

const directoryStatus = computed(() => status.value.directories || {});

function sourceUrl(source) {
  const candidate = String(source?.url || source?.detail || source?.api || '').trim();
  if (!candidate) return ''
  try {
    const parsed = new URL(candidate);
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : ''
  } catch {
    return ''
  }
}

function sourceHost(source) {
  const url = sourceUrl(source);
  return url ? new URL(url).hostname : '—'
}

onMounted(load);

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[1] || (_cache[1] = _createElementVNode("div", null, [
        _createElementVNode("div", { class: "lunatv-eyebrow" }, "THIRD-PARTY CMS / M3U8"),
        _createElementVNode("h1", null, "LunaTV 资源订阅"),
        _createElementVNode("p", null, "接入 MoviePilot 原生搜索、订阅与下载；播放继续交给既有 Emby。")
      ], -1)),
      _createElementVNode("div", _hoisted_3, [
        _cache[0] || (_cache[0] = _createElementVNode("span", { class: "chip" }, "串行队列", -1)),
        _createElementVNode("span", {
          class: _normalizeClass(['chip', status.value.ai?.available ? 'ready' : 'muted-chip'])
        }, "AI " + _toDisplayString(status.value.ai?.available ? '已就绪' : '未启用'), 3),
        _createElementVNode("span", {
          class: _normalizeClass(['chip', status.value.media_server_sync_running ? 'busy' : 'muted-chip'])
        }, "媒体库 " + _toDisplayString(status.value.media_server_sync_running ? '同步中' : '自动刷新'), 3)
      ]),
      _createElementVNode("div", _hoisted_4, [
        _createElementVNode("button", {
          class: "button",
          disabled: loading.value,
          onClick: load
        }, "重新加载", 8, _hoisted_5)
      ])
    ]),
    (error.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_6, _toDisplayString(error.value), 1))
      : _createCommentVNode("", true),
    _createElementVNode("section", _hoisted_7, [
      _createElementVNode("span", null, "目录：" + _toDisplayString(directoryStatus.value.configured_root || directoryStatus.value.auto_roots?.[0]?.download_path || '未配置'), 1),
      _createElementVNode("span", null, "来源：" + _toDisplayString(directoryStatus.value.source || '未配置'), 1),
      _createElementVNode("span", null, "TMDB：" + _toDisplayString(status.value.tmdb_association ? '自动关联' : '关闭'), 1),
      _cache[2] || (_cache[2] = _createElementVNode("span", null, "缓存：完成后才整理", -1))
    ]),
    _createElementVNode("section", _hoisted_8, [
      _createElementVNode("div", _hoisted_9, [
        _createElementVNode("div", _hoisted_10, [
          _cache[3] || (_cache[3] = _createTextVNode("资源站 ", -1)),
          _createElementVNode("span", _hoisted_11, _toDisplayString(loading.value ? '…' : sources.value.length), 1)
        ]),
        _cache[4] || (_cache[4] = _createElementVNode("span", { class: "source-caption" }, "依据源配置备注，非实时测速", -1))
      ]),
      (loading.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_12, "正在读取资源站配置…"))
        : (!sources.value.length)
          ? (_openBlock(), _createElementBlock("div", _hoisted_13, "暂未读取到资源站配置"))
          : (_openBlock(), _createElementBlock("div", _hoisted_14, [
              _createElementVNode("table", _hoisted_15, [
                _cache[6] || (_cache[6] = _createElementVNode("thead", null, [
                  _createElementVNode("tr", null, [
                    _createElementVNode("th", { scope: "col" }, "状态"),
                    _createElementVNode("th", { scope: "col" }, "资源名称"),
                    _createElementVNode("th", { scope: "col" }, "网址"),
                    _createElementVNode("th", { scope: "col" }, "搜索功能")
                  ])
                ], -1)),
                _createElementVNode("tbody", null, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(sources.value, (source) => {
                    return (_openBlock(), _createElementBlock("tr", {
                      key: source.key
                    }, [
                      _createElementVNode("td", null, [
                        _createElementVNode("span", {
                          class: _normalizeClass(['source-state', `is-${source.status || 'ready'}`])
                        }, [
                          _cache[5] || (_cache[5] = _createElementVNode("i", {
                            class: "state-dot",
                            "aria-hidden": "true"
                          }, null, -1)),
                          _createTextVNode(" " + _toDisplayString(source.status_label || '已加载'), 1)
                        ], 2)
                      ]),
                      _createElementVNode("td", null, [
                        _createElementVNode("span", _hoisted_16, _toDisplayString(source.name), 1)
                      ]),
                      _createElementVNode("td", null, [
                        (sourceUrl(source))
                          ? (_openBlock(), _createElementBlock("a", {
                              key: 0,
                              class: "source-link",
                              href: sourceUrl(source),
                              target: "_blank",
                              rel: "noopener noreferrer"
                            }, _toDisplayString(sourceHost(source)), 9, _hoisted_17))
                          : (_openBlock(), _createElementBlock("span", _hoisted_18, "—"))
                      ]),
                      _createElementVNode("td", null, [
                        _createElementVNode("span", {
                          class: _normalizeClass(['search-state', `is-${source.search_status || 'supported'}`])
                        }, _toDisplayString(source.search_label || '支持'), 3)
                      ])
                    ]))
                  }), 128))
                ])
              ])
            ]))
    ]),
    _cache[7] || (_cache[7] = _createStaticVNode("<section class=\"panel help-panel\" data-v-2fd7c932><div class=\"section-title\" data-v-2fd7c932>使用说明</div><div class=\"help-grid\" data-v-2fd7c932><p data-v-2fd7c932><strong data-v-2fd7c932>目录</strong>：目录留空时按媒体类型读取 MoviePilot 的本地目录；填写插件目录则优先使用插件目录。</p><p data-v-2fd7c932><strong data-v-2fd7c932>多季合集</strong>：有明确季号或 TMDB 季集数能完整对应时才会自动分季；无法确认时会暂停，避免错放。</p><p data-v-2fd7c932><strong data-v-2fd7c932>媒体库</strong>：目录内没有正在下载的缓存文件后才显示完整文件夹；完成后可请求 Emby/Jellyfin 刷新。</p><p data-v-2fd7c932><strong data-v-2fd7c932>播放</strong>：插件不内置 m3u8 播放器，播放仍由已有 Emby/Jellyfin 页面负责。</p></div></section>", 1))
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-2fd7c932"]]);

export { AppPage as default };
