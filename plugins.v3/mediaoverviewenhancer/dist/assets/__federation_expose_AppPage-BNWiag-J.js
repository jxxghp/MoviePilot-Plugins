import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx,createBlock:_createBlock,renderList:_renderList,Fragment:_Fragment,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1 = { class: "moe-root" };
const _hoisted_2 = {
  key: 0,
  class: "moe-header"
};
const _hoisted_3 = { class: "moe-actions" };
const _hoisted_4 = { class: "text-body-2 mb-2" };
const _hoisted_5 = { class: "text-caption text-medium-emphasis mt-2" };
const _hoisted_6 = {
  key: 0,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_7 = {
  key: 1,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_8 = { key: 0 };
const _hoisted_9 = {
  key: 0,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_10 = {
  key: 1,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_11 = { class: "moe-preview" };
const _hoisted_12 = { key: 0 };
const _hoisted_13 = {
  key: 1,
  class: "text-error text-caption"
};
const _hoisted_14 = { class: "text-caption text-medium-emphasis mt-1" };
const _hoisted_15 = { class: "text-error" };
const _hoisted_16 = { class: "moe-preview" };
const _hoisted_17 = {
  key: 0,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_18 = { class: "text-caption text-medium-emphasis" };

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'AppPage',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'MediaOverviewEnhancer' },
  navKey: { type: String, default: 'main' },
  hideTitle: { type: Boolean, default: false },
},
  emits: ['close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const base = computed(() => `plugin/${props.pluginId || 'MediaOverviewEnhancer'}`);

const loading = ref(false);
const previewing = ref(false);
const sampling = ref(false);
const starting = ref(false);
const retrying = ref(false);
const rolling = ref(false);
const clearing = ref(false);
const message = ref('');
const error = ref('');
const status = ref({});
const servers = ref([]);
const previewItems = ref([]);
const previewTotal = ref(0);
const previewSampled = ref(0);
const sourceFilter = ref('all');
const form = ref({ media_type: 'all', title: '', force: false, limit: 30 });
let timer = null;

const reasonLabels = {
  missing: '简介缺失',
  short: '简介过短',
  duplicate: '简介重复',
  force: '强制重写',
  people: '缺演员',
  nfo: 'NFO/头像待补',
  avatar: '缺演员头像',
};

const actionLabels = {
  write: '将写入',
  skip: '跳过',
};

const kindLabels = {
  movie: '电影',
  episode: '剧集',
  mv: 'MV',
};

const run = computed(() => status.value.run || {});
const running = computed(() => Boolean(status.value.running));
const failures = computed(() => status.value.failures || []);
const backups = computed(() => status.value.backups || []);
const progress = computed(() => {
  const total = Number(run.value.total || 0);
  const done = Number(run.value.done || 0);
  if (!total) return 0
  return Math.min(100, Math.round((done / total) * 100))
});

const sourceOptions = computed(() => {
  const values = new Set();
  previewItems.value.forEach(item => {
    if (item.source) values.add(String(item.source));
  });
  return [
    { title: '全部来源', value: 'all' },
    ...Array.from(values).sort().map(value => ({ title: value, value })),
  ]
});

const filteredPreview = computed(() => {
  if (sourceFilter.value === 'all') return previewItems.value
  return previewItems.value.filter(item => String(item.source || '') === sourceFilter.value)
});

const latestRunId = computed(() => {
  const row = backups.value.find(item => item.run_id);
  return row?.run_id || ''
});

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

function errorText(err) {
  if (!err) return '未知错误'
  return err.message || String(err)
}

function kindLabel(kind) {
  return kindLabels[kind] || '电影'
}

function reasonLabel(reason) {
  return reasonLabels[reason] || reason || '-'
}

function actionLabel(item) {
  if (item.action === 'write') return `${actionLabels.write} · ${item.source || ''}`
  return `${actionLabels.skip} · ${item.message || ''}`
}

function episodeLabel(item) {
  if (item.kind !== 'episode') return '-'
  return `S${item.season}E${item.episode}`
}

async function loadStatus() {
  loading.value = true;
  try {
    const data = unwrap(await props.api.get(`${base.value}/status`));
    status.value = data && typeof data === 'object' ? data : {};
    if (status.value.running) {
      startPolling();
    } else {
      stopPolling();
    }
  } catch (err) {
    error.value = `读取状态失败：${errorText(err)}`;
  } finally {
    loading.value = false;
  }
}

async function loadServers() {
  try {
    const data = unwrap(await props.api.get(`${base.value}/servers`));
    servers.value = data?.servers || [];
  } catch (err) {
    servers.value = [];
  }
}

async function runPreview(withSample = false) {
  if (withSample) sampling.value = true;
  else previewing.value = true;
  error.value = '';
  message.value = '';
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/preview`, {
        media_type: form.value.media_type,
        title: form.value.title,
        force: form.value.force,
        limit: Number(form.value.limit) || 30,
        sample: withSample ? 2 : 0,
      }),
    );
    previewItems.value = data?.items || [];
    previewTotal.value = Number(data?.total || previewItems.value.length);
    previewSampled.value = Number(data?.sample || 0);
    const problems = (data?.errors || []).join('；');
    message.value = `试跑完成：共 ${previewTotal.value} 条待处理${
      previewSampled.value ? `，已生成 ${previewSampled.value} 条样张` : ''
    }${problems ? `（${problems}）` : ''}`;
  } catch (err) {
    error.value = `试跑失败：${errorText(err)}`;
  } finally {
    previewing.value = false;
    sampling.value = false;
  }
}

async function runNow() {
  starting.value = true;
  error.value = '';
  message.value = '';
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/run`, {
        media_type: form.value.media_type,
        title: form.value.title,
        force: form.value.force,
        limit: Number(form.value.limit) || 30,
        trigger: 'manual',
      }),
    );
    message.value = data?.message || '任务已提交';
    await loadStatus();
  } catch (err) {
    error.value = `启动失败：${errorText(err)}`;
  } finally {
    starting.value = false;
  }
}

async function redoItem(item) {
  if (!item?.key) return
  const mediaType = item.kind === 'episode' ? 'tv' : (item.kind === 'mv' ? 'mv' : 'movie');
  starting.value = true;
  error.value = '';
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/run`, {
        media_type: mediaType,
        title: '',
        force: true,
        limit: 1,
        keys: [item.key],
        trigger: 'manual',
      }),
    );
    message.value = data?.message || '已提交单条重做';
    await loadStatus();
  } catch (err) {
    error.value = `单条重做失败：${errorText(err)}`;
  } finally {
    starting.value = false;
  }
}

async function retryFailures() {
  retrying.value = true;
  error.value = '';
  try {
    const data = unwrap(await props.api.post(`${base.value}/retry`, {}));
    message.value = data?.message || '已请求重试';
    await loadStatus();
  } catch (err) {
    error.value = `重试失败：${errorText(err)}`;
  } finally {
    retrying.value = false;
  }
}

async function rollbackOne(row) {
  if (!row?.key) return
  rolling.value = true;
  error.value = '';
  try {
    const data = unwrap(await props.api.post(`${base.value}/rollback`, { keys: [row.key] }));
    message.value = data?.message || '已回滚';
    await loadStatus();
  } catch (err) {
    error.value = `回滚失败：${errorText(err)}`;
  } finally {
    rolling.value = false;
  }
}

async function rollbackLatestRun() {
  const runId = latestRunId.value;
  if (!runId) {
    message.value = '没有可回滚的运行批次';
    return
  }
  rolling.value = true;
  error.value = '';
  try {
    const data = unwrap(await props.api.post(`${base.value}/rollback`, { run_id: runId }));
    message.value = data?.message || '已回滚最近一轮';
    await loadStatus();
  } catch (err) {
    error.value = `回滚失败：${errorText(err)}`;
  } finally {
    rolling.value = false;
  }
}

async function cancelRun() {
  try {
    const data = unwrap(await props.api.post(`${base.value}/cancel`, {}));
    message.value = data?.message || '已请求停止';
    await loadStatus();
  } catch (err) {
    error.value = `停止失败：${errorText(err)}`;
  }
}

async function clearRecords() {
  clearing.value = true;
  try {
    const data = unwrap(await props.api.post(`${base.value}/clear`, {}));
    message.value = `已清空 ${data?.cleared ?? 0} 条处理记录与 ${data?.failures ?? 0} 条失败记录`;
    await loadStatus();
  } catch (err) {
    error.value = `清空失败：${errorText(err)}`;
  } finally {
    clearing.value = false;
  }
}

async function refreshAll() {
  await Promise.all([loadStatus(), loadServers()]);
}

function startPolling() {
  if (timer) return
  timer = window.setInterval(() => {
    loadStatus();
  }, 3000);
}

function stopPolling() {
  if (!timer) return
  window.clearInterval(timer);
  timer = null;
}

onMounted(() => {
  loadStatus();
  loadServers();
});

onUnmounted(() => {
  stopPolling();
});

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VTable = _resolveComponent("VTable");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (!props.hideTitle)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, [
          _cache[8] || (_cache[8] = _createElementVNode("div", null, [
            _createElementVNode("div", { class: "text-h6" }, "影视简介增强"),
            _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, " 为电影写更详细的简介，为剧集每一集写独立简介，为 MV 生成中文简介，并写回 Emby。 ")
          ], -1)),
          _createVNode(_component_VSpacer),
          _createVNode(_component_VBtn, {
            icon: "mdi-refresh",
            variant: "text",
            loading: loading.value,
            onClick: refreshAll
          }, null, 8, ["loading"])
        ]))
      : _createCommentVNode("", true),
    (error.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 1,
          type: "error",
          variant: "tonal",
          density: "compact",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (message.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 2,
          type: "info",
          variant: "tonal",
          density: "compact",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(message.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createVNode(_component_VCard, {
      variant: "tonal",
      class: "mb-3"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardText, { class: "moe-chips" }, {
          default: _withCtx(() => [
            _createVNode(_component_VChip, {
              color: status.value.enabled ? 'success' : 'grey',
              size: "small",
              variant: "flat"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(status.value.enabled ? '插件已启用' : '插件未启用'), 1)
              ]),
              _: 1
            }, 8, ["color"]),
            _createVNode(_component_VChip, {
              color: status.value.llm_available ? 'primary' : 'warning',
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(status.value.llm_available ? 'LLM 可用' : 'LLM 不可用'), 1)
              ]),
              _: 1
            }, 8, ["color"]),
            _createVNode(_component_VChip, {
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode("已处理 " + _toDisplayString(status.value.processed_total || 0) + " 条", 1)
              ]),
              _: 1
            }),
            (status.value.daily)
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 0,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(" 今日成功 " + _toDisplayString(status.value.daily.updated || 0) + " / 失败 " + _toDisplayString(status.value.daily.failed || 0), 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (status.value.failure_count)
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 1,
                  color: "error",
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(" 失败待处理 " + _toDisplayString(status.value.failure_count) + " 条 ", 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            _createVNode(_component_VChip, {
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode("可回滚 " + _toDisplayString(status.value.backup_count || 0) + " 条", 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VChip, {
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode("电影模式 " + _toDisplayString(status.value.movie_mode || '-'), 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VChip, {
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode("分集模式 " + _toDisplayString(status.value.episode_mode || '-'), 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VChip, {
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(" MV 简介 " + _toDisplayString(status.value.mv_enabled ? `已启用 · ${(status.value.mv_libraries || []).join('/') || 'mv'}` : '关闭'), 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VChip, {
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(status.value.auto_on_transfer ? '入库后自动' : '仅手动'), 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VChip, {
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(" 定时补漏 " + _toDisplayString(Number(status.value.schedule_hours || 0) > 0 ? `${status.value.schedule_hours} 小时` : '关闭'), 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        (servers.value.length)
          ? (_openBlock(), _createBlock(_component_VCardText, {
              key: 0,
              class: "moe-chips"
            }, {
              default: _withCtx(() => [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(servers.value, (server) => {
                  return (_openBlock(), _createBlock(_component_VChip, {
                    key: server.name + server.message,
                    color: server.connected ? 'success' : 'error',
                    size: "small",
                    variant: "tonal"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(" Emby " + _toDisplayString(server.name) + " · " + _toDisplayString(server.connected ? '已连接' : server.message), 1)
                    ]),
                    _: 2
                  }, 1032, ["color"]))
                }), 128))
              ]),
              _: 1
            }))
          : _createCommentVNode("", true)
      ]),
      _: 1
    }),
    _createVNode(_component_VCard, {
      variant: "outlined",
      class: "mb-3"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
          default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
            _createTextVNode("执行范围", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_VCardText, null, {
          default: _withCtx(() => [
            _createVNode(_component_VRow, { dense: "" }, {
              default: _withCtx(() => [
                _createVNode(_component_VCol, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VSelect, {
                      modelValue: form.value.media_type,
                      "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((form.value.media_type) = $event)),
                      items: [
                { title: '全部', value: 'all' },
                { title: '仅电影', value: 'movie' },
                { title: '仅剧集', value: 'tv' },
                { title: '仅 MV', value: 'mv' },
                { title: '仅补 NFO/头像', value: 'maintenance' },
              ],
                      label: "处理对象",
                      density: "comfortable",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_VCol, {
                  cols: "12",
                  md: "4"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VTextField, {
                      modelValue: form.value.title,
                      "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((form.value.title) = $event)),
                      label: "指定标题（留空为整库扫描）",
                      density: "comfortable",
                      "hide-details": "",
                      clearable: ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_VCol, {
                  cols: "12",
                  md: "2"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VTextField, {
                      modelValue: form.value.limit,
                      "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((form.value.limit) = $event)),
                      type: "number",
                      label: "本次上限",
                      density: "comfortable",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_VCol, {
                  cols: "12",
                  md: "3",
                  class: "d-flex align-center"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VSwitch, {
                      modelValue: form.value.force,
                      "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((form.value.force) = $event)),
                      label: "强制重写已有简介",
                      density: "comfortable",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _cache[17] || (_cache[17] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-1" }, " 「仅 MV」扫描 MV 媒体库并由 AI 生成简介；「仅补 NFO/头像」只修复缺失或过期的 NFO 与演员头像，不改写简介； 「全部」不含 MV，避免一次性产生大量大模型调用。 ", -1)),
            _createElementVNode("div", _hoisted_3, [
              _createVNode(_component_VBtn, {
                variant: "tonal",
                "prepend-icon": "mdi-flask-outline",
                loading: previewing.value,
                onClick: _cache[4] || (_cache[4] = $event => (runPreview(false)))
              }, {
                default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                  _createTextVNode(" 试跑（不写入） ", -1)
                ]))]),
                _: 1
              }, 8, ["loading"]),
              _createVNode(_component_VBtn, {
                variant: "tonal",
                "prepend-icon": "mdi-image-text",
                loading: sampling.value,
                onClick: _cache[5] || (_cache[5] = $event => (runPreview(true)))
              }, {
                default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                  _createTextVNode(" 生成 2 条样张 ", -1)
                ]))]),
                _: 1
              }, 8, ["loading"]),
              _createVNode(_component_VBtn, {
                color: "primary",
                "prepend-icon": "mdi-play",
                loading: starting.value,
                disabled: running.value,
                onClick: runNow
              }, {
                default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                  _createTextVNode(" 立即执行 ", -1)
                ]))]),
                _: 1
              }, 8, ["loading", "disabled"]),
              _createVNode(_component_VBtn, {
                variant: "tonal",
                color: "warning",
                "prepend-icon": "mdi-stop",
                disabled: !running.value,
                onClick: cancelRun
              }, {
                default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                  _createTextVNode(" 停止 ", -1)
                ]))]),
                _: 1
              }, 8, ["disabled"]),
              _createVNode(_component_VBtn, {
                variant: "tonal",
                color: "error",
                "prepend-icon": "mdi-restart-alert",
                loading: retrying.value,
                disabled: !failures.value.length || running.value,
                onClick: retryFailures
              }, {
                default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                  _createTextVNode(" 重试失败项 ", -1)
                ]))]),
                _: 1
              }, 8, ["loading", "disabled"]),
              _createVNode(_component_VSpacer),
              _createVNode(_component_VBtn, {
                variant: "text",
                color: "error",
                "prepend-icon": "mdi-delete-sweep-outline",
                loading: clearing.value,
                onClick: clearRecords
              }, {
                default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                  _createTextVNode(" 清空处理记录 ", -1)
                ]))]),
                _: 1
              }, 8, ["loading"]),
              _createVNode(_component_VBtn, {
                variant: "text",
                "prepend-icon": "mdi-cog-outline",
                onClick: _cache[6] || (_cache[6] = $event => (emit('switch')))
              }, {
                default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                  _createTextVNode("插件设置", -1)
                ]))]),
                _: 1
              })
            ])
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    (run.value && Object.keys(run.value).length)
      ? (_openBlock(), _createBlock(_component_VCard, {
          key: 3,
          variant: "outlined",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
              default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                _createTextVNode("运行进度", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_VCardText, null, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_4, _toDisplayString(run.value.state === 'running' ? '执行中' : '已结束') + " · 共 " + _toDisplayString(run.value.total || 0) + " 条 · 成功 " + _toDisplayString(run.value.updated || 0) + " · 跳过 " + _toDisplayString(run.value.skipped || 0) + " · 失败 " + _toDisplayString(run.value.failed || 0), 1),
                _createVNode(_component_VProgressLinear, {
                  "model-value": progress.value,
                  color: "primary",
                  height: "10",
                  rounded: ""
                }, null, 8, ["model-value"]),
                _createElementVNode("div", _hoisted_5, _toDisplayString(run.value.message || ''), 1),
                (run.value.current)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_6, "当前：" + _toDisplayString(run.value.current), 1))
                  : _createCommentVNode("", true),
                (run.value.started_at)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_7, [
                      _createTextVNode(" 开始于 " + _toDisplayString(run.value.started_at), 1),
                      (run.value.finished_at)
                        ? (_openBlock(), _createElementBlock("span", _hoisted_8, " · 结束于 " + _toDisplayString(run.value.finished_at), 1))
                        : _createCommentVNode("", true)
                    ]))
                  : _createCommentVNode("", true)
              ]),
              _: 1
            })
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (previewItems.value.length)
      ? (_openBlock(), _createBlock(_component_VCard, {
          key: 4,
          variant: "outlined",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "text-subtitle-1 d-flex align-center" }, {
              default: _withCtx(() => [
                _createTextVNode(" 试跑结果（共 " + _toDisplayString(previewTotal.value) + " 条） ", 1),
                _createVNode(_component_VSpacer),
                _createVNode(_component_VSelect, {
                  modelValue: sourceFilter.value,
                  "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((sourceFilter).value = $event)),
                  items: sourceOptions.value,
                  density: "compact",
                  variant: "outlined",
                  "hide-details": "",
                  style: {"max-width":"200px"}
                }, null, 8, ["modelValue", "items"])
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "moe-table-wrap" }, {
              default: _withCtx(() => [
                _createVNode(_component_VTable, { density: "compact" }, {
                  default: _withCtx(() => [
                    _cache[20] || (_cache[20] = _createElementVNode("thead", null, [
                      _createElementVNode("tr", null, [
                        _createElementVNode("th", null, "类型"),
                        _createElementVNode("th", null, "标题"),
                        _createElementVNode("th", null, "集"),
                        _createElementVNode("th", null, "原因"),
                        _createElementVNode("th", null, "处理"),
                        _createElementVNode("th", null, "样张 / 质量"),
                        _createElementVNode("th")
                      ])
                    ], -1)),
                    _createElementVNode("tbody", null, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(filteredPreview.value, (item, index) => {
                        return (_openBlock(), _createElementBlock("tr", {
                          key: item.key || index
                        }, [
                          _createElementVNode("td", null, _toDisplayString(kindLabel(item.kind)), 1),
                          _createElementVNode("td", null, _toDisplayString(item.title), 1),
                          _createElementVNode("td", null, _toDisplayString(episodeLabel(item)), 1),
                          _createElementVNode("td", null, _toDisplayString(reasonLabel(item.reason)), 1),
                          _createElementVNode("td", null, [
                            _createElementVNode("div", null, _toDisplayString(actionLabel(item)), 1),
                            (item.need_nfo)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_9, "将补 NFO"))
                              : _createCommentVNode("", true),
                            (item.need_avatar)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_10, "将补头像"))
                              : _createCommentVNode("", true)
                          ]),
                          _createElementVNode("td", _hoisted_11, [
                            (item.preview)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_12, _toDisplayString(item.preview), 1))
                              : _createCommentVNode("", true),
                            (item.quality)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_13, "质量提示：" + _toDisplayString(item.quality), 1))
                              : _createCommentVNode("", true)
                          ]),
                          _createElementVNode("td", null, [
                            _createVNode(_component_VBtn, {
                              size: "x-small",
                              variant: "text",
                              disabled: running.value,
                              loading: starting.value,
                              onClick: $event => (redoItem(item))
                            }, {
                              default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                                _createTextVNode(" 重做 ", -1)
                              ]))]),
                              _: 1
                            }, 8, ["disabled", "loading", "onClick"])
                          ])
                        ]))
                      }), 128))
                    ])
                  ]),
                  _: 1
                }),
                _createElementVNode("div", _hoisted_14, " 样张只对前 " + _toDisplayString(previewSampled.value || 0) + " 条生成，不会写入媒体库；「重做」会强制重新生成该条。 ", 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (failures.value.length)
      ? (_openBlock(), _createBlock(_component_VCard, {
          key: 5,
          variant: "outlined",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "text-subtitle-1 d-flex align-center" }, {
              default: _withCtx(() => [
                _createTextVNode(" 失败条目（最近 " + _toDisplayString(failures.value.length) + " 条） ", 1),
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  size: "small",
                  variant: "tonal",
                  color: "error",
                  "prepend-icon": "mdi-restart-alert",
                  loading: retrying.value,
                  disabled: running.value,
                  onClick: retryFailures
                }, {
                  default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                    _createTextVNode(" 全部重试 ", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading", "disabled"])
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "moe-table-wrap" }, {
              default: _withCtx(() => [
                _createVNode(_component_VTable, { density: "compact" }, {
                  default: _withCtx(() => [
                    _cache[22] || (_cache[22] = _createElementVNode("thead", null, [
                      _createElementVNode("tr", null, [
                        _createElementVNode("th", null, "类型"),
                        _createElementVNode("th", null, "标题"),
                        _createElementVNode("th", null, "集"),
                        _createElementVNode("th", null, "失败原因"),
                        _createElementVNode("th", null, "时间"),
                        _createElementVNode("th", null, "次数")
                      ])
                    ], -1)),
                    _createElementVNode("tbody", null, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(failures.value, (row, index) => {
                        return (_openBlock(), _createElementBlock("tr", {
                          key: row.key || index
                        }, [
                          _createElementVNode("td", null, _toDisplayString(kindLabel(row.kind)), 1),
                          _createElementVNode("td", null, _toDisplayString(row.title), 1),
                          _createElementVNode("td", null, _toDisplayString(row.kind === 'episode' ? `S${row.season}E${row.episode}` : '-'), 1),
                          _createElementVNode("td", _hoisted_15, _toDisplayString(row.message), 1),
                          _createElementVNode("td", null, _toDisplayString(row.time), 1),
                          _createElementVNode("td", null, _toDisplayString(row.count), 1)
                        ]))
                      }), 128))
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (backups.value.length)
      ? (_openBlock(), _createBlock(_component_VCard, {
          key: 6,
          variant: "outlined",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "text-subtitle-1 d-flex align-center" }, {
              default: _withCtx(() => [
                _createTextVNode(" 可回滚的旧简介（最近 " + _toDisplayString(backups.value.length) + " 条） ", 1),
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  size: "small",
                  variant: "tonal",
                  color: "warning",
                  "prepend-icon": "mdi-history",
                  loading: rolling.value,
                  disabled: !latestRunId.value || running.value,
                  onClick: rollbackLatestRun
                }, {
                  default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                    _createTextVNode(" 回滚最近一轮 ", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading", "disabled"])
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "moe-table-wrap" }, {
              default: _withCtx(() => [
                _createVNode(_component_VTable, { density: "compact" }, {
                  default: _withCtx(() => [
                    _cache[25] || (_cache[25] = _createElementVNode("thead", null, [
                      _createElementVNode("tr", null, [
                        _createElementVNode("th", null, "类型"),
                        _createElementVNode("th", null, "标题"),
                        _createElementVNode("th", null, "集"),
                        _createElementVNode("th", null, "写入前简介"),
                        _createElementVNode("th", null, "时间"),
                        _createElementVNode("th")
                      ])
                    ], -1)),
                    _createElementVNode("tbody", null, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(backups.value, (row, index) => {
                        return (_openBlock(), _createElementBlock("tr", {
                          key: row.key || index
                        }, [
                          _createElementVNode("td", null, _toDisplayString(kindLabel(row.kind)), 1),
                          _createElementVNode("td", null, _toDisplayString(row.title), 1),
                          _createElementVNode("td", null, _toDisplayString(row.kind === 'episode' ? `S${row.season}E${row.episode}` : '-'), 1),
                          _createElementVNode("td", _hoisted_16, _toDisplayString(row.preview) + "（" + _toDisplayString(row.chars) + " 字）", 1),
                          _createElementVNode("td", null, _toDisplayString(row.time), 1),
                          _createElementVNode("td", null, [
                            _createVNode(_component_VBtn, {
                              size: "x-small",
                              variant: "text",
                              color: "warning",
                              loading: rolling.value,
                              disabled: running.value,
                              onClick: $event => (rollbackOne(row))
                            }, {
                              default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                                _createTextVNode(" 回滚 ", -1)
                              ]))]),
                              _: 1
                            }, 8, ["loading", "disabled", "onClick"])
                          ])
                        ]))
                      }), 128))
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createVNode(_component_VCard, { variant: "outlined" }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
          default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
            _createTextVNode("最近日志", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_VCardText, { class: "moe-logs" }, {
          default: _withCtx(() => [
            (!(status.value.logs || []).length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_17, "暂无日志"))
              : _createCommentVNode("", true),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList((status.value.logs || []).slice().reverse(), (log, index) => {
              return (_openBlock(), _createElementBlock("div", {
                key: index,
                class: "moe-log-line"
              }, [
                _createElementVNode("span", _hoisted_18, "[" + _toDisplayString(log.time) + "]", 1),
                _createElementVNode("span", {
                  class: _normalizeClass(log.level === 'error' ? 'text-error' : (log.level === 'warning' ? 'text-warning' : ''))
                }, _toDisplayString(log.message), 3)
              ]))
            }), 128))
          ]),
          _: 1
        })
      ]),
      _: 1
    })
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-0c528ec3"]]);

export { AppPage as default };
