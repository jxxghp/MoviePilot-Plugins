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
const _hoisted_4 = { class: "chip" };
const _hoisted_5 = { class: "lunatv-actions" };
const _hoisted_6 = ["disabled"];
const _hoisted_7 = ["disabled", "aria-label"];
const _hoisted_8 = {
  key: 0,
  class: "alert error"
};
const _hoisted_9 = {
  key: 1,
  class: "alert error"
};
const _hoisted_10 = {
  key: 2,
  class: "alert warning"
};
const _hoisted_11 = { class: "setup-strip" };
const _hoisted_12 = { class: "panel" };
const _hoisted_13 = { class: "section-heading" };
const _hoisted_14 = { class: "section-title" };
const _hoisted_15 = { class: "muted" };
const _hoisted_16 = {
  key: 0,
  class: "empty"
};
const _hoisted_17 = {
  key: 1,
  class: "empty"
};
const _hoisted_18 = {
  key: 2,
  class: "source-table-wrap"
};
const _hoisted_19 = { class: "source-table" };
const _hoisted_20 = { class: "health-status" };
const _hoisted_21 = ["title"];
const _hoisted_22 = { class: "source-name" };
const _hoisted_23 = ["href"];
const _hoisted_24 = {
  key: 1,
  class: "muted"
};
const _hoisted_25 = { class: "source-actions" };
const _hoisted_26 = ["disabled", "aria-label", "onClick"];
const _hoisted_27 = ["disabled", "aria-label", "onClick"];

const {computed,onBeforeUnmount,onMounted,ref} = await importShared('vue');



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
const healthCheckStarting = ref(false);
const busySourceKeys = ref(new Set());
let healthPollTimer = null;
let healthPollDeadline = 0;

const apiCall = (method, path, payload) => {
  if (typeof props.api?.[method] === 'function') return props.api[method](`plugin/${props.pluginId}${path}`, payload)
  return Promise.reject(new Error('MoviePilot API 客户端未注入'))
};

function unwrap(response) {
  const body = response?.data ?? response;
  if (body?.success === false) throw new Error(body.message || '请求失败')
  return body?.data ?? body ?? {}
}

async function load(options = {}) {
  const silent = options?.silent === true;
  if (!silent) {
    loading.value = true;
    error.value = '';
  }
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
    if (!silent) loading.value = false;
  }
}

async function loadHealthStatus() {
  status.value = unwrap(await apiCall('get', '/status'));
}

function clearHealthPoll() {
  if (healthPollTimer) clearTimeout(healthPollTimer);
  healthPollTimer = null;
  healthPollDeadline = 0;
}

function scheduleHealthPoll() {
  if (Date.now() >= healthPollDeadline) {
    healthCheckStarting.value = false;
    error.value = '健康检查仍在后台运行，请稍后刷新状态查看结果';
    clearHealthPoll();
    return
  }
  if (healthPollTimer) clearTimeout(healthPollTimer);
  healthPollTimer = setTimeout(async () => {
    try {
      await loadHealthStatus();
    } catch (pollError) {
      healthCheckStarting.value = false;
      error.value = pollError?.message || '刷新健康检查状态失败';
      clearHealthPoll();
      return
    }
    if (sourceHealth.value.running) scheduleHealthPoll();
    else {
      await load({ silent: true });
      healthCheckStarting.value = false;
      clearHealthPoll();
    }
  }, 2000);
}

async function startHealthCheck() {
  if (healthCheckStarting.value || sourceHealth.value.running) return
  healthCheckStarting.value = true;
  error.value = '';
  try {
    unwrap(await apiCall('post', '/sources/refresh'));
    await loadHealthStatus();
    if (sourceHealth.value.running) {
      healthPollDeadline = Date.now() + 60000;
      scheduleHealthPoll();
    } else {
      healthCheckStarting.value = false;
    }
  } catch (requestError) {
    healthCheckStarting.value = false;
    error.value = requestError?.message || '启动健康检查失败';
  }
}

function sourceIsBusy(source) {
  return busySourceKeys.value.has(source.key)
}

async function setSourceEnabled(source, enabled) {
  if (!source?.key || sourceIsBusy(source)) return
  const nextBusyKeys = new Set(busySourceKeys.value);
  nextBusyKeys.add(source.key);
  busySourceKeys.value = nextBusyKeys;
  error.value = '';
  try {
    const result = unwrap(await apiCall('post', '/sources/state', { source_key: source.key, enabled }));
    await load({ silent: true });
    if (enabled && result?.check_started && sourceHealth.value.running) {
      healthPollDeadline = Date.now() + 60000;
      scheduleHealthPoll();
    }
  } catch (requestError) {
    error.value = requestError?.message || `更新“${source.name || source.key}”状态失败`;
  } finally {
    const remainingBusyKeys = new Set(busySourceKeys.value);
    remainingBusyKeys.delete(source.key);
    busySourceKeys.value = remainingBusyKeys;
  }
}

async function recheckSource(source) {
  if (!source?.key || sourceIsBusy(source) || sourceHealth.value.running) return
  const nextBusyKeys = new Set(busySourceKeys.value);
  nextBusyKeys.add(source.key);
  busySourceKeys.value = nextBusyKeys;
  error.value = '';
  try {
    unwrap(await apiCall('post', '/sources/refresh', { source_key: source.key }));
    await load({ silent: true });
    if (sourceHealth.value.running) {
      healthPollDeadline = Date.now() + 60000;
      scheduleHealthPoll();
    }
  } catch (requestError) {
    error.value = requestError?.message || `重新检查“${source.name || source.key}”失败`;
  } finally {
    const remainingBusyKeys = new Set(busySourceKeys.value);
    remainingBusyKeys.delete(source.key);
    busySourceKeys.value = remainingBusyKeys;
  }
}

const directoryStatus = computed(() => status.value.directories || {});
const downloadSettings = computed(() => status.value.download_settings || {});
const engineStatus = computed(() => status.value.engine || {});
const subscriptionStatus = computed(() => status.value.subscription || {});
const sourceHealth = computed(() => status.value.source_health || {});

function formattedTime(value) {
  if (!value) return '未检查'
  const numeric = Number(value);
  const date = new Date(Number.isFinite(numeric) ? numeric * 1000 : value);
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

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
onBeforeUnmount(clearHealthPoll);

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[0] || (_cache[0] = _createElementVNode("div", null, [
        _createElementVNode("div", { class: "lunatv-eyebrow" }, "THIRD-PARTY CMS / M3U8"),
        _createElementVNode("h1", null, "LunaTV 资源订阅"),
        _createElementVNode("p", null, "接入 MoviePilot 原生搜索、订阅与下载；播放继续交给既有 Emby。")
      ], -1)),
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("span", _hoisted_4, _toDisplayString(downloadSettings.value.max_concurrent_tasks || 2) + " 任务 × " + _toDisplayString(downloadSettings.value.segment_thread_count || 16) + " 分片 ", 1),
        _createElementVNode("span", {
          class: _normalizeClass(['chip', engineStatus.value.ready ? 'ready' : 'muted-chip'])
        }, " N_m3u8DL-RE " + _toDisplayString(engineStatus.value.ready ? '已就绪' : (engineStatus.value.supported ? '内置待安装' : '当前平台不支持')), 3),
        _createElementVNode("span", {
          class: _normalizeClass(['chip', status.value.ai?.available ? 'ready' : 'muted-chip'])
        }, "AI " + _toDisplayString(status.value.ai?.available ? '已就绪' : '未启用'), 3),
        _createElementVNode("span", {
          class: _normalizeClass(['chip', status.value.media_server_sync_running ? 'busy' : 'muted-chip'])
        }, "媒体库 " + _toDisplayString(status.value.media_server_sync_running ? '同步中' : '自动刷新'), 3)
      ]),
      _createElementVNode("div", _hoisted_5, [
        _createElementVNode("button", {
          class: "button secondary",
          disabled: loading.value,
          onClick: load
        }, "刷新状态", 8, _hoisted_6),
        _createElementVNode("button", {
          class: "button",
          disabled: healthCheckStarting.value || sourceHealth.value.running,
          "aria-label": sourceHealth.value.running ? '健康检查进行中' : '立即健康检查所有来源',
          onClick: startHealthCheck
        }, _toDisplayString(healthCheckStarting.value || sourceHealth.value.running ? '健康检查中…' : '立即健康检查'), 9, _hoisted_7)
      ])
    ]),
    (error.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_8, _toDisplayString(error.value), 1))
      : (sourceHealth.value.last_error)
        ? (_openBlock(), _createElementBlock("div", _hoisted_9, " 最近一次健康检查失败：" + _toDisplayString(sourceHealth.value.last_error), 1))
        : _createCommentVNode("", true),
    (status.value.source_config?.error)
      ? (_openBlock(), _createElementBlock("div", _hoisted_10, " 远程来源清单刷新失败，当前使用" + _toDisplayString(status.value.source_config?.origin || '缓存') + "：" + _toDisplayString(status.value.source_config.error), 1))
      : _createCommentVNode("", true),
    _createElementVNode("section", _hoisted_11, [
      _createElementVNode("span", null, "目录：" + _toDisplayString(directoryStatus.value.configured_root || directoryStatus.value.auto_roots?.[0]?.download_path || '未配置'), 1),
      _createElementVNode("span", null, "来源：" + _toDisplayString(directoryStatus.value.source || '未配置'), 1),
      _createElementVNode("span", null, "追更：每 " + _toDisplayString(subscriptionStatus.value.refresh_minutes || 30) + " 分钟检查新集", 1),
      _createElementVNode("span", null, "TMDB：" + _toDisplayString(status.value.tmdb_association ? '自动关联' : '关闭'), 1),
      _cache[1] || (_cache[1] = _createElementVNode("span", null, "缓存：完成后才整理", -1)),
      _createElementVNode("span", null, "来源健康检查：每 " + _toDisplayString(sourceHealth.value.interval_minutes || 60) + " 分钟", 1)
    ]),
    _createElementVNode("section", _hoisted_12, [
      _createElementVNode("div", _hoisted_13, [
        _createElementVNode("div", _hoisted_14, [
          _cache[2] || (_cache[2] = _createTextVNode("资源站 ", -1)),
          _createElementVNode("span", _hoisted_15, _toDisplayString(loading.value ? '…' : sources.value.length), 1)
        ]),
        _cache[3] || (_cache[3] = _createElementVNode("span", { class: "source-caption" }, "打开页面仅读取缓存；搜索仅使用健康且已启用的来源", -1))
      ]),
      (loading.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_16, "正在读取资源站配置…"))
        : (!sources.value.length)
          ? (_openBlock(), _createElementBlock("div", _hoisted_17, "暂未读取到资源站配置"))
          : (_openBlock(), _createElementBlock("div", _hoisted_18, [
              _createElementVNode("table", _hoisted_19, [
                _cache[5] || (_cache[5] = _createElementVNode("thead", null, [
                  _createElementVNode("tr", null, [
                    _createElementVNode("th", { scope: "col" }, "状态"),
                    _createElementVNode("th", { scope: "col" }, "资源名称"),
                    _createElementVNode("th", { scope: "col" }, "网址"),
                    _createElementVNode("th", { scope: "col" }, "搜索功能"),
                    _createElementVNode("th", { scope: "col" }, "最近检查"),
                    _createElementVNode("th", { scope: "col" }, "操作")
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
                          _cache[4] || (_cache[4] = _createElementVNode("i", {
                            class: "state-dot",
                            "aria-hidden": "true"
                          }, null, -1)),
                          _createTextVNode(" " + _toDisplayString(source.status_label || '已加载'), 1)
                        ], 2),
                        _createElementVNode("div", _hoisted_20, [
                          _createElementVNode("span", {
                            class: _normalizeClass(['health-state', `is-${source.health_status || 'unknown'}`])
                          }, _toDisplayString(source.health_label || '未检查'), 3),
                          (source.last_error)
                            ? (_openBlock(), _createElementBlock("span", {
                                key: 0,
                                class: "source-error",
                                title: source.last_error
                              }, _toDisplayString(source.last_error), 9, _hoisted_21))
                            : _createCommentVNode("", true)
                        ])
                      ]),
                      _createElementVNode("td", null, [
                        _createElementVNode("span", _hoisted_22, _toDisplayString(source.name), 1)
                      ]),
                      _createElementVNode("td", null, [
                        (sourceUrl(source))
                          ? (_openBlock(), _createElementBlock("a", {
                              key: 0,
                              class: "source-link",
                              href: sourceUrl(source),
                              target: "_blank",
                              rel: "noopener noreferrer"
                            }, _toDisplayString(sourceHost(source)), 9, _hoisted_23))
                          : (_openBlock(), _createElementBlock("span", _hoisted_24, "—"))
                      ]),
                      _createElementVNode("td", null, [
                        _createElementVNode("span", {
                          class: _normalizeClass(['search-state', `is-${source.search_status || 'supported'}`])
                        }, _toDisplayString(source.search_label || '支持'), 3)
                      ]),
                      _createElementVNode("td", null, _toDisplayString(formattedTime(source.last_checked)), 1),
                      _createElementVNode("td", null, [
                        _createElementVNode("div", _hoisted_25, [
                          _createElementVNode("button", {
                            class: "source-action",
                            disabled: sourceIsBusy(source) || sourceHealth.value.running,
                            "aria-label": `${source.manual_disabled ? '重新启用' : '永久停用'}来源 ${source.name || source.key}`,
                            onClick: $event => (setSourceEnabled(source, source.manual_disabled))
                          }, _toDisplayString(sourceIsBusy(source) ? '处理中…' : (source.manual_disabled ? '重新启用' : '永久停用')), 9, _hoisted_26),
                          (!source.manual_disabled && !source.enabled && source.disabled_reason !== 'configured')
                            ? (_openBlock(), _createElementBlock("button", {
                                key: 0,
                                class: "source-action",
                                disabled: sourceIsBusy(source) || sourceHealth.value.running,
                                "aria-label": `立即复检来源 ${source.name || source.key}`,
                                onClick: $event => (recheckSource(source))
                              }, "立即复检", 8, _hoisted_27))
                            : _createCommentVNode("", true)
                        ])
                      ])
                    ]))
                  }), 128))
                ])
              ])
            ]))
    ]),
    _cache[6] || (_cache[6] = _createStaticVNode("<section class=\"panel help-panel\" data-v-c4328a6e><div class=\"section-title\" data-v-c4328a6e>使用说明</div><div class=\"help-grid\" data-v-c4328a6e><p data-v-c4328a6e><strong data-v-c4328a6e>目录</strong>：目录留空时按媒体类型读取 MoviePilot 的本地目录；填写插件目录则优先使用插件目录。</p><p data-v-c4328a6e><strong data-v-c4328a6e>多季合集</strong>：有明确季号或 TMDB 季集数能完整对应时才会自动分季；无法确认时会暂停，避免错放。</p><p data-v-c4328a6e><strong data-v-c4328a6e>自动追更</strong>：MoviePilot 活跃电视剧订阅会定期重新搜索；已完成和正在下载的集数会跳过，只排队新增集。</p><p data-v-c4328a6e><strong data-v-c4328a6e>媒体库</strong>：目录内没有正在下载的缓存文件后才显示完整文件夹；完成后可请求 Emby/Jellyfin 刷新。</p><p data-v-c4328a6e><strong data-v-c4328a6e>播放</strong>：插件不内置 m3u8 播放器，播放仍由已有 Emby/Jellyfin 页面负责。</p></div></section>", 1))
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-c4328a6e"]]);

export { AppPage as default };
