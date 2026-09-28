import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createTextVNode:_createTextVNode,normalizeStyle:_normalizeStyle,renderList:_renderList,Fragment:_Fragment,createStaticVNode:_createStaticVNode} = await importShared('vue');


const _hoisted_1 = { class: "lunatv-page" };
const _hoisted_2 = { class: "lunatv-header" };
const _hoisted_3 = { class: "header-status" };
const _hoisted_4 = { class: "chip" };
const _hoisted_5 = { class: "lunatv-actions" };
const _hoisted_6 = ["disabled"];
const _hoisted_7 = ["disabled", "aria-label"];
const _hoisted_8 = {
  key: 0,
  class: "source-caption"
};
const _hoisted_9 = {
  key: 0,
  class: "alert error"
};
const _hoisted_10 = {
  key: 1,
  class: "alert error"
};
const _hoisted_11 = {
  key: 2,
  class: "alert warning"
};
const _hoisted_12 = {
  key: 3,
  class: "alert warning"
};
const _hoisted_13 = {
  key: 4,
  class: "alert warning"
};
const _hoisted_14 = { class: "setup-strip" };
const _hoisted_15 = { class: "panel" };
const _hoisted_16 = { class: "section-heading" };
const _hoisted_17 = { class: "section-title" };
const _hoisted_18 = { class: "muted" };
const _hoisted_19 = { class: "health-progress-block" };
const _hoisted_20 = { class: "health-progress-heading" };
const _hoisted_21 = { class: "health-progress-title" };
const _hoisted_22 = { class: "health-progress-count" };
const _hoisted_23 = ["aria-label", "aria-valuenow"];
const _hoisted_24 = {
  key: 1,
  class: "empty"
};
const _hoisted_25 = {
  key: 2,
  class: "empty"
};
const _hoisted_26 = {
  key: 3,
  class: "source-table-wrap"
};
const _hoisted_27 = { class: "source-table" };
const _hoisted_28 = { class: "health-status" };
const _hoisted_29 = { class: "network-metrics" };
const _hoisted_30 = ["title"];
const _hoisted_31 = { class: "source-identity" };
const _hoisted_32 = { class: "source-name" };
const _hoisted_33 = { class: "source-key" };
const _hoisted_34 = ["href"];
const _hoisted_35 = {
  key: 1,
  class: "muted"
};
const _hoisted_36 = { class: "source-actions" };
const _hoisted_37 = ["value", "disabled", "aria-label", "onChange"];
const _hoisted_38 = ["disabled", "aria-label", "onClick"];

const {computed,onBeforeUnmount,onMounted,ref} = await importShared('vue');


const HEALTH_POLL_INTERVAL_MS = 1000;
const HEALTH_POLL_TIMEOUT_MS = 5 * 60 * 1000;


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
  const [statusResponse, sourceResponse] = await Promise.all([
    apiCall('get', '/status'),
    apiCall('get', '/sources'),
  ]);
  status.value = unwrap(statusResponse);
  sources.value = unwrap(sourceResponse) || [];
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
  }, HEALTH_POLL_INTERVAL_MS);
}

async function startHealthCheck() {
  if (healthCheckStarting.value || sourceHealth.value.running) return
  healthCheckStarting.value = true;
  error.value = '';
  try {
    unwrap(await apiCall('post', '/sources/refresh'));
    await loadHealthStatus();
    if (sourceHealth.value.running) {
      healthPollDeadline = Date.now() + HEALTH_POLL_TIMEOUT_MS;
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
      healthPollDeadline = Date.now() + HEALTH_POLL_TIMEOUT_MS;
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

function setSourceConfig(source, event) {
  const value = event?.target?.value;
  setSourceEnabled(source, value === 'enabled');
}

async function recheckSource(source) {
  if (!source?.key || sourceIsBusy(source)) return
  const nextBusyKeys = new Set(busySourceKeys.value);
  nextBusyKeys.add(source.key);
  busySourceKeys.value = nextBusyKeys;
  error.value = '';
  try {
    unwrap(await apiCall('post', '/sources/refresh', { source_key: source.key }));
    await load({ silent: true });
    if (sourceHealth.value.running) {
      healthPollDeadline = Date.now() + HEALTH_POLL_TIMEOUT_MS;
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
const healthChecked = computed(() => Math.max(0, Number(sourceHealth.value.checked || 0)));
const healthCheckTotal = computed(() => Math.max(0, Number(sourceHealth.value.check_total || 0)));
const healthProgress = computed(() => {
  if (!healthCheckTotal.value) return 0
  return Math.min(100, Math.round((healthChecked.value / healthCheckTotal.value) * 100))
});
const healthProgressLabel = computed(() => {
  if (sourceHealth.value.running && !healthCheckTotal.value) return '正在读取来源清单…'
  if (!healthCheckTotal.value) return '尚未开始健康检查'
  return `${sourceHealth.value.running ? '本轮进度' : '最近一轮'} ${healthChecked.value} / ${healthCheckTotal.value}`
});
const queueStatus = computed(() => status.value.queue || {});
const queueTotal = computed(() => ['pending', 'running', 'paused']
  .reduce((total, state) => total + Number(queueStatus.value[state] || 0), 0));
const followupStatus = computed(() => status.value.followup_status || {});
const subscriptionRefreshStatus = computed(() => followupStatus.value.subscription_refresh || {});
const mediaSyncStatus = computed(() => followupStatus.value.media_server_sync || {});

function followupSummary(item) {
  if (item?.running) return '进行中'
  if (!item?.finished_at) return '暂无记录'
  return `${item.success === false ? '失败' : '成功'} · ${formattedTime(item.finished_at)}`
}

function sourceVisualStatus(source) {
  if (
    source?.manual_disabled
    || source?.disabled_reason === 'configured'
    || ['pending', 'unchecked'].includes(source?.health_status)
  ) return 'muted'
  return source?.status || 'ready'
}

function sourceSearchVisualStatus(source) {
  if (
    source?.manual_disabled
    || source?.disabled_reason === 'configured'
    || ['pending', 'unchecked'].includes(source?.health_status)
  ) return 'muted'
  return source?.search_status || 'supported'
}

function sourceHealthVisualStatus(source) {
  if (
    source?.manual_disabled
    || source?.disabled_reason === 'configured'
    || ['pending', 'unchecked'].includes(source?.health_status)
  ) return 'muted'
  return source?.health_status || 'unknown'
}

function sourceCheckedLabel(source) {
  return source?.check_state === 'pending' ? '等待本轮检查' : formattedTime(source?.last_checked)
}

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
        _createElementVNode("span", _hoisted_4, " 并发上限：" + _toDisplayString(downloadSettings.value.max_concurrent_tasks || 2) + " 任务 × " + _toDisplayString(downloadSettings.value.segment_thread_count || 16) + " 分片 ", 1),
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
          disabled: status.value.enabled !== true || healthCheckStarting.value || sourceHealth.value.running,
          "aria-label": status.value.enabled !== true ? '请先启用插件' : (sourceHealth.value.running ? '健康检查进行中' : '立即健康检查所有来源'),
          onClick: startHealthCheck
        }, _toDisplayString(healthCheckStarting.value || sourceHealth.value.running ? '健康检查中…' : '立即健康检查'), 9, _hoisted_7),
        (status.value.enabled === false)
          ? (_openBlock(), _createElementBlock("span", _hoisted_8, "请先启用插件后进行健康检查"))
          : _createCommentVNode("", true)
      ])
    ]),
    (error.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_9, _toDisplayString(error.value), 1))
      : (sourceHealth.value.last_error)
        ? (_openBlock(), _createElementBlock("div", _hoisted_10, " 最近一次健康检查失败：" + _toDisplayString(sourceHealth.value.last_error), 1))
        : _createCommentVNode("", true),
    (status.value.source_config?.error)
      ? (_openBlock(), _createElementBlock("div", _hoisted_11, " 远程来源清单刷新失败，当前使用" + _toDisplayString(status.value.source_config?.origin || '缓存') + "：" + _toDisplayString(status.value.source_config.error), 1))
      : _createCommentVNode("", true),
    (subscriptionRefreshStatus.value.error)
      ? (_openBlock(), _createElementBlock("div", _hoisted_12, " 最近一次追更失败：" + _toDisplayString(subscriptionRefreshStatus.value.error), 1))
      : _createCommentVNode("", true),
    (mediaSyncStatus.value.error)
      ? (_openBlock(), _createElementBlock("div", _hoisted_13, " 最近一次媒体库或订阅进度同步失败：" + _toDisplayString(mediaSyncStatus.value.error), 1))
      : _createCommentVNode("", true),
    _createElementVNode("section", _hoisted_14, [
      _createElementVNode("span", null, "目录：" + _toDisplayString(directoryStatus.value.configured_root || directoryStatus.value.auto_roots?.[0]?.download_path || '未配置'), 1),
      _createElementVNode("span", null, "来源：" + _toDisplayString(directoryStatus.value.source || '未配置'), 1),
      _createElementVNode("span", null, "当前队列：运行 " + _toDisplayString(queueStatus.value.running || 0) + " · 等待 " + _toDisplayString(queueStatus.value.pending || 0) + " · 暂停 " + _toDisplayString(queueStatus.value.paused || 0) + " · 共 " + _toDisplayString(queueTotal.value) + " 个活动任务", 1),
      _createElementVNode("span", null, "追更：每 " + _toDisplayString(subscriptionStatus.value.refresh_minutes || 30) + " 分钟检查新集", 1),
      _createElementVNode("span", null, "最近追更：" + _toDisplayString(followupSummary(subscriptionRefreshStatus.value)), 1),
      _createElementVNode("span", null, "最近同步：" + _toDisplayString(followupSummary(mediaSyncStatus.value)), 1),
      _createElementVNode("span", null, "TMDB：" + _toDisplayString(status.value.tmdb_association ? '自动关联' : '关闭'), 1),
      _cache[1] || (_cache[1] = _createElementVNode("span", null, "缓存：完成后才整理", -1)),
      _createElementVNode("span", null, "来源健康检查：每 " + _toDisplayString(sourceHealth.value.interval_minutes || 60) + " 分钟", 1)
    ]),
    _createElementVNode("section", _hoisted_15, [
      _createElementVNode("div", _hoisted_16, [
        _createElementVNode("div", _hoisted_17, [
          _cache[2] || (_cache[2] = _createTextVNode("资源站数量 ", -1)),
          _createElementVNode("span", _hoisted_18, _toDisplayString(loading.value ? '…' : sources.value.length), 1)
        ]),
        _cache[3] || (_cache[3] = _createElementVNode("span", { class: "source-caption" }, "打开页面仅读取缓存；搜索会跳过“配置禁用”的来源，网络不通的来源仍会尝试调用", -1))
      ]),
      (!loading.value && sources.value.length)
        ? (_openBlock(), _createElementBlock("div", {
            key: 0,
            class: _normalizeClass(['health-overview', { 'is-running': sourceHealth.value.running }])
          }, [
            _createElementVNode("div", _hoisted_19, [
              _createElementVNode("div", _hoisted_20, [
                _createElementVNode("span", _hoisted_21, _toDisplayString(sourceHealth.value.running ? '正在逐个检查来源' : '来源健康状态'), 1),
                _createElementVNode("span", _hoisted_22, _toDisplayString(healthProgressLabel.value), 1)
              ]),
              _createElementVNode("div", {
                class: "health-progress-track",
                role: "progressbar",
                "aria-label": healthProgressLabel.value,
                "aria-valuemin": 0,
                "aria-valuemax": 100,
                "aria-valuenow": healthProgress.value
              }, [
                _createElementVNode("span", {
                  style: _normalizeStyle({ width: `${healthProgress.value}%` })
                }, null, 4)
              ], 8, _hoisted_23)
            ]),
            _cache[4] || (_cache[4] = _createElementVNode("div", {
              class: "health-legend",
              "aria-label": "健康状态图例"
            }, [
              _createElementVNode("span", null, [
                _createElementVNode("i", {
                  class: "legend-dot is-pending",
                  "aria-hidden": "true"
                }),
                _createTextVNode("待检查")
              ]),
              _createElementVNode("span", null, [
                _createElementVNode("i", {
                  class: "legend-dot is-healthy",
                  "aria-hidden": "true"
                }),
                _createTextVNode("正常")
              ]),
              _createElementVNode("span", null, [
                _createElementVNode("i", {
                  class: "legend-dot is-failed",
                  "aria-hidden": "true"
                }),
                _createTextVNode("不可用")
              ])
            ], -1))
          ], 2))
        : _createCommentVNode("", true),
      (loading.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_24, "正在读取资源站配置…"))
        : (!sources.value.length)
          ? (_openBlock(), _createElementBlock("div", _hoisted_25, "暂未读取到资源站配置"))
          : (_openBlock(), _createElementBlock("div", _hoisted_26, [
              _createElementVNode("table", _hoisted_27, [
                _cache[7] || (_cache[7] = _createElementVNode("thead", null, [
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
                      key: source.key,
                      class: _normalizeClass({ 'is-pending': source.check_state === 'pending' })
                    }, [
                      _createElementVNode("td", null, [
                        _createElementVNode("span", {
                          class: _normalizeClass(['source-state', `is-${sourceVisualStatus(source)}`])
                        }, [
                          _cache[5] || (_cache[5] = _createElementVNode("i", {
                            class: "state-dot",
                            "aria-hidden": "true"
                          }, null, -1)),
                          _createTextVNode(" " + _toDisplayString(source.status_label || '已加载'), 1)
                        ], 2),
                        _createElementVNode("div", _hoisted_28, [
                          _createElementVNode("span", {
                            class: _normalizeClass(['health-state', `is-${sourceHealthVisualStatus(source)}`])
                          }, _toDisplayString(source.health_label || '未检查'), 3),
                          _createElementVNode("div", _hoisted_29, [
                            _createElementVNode("span", null, _toDisplayString(source.network_label || '待检查'), 1),
                            _createElementVNode("span", null, "成功 " + _toDisplayString(source.network_successes || 0) + " 次", 1),
                            _createElementVNode("span", null, "失败 " + _toDisplayString(source.network_failures || 0) + " 次", 1)
                          ]),
                          (source.last_error && source.check_state !== 'pending')
                            ? (_openBlock(), _createElementBlock("span", {
                                key: 0,
                                class: "source-error",
                                title: source.last_error
                              }, _toDisplayString(source.last_error), 9, _hoisted_30))
                            : _createCommentVNode("", true)
                        ])
                      ]),
                      _createElementVNode("td", null, [
                        _createElementVNode("div", _hoisted_31, [
                          _createElementVNode("span", _hoisted_32, _toDisplayString(source.name), 1),
                          _createElementVNode("span", _hoisted_33, _toDisplayString(source.key), 1)
                        ])
                      ]),
                      _createElementVNode("td", null, [
                        (sourceUrl(source))
                          ? (_openBlock(), _createElementBlock("a", {
                              key: 0,
                              class: "source-link",
                              href: sourceUrl(source),
                              target: "_blank",
                              rel: "noopener noreferrer"
                            }, _toDisplayString(sourceHost(source)), 9, _hoisted_34))
                          : (_openBlock(), _createElementBlock("span", _hoisted_35, "—"))
                      ]),
                      _createElementVNode("td", null, [
                        _createElementVNode("span", {
                          class: _normalizeClass(['search-state', `is-${sourceSearchVisualStatus(source)}`])
                        }, _toDisplayString(source.search_label || '支持'), 3)
                      ]),
                      _createElementVNode("td", null, [
                        _createElementVNode("span", {
                          class: _normalizeClass({ 'pending-time': source.check_state === 'pending' })
                        }, _toDisplayString(sourceCheckedLabel(source)), 3)
                      ]),
                      _createElementVNode("td", null, [
                        _createElementVNode("div", _hoisted_36, [
                          _createElementVNode("select", {
                            class: "source-config-select",
                            value: source.manual_disabled ? 'disabled' : 'enabled',
                            disabled: sourceIsBusy(source),
                            "aria-label": '配置' + (source.name || source.key) + '来源',
                            onChange: $event => (setSourceConfig(source, $event))
                          }, [...(_cache[6] || (_cache[6] = [
                            _createElementVNode("option", { value: "enabled" }, "配置启用", -1),
                            _createElementVNode("option", { value: "disabled" }, "配置禁用", -1)
                          ]))], 40, _hoisted_37),
                          _createElementVNode("button", {
                            class: "source-action",
                            disabled: sourceIsBusy(source),
                            "aria-label": '测试来源 ' + (source.name || source.key),
                            onClick: $event => (recheckSource(source))
                          }, _toDisplayString(sourceIsBusy(source) ? '测试中…' : '测试'), 9, _hoisted_38)
                        ])
                      ])
                    ], 2))
                  }), 128))
                ])
              ])
            ]))
    ]),
    _cache[8] || (_cache[8] = _createStaticVNode("<section class=\"panel help-panel\" data-v-4699be10><div class=\"section-title\" data-v-4699be10>使用说明</div><div class=\"help-grid\" data-v-4699be10><p data-v-4699be10><strong data-v-4699be10>目录</strong>：目录留空时按媒体类型读取 MoviePilot 的本地目录；填写插件目录则优先使用插件目录。</p><p data-v-4699be10><strong data-v-4699be10>多季合集</strong>：有明确季号或 TMDB 季集数能完整对应时才会自动分季；无法确认时会暂停，避免错放。</p><p data-v-4699be10><strong data-v-4699be10>自动追更</strong>：MoviePilot 活跃电视剧订阅会定期重新搜索；已完成和正在下载的集数会跳过，只排队新增集。</p><p data-v-4699be10><strong data-v-4699be10>媒体库</strong>：目录内没有正在下载的缓存文件后才显示完整文件夹；完成后可请求 Emby/Jellyfin 刷新。</p><p data-v-4699be10><strong data-v-4699be10>播放</strong>：插件不内置 m3u8 播放器，播放仍由已有 Emby/Jellyfin 页面负责。</p></div></section>", 1))
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-4699be10"]]);

export { AppPage as default };
