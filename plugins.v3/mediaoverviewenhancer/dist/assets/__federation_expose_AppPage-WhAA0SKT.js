import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx,createBlock:_createBlock,renderList:_renderList,Fragment:_Fragment,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1 = { class: "moe-root" };
const _hoisted_2 = {
  key: 0,
  class: "moe-header"
};
const _hoisted_3 = { class: "moe-actions" };
const _hoisted_4 = {
  key: 0,
  class: "text-caption text-warning mt-1"
};
const _hoisted_5 = { class: "text-error" };
const _hoisted_6 = {
  key: 0,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_7 = { class: "moe-preview" };
const _hoisted_8 = { class: "text-caption text-medium-emphasis mt-1" };
const _hoisted_9 = { class: "text-body-2 mb-2" };
const _hoisted_10 = { class: "text-caption text-medium-emphasis mt-2" };
const _hoisted_11 = {
  key: 0,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_12 = {
  key: 1,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_13 = { key: 0 };
const _hoisted_14 = {
  key: 2,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_15 = {
  key: 0,
  class: "text-warning"
};
const _hoisted_16 = {
  key: 0,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_17 = {
  key: 1,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_18 = { class: "moe-preview" };
const _hoisted_19 = { key: 0 };
const _hoisted_20 = {
  key: 1,
  class: "text-error text-caption"
};
const _hoisted_21 = {
  key: 2,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_22 = { key: 0 };
const _hoisted_23 = { key: 1 };
const _hoisted_24 = {
  key: 3,
  class: "text-caption"
};
const _hoisted_25 = { class: "text-caption text-medium-emphasis mt-1" };
const _hoisted_26 = { class: "text-error" };
const _hoisted_27 = { class: "moe-preview" };
const _hoisted_28 = {
  key: 0,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_29 = { class: "text-caption text-medium-emphasis" };

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
const writingKey = ref('');
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
  series: '整剧',
  season: '整季',
  mv: 'MV',
};

const failureKindLabels = {
  llm_unavailable: '大模型不可用',
  llm_rate_limit: '大模型限流',
  llm_empty: '空返回',
  llm_error: '调用异常',
  quality_gate: '质量闸门',
  material_missing: '素材缺失',
  emby_write: '写入失败',
  nfo_write: 'NFO 写入',
  unknown: '未归类',
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

const llmStats = computed(() => status.value.llm || {});
const failureKinds = computed(() => status.value.failure_kinds || {});
const features = computed(() => status.value.features || {});

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

function errorText(err) {
  if (!err) return '未知错误'
  const response = err.response || {};
  const data = response.data || {};
  const detail = data.detail || data.message || err.message;
  if (typeof detail === 'string' && detail.trim()) return detail
  if (response.status) return `HTTP ${response.status}`
  return '未知错误（后端未返回详情，请查看 MP 日志）'
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

async function writeSample(item) {
  if (!item?.key || !item?.preview) return
  writingKey.value = String(item.key);
  error.value = '';
  message.value = '';
  const mediaType = ['episode', 'series', 'season'].includes(item.kind)
    ? 'tv'
    : (item.kind === 'mv' ? 'mv' : 'movie');
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/write-sample`, {
        key: item.key,
        kind: item.kind || '',
        media_type: mediaType,
        title: item.title || '',
        year: item.year || '',
        season: item.season ?? 0,
        episode: item.episode ?? 0,
        episode_title: item.episode_title || '',
        text: item.preview,
        title_override: item.new_title || '',
      }),
    );
    if (data?.written) {
      message.value = `已写入样张：${item.title || item.key}`;
      await loadStatus();
    } else {
      error.value = `写入失败：${data?.message || '未知原因'}`;
    }
  } catch (err) {
    error.value = `写入失败：${errorText(err)}`;
  } finally {
    writingKey.value = '';
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

const auditing = ref(false);
const repairing = ref(false);
const auditItems = ref([]);
const auditScanned = ref(0);
const auditTotal = ref(0);
const auditTime = ref('');
const auditErrors = ref([]);
const auditType = ref('all');
const auditLimit = ref(300);
const auditSelected = ref([]);

const auditFilter = ref('all');
const auditSelectedSet = computed(() => new Set(auditSelected.value.map(String)));

function auditHas(item, kind) {
  const text = (item.reasons || []).join('；');
  if (kind === 'missing') return text.includes('简介缺失')
  if (kind === 'short') return text.includes('简介过短')
  if (kind === 'tech') return text.includes('技术信息')
  if (kind === 'flavor') return text.includes('AI 味')
  if (kind === 'similar') return text.includes('雷同')
  return true
}

const filteredAuditItems = computed(() => {
  if (auditFilter.value === 'all') return auditItems.value
  return auditItems.value.filter(item => auditHas(item, auditFilter.value))
});

const auditAllSelected = computed(
  () =>
    filteredAuditItems.value.length > 0 &&
    filteredAuditItems.value.every(item => auditSelectedSet.value.has(String(item.key))),
);

function auditReasonText(item) {
  return (item.reasons || []).join('；') || '-'
}

function applyAudit(data) {
  auditItems.value = data?.items || [];
  auditScanned.value = Number(data?.scanned || 0);
  auditTotal.value = Number(data?.total || 0);
  auditTime.value = data?.time || '';
  auditErrors.value = data?.errors || [];
  const keys = new Set(auditItems.value.map(item => String(item.key)));
  auditSelected.value = auditSelected.value.filter(key => keys.has(key));
}

async function loadAudit() {
  try {
    const data = unwrap(await props.api.get(`${base.value}/audit`));
    applyAudit(data);
  } catch (err) {
    auditItems.value = [];
  }
}

async function runAudit() {
  auditing.value = true;
  error.value = '';
  message.value = '';
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/audit/scan`, {
        media_type: auditType.value,
        limit: Number(auditLimit.value) || 300,
      }),
    );
    applyAudit(data);
    const problems = (data?.errors || []).join('；');
    message.value = `体检完成：扫描 ${auditScanned.value} 条，发现 ${auditTotal.value} 条低质简介${
      data?.truncated ? `（仅显示前 ${auditItems.value.length} 条）` : ''
    }${problems ? `（${problems}）` : ''}`;
    auditSelected.value = auditItems.value.slice(0, 50).map(item => String(item.key));
  } catch (err) {
    error.value = `体检失败：${errorText(err)}`;
  } finally {
    auditing.value = false;
  }
}

function toggleAuditAll() {
  if (auditAllSelected.value) {
    auditSelected.value = [];
  } else {
    auditSelected.value = filteredAuditItems.value.map(item => String(item.key));
  }
}

function toggleAuditItem(key) {
  const value = String(key);
  const index = auditSelected.value.indexOf(value);
  if (index >= 0) auditSelected.value.splice(index, 1);
  else auditSelected.value.push(value);
}

async function repairAudit() {
  if (!auditSelected.value.length) {
    message.value = '请先勾选要重写的条目';
    return
  }
  repairing.value = true;
  error.value = '';
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/audit/repair`, { keys: auditSelected.value }),
    );
    if (data?.started) {
      message.value = data?.message || '已提交重写';
      await loadStatus();
    } else {
      error.value = data?.message || '提交重写失败';
    }
  } catch (err) {
    error.value = `提交重写失败：${errorText(err)}`;
  } finally {
    repairing.value = false;
  }
}

onMounted(() => {
  loadStatus();
  loadServers();
  loadAudit();
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
  const _component_VCheckbox = _resolveComponent("VCheckbox");
  const _component_VTable = _resolveComponent("VTable");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (!props.hideTitle)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, [
          _cache[11] || (_cache[11] = _createElementVNode("div", null, [
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
            (Number(llmStats.value.calls || 0))
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 2,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(" 今日大模型 " + _toDisplayString(llmStats.value.calls) + " 次 · 成功率 " + _toDisplayString(llmStats.value.success_rate ?? 0) + "% · 均耗时 " + _toDisplayString(llmStats.value.avg_seconds ?? 0) + "s ", 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (Number(llmStats.value.rate_limited || 0))
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 3,
                  color: "warning",
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(" 今日限流 " + _toDisplayString(llmStats.value.rate_limited) + " 次 ", 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (features.value.style_preset)
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 4,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(" 文风 " + _toDisplayString(features.value.style_preset), 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (features.value.episode_title)
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 5,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                    _createTextVNode("分集标题美化", -1)
                  ]))]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (features.value.series)
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 6,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                    _createTextVNode("整剧简介", -1)
                  ]))]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (features.value.season)
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 7,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                    _createTextVNode("整季简介", -1)
                  ]))]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (features.value.people_bio)
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 8,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                    _createTextVNode("演职员简介", -1)
                  ]))]),
                  _: 1
                }))
              : _createCommentVNode("", true),
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
        (Object.keys(failureKinds.value).length)
          ? (_openBlock(), _createBlock(_component_VCardText, {
              key: 0,
              class: "moe-chips"
            }, {
              default: _withCtx(() => [
                _cache[16] || (_cache[16] = _createElementVNode("span", { class: "text-caption text-medium-emphasis align-self-center" }, "失败分类：", -1)),
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(failureKinds.value, (count, kind) => {
                  return (_openBlock(), _createBlock(_component_VChip, {
                    key: kind,
                    size: "small",
                    color: "error",
                    variant: "tonal"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(failureKindLabels[kind] || kind) + " " + _toDisplayString(count), 1)
                    ]),
                    _: 2
                  }, 1024))
                }), 128))
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        (servers.value.length)
          ? (_openBlock(), _createBlock(_component_VCardText, {
              key: 1,
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
          default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
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
                { title: '仅剧集（含整剧/整季）', value: 'tv' },
                { title: '仅 MV', value: 'mv' },
                { title: '仅补分集标题', value: 'titles' },
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
            _cache[25] || (_cache[25] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-1" }, " 「仅 MV」扫描 MV 媒体库并由 AI 生成简介；「仅补分集标题」只改写「第 N 集」这类占位标题 （写 Emby 标题与 NFO），**不动简介**；「仅补 NFO/头像」只修复缺失或过期的 NFO 与演员头像； 「全部」不含 MV，避免一次性产生大量大模型调用。 ", -1)),
            _createElementVNode("div", _hoisted_3, [
              _createVNode(_component_VBtn, {
                variant: "tonal",
                "prepend-icon": "mdi-flask-outline",
                loading: previewing.value,
                onClick: _cache[4] || (_cache[4] = $event => (runPreview(false)))
              }, {
                default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
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
                default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
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
                default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
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
                default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
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
                default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
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
                default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                  _createTextVNode(" 清空处理记录 ", -1)
                ]))]),
                _: 1
              }, 8, ["loading"]),
              _createVNode(_component_VBtn, {
                variant: "text",
                "prepend-icon": "mdi-cog-outline",
                onClick: _cache[6] || (_cache[6] = $event => (emit('switch')))
              }, {
                default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
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
    _createVNode(_component_VCard, {
      variant: "outlined",
      class: "mb-3"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardTitle, { class: "text-subtitle-1 d-flex align-center flex-wrap ga-2" }, {
          default: _withCtx(() => [
            _cache[27] || (_cache[27] = _createTextVNode(" 存量简介体检 ", -1)),
            (auditTime.value)
              ? (_openBlock(), _createBlock(_component_VChip, {
                  key: 0,
                  size: "x-small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(auditTime.value), 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            _createVNode(_component_VSpacer),
            _createVNode(_component_VSelect, {
              modelValue: auditFilter.value,
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((auditFilter).value = $event)),
              items: [
            { title: '全部问题', value: 'all' },
            { title: '简介缺失', value: 'missing' },
            { title: '简介过短', value: 'short' },
            { title: '技术词', value: 'tech' },
            { title: 'AI 味', value: 'flavor' },
            { title: '同季雷同', value: 'similar' },
          ],
              density: "compact",
              variant: "outlined",
              "hide-details": "",
              style: {"max-width":"150px"}
            }, null, 8, ["modelValue"]),
            _createVNode(_component_VBtn, {
              size: "small",
              variant: "tonal",
              "prepend-icon": "mdi-magnify-scan",
              loading: auditing.value,
              disabled: running.value || repairing.value,
              onClick: runAudit
            }, {
              default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                _createTextVNode(" 开始体检 ", -1)
              ]))]),
              _: 1
            }, 8, ["loading", "disabled"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCardText, null, {
          default: _withCtx(() => [
            _createVNode(_component_VRow, { dense: "" }, {
              default: _withCtx(() => [
                _createVNode(_component_VCol, {
                  cols: "12",
                  md: "4"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VSelect, {
                      modelValue: auditType.value,
                      "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((auditType).value = $event)),
                      items: [
                { title: '电影 + 剧集', value: 'all' },
                { title: '仅电影', value: 'movie' },
                { title: '仅剧集分集', value: 'tv' },
                { title: '仅 MV', value: 'mv' },
              ],
                      label: "体检范围",
                      density: "comfortable",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_VCol, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VTextField, {
                      modelValue: auditLimit.value,
                      "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((auditLimit).value = $event)),
                      type: "number",
                      label: "最多显示条数",
                      density: "comfortable",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_VCol, {
                  cols: "12",
                  md: "5",
                  class: "d-flex align-center flex-wrap ga-2"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VBtn, {
                      size: "small",
                      variant: "text",
                      disabled: !auditItems.value.length,
                      onClick: toggleAuditAll
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(auditAllSelected.value ? '取消全选' : '全选'), 1)
                      ]),
                      _: 1
                    }, 8, ["disabled"]),
                    _createVNode(_component_VBtn, {
                      size: "small",
                      color: "primary",
                      "prepend-icon": "mdi-auto-fix",
                      disabled: !auditSelected.value.length || running.value || repairing.value,
                      loading: repairing.value,
                      onClick: repairAudit
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(" 重写选中（" + _toDisplayString(auditSelected.value.length) + "） ", 1)
                      ]),
                      _: 1
                    }, 8, ["disabled", "loading"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _cache[28] || (_cache[28] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-1" }, " 只读扫描已有简介（包括旧版本写入、手动修改和其他插件写入的内容），检测缺失 / 过短、技术词、 模板化开头、AI 味偏重与同季雷同。扫描不调用大模型、不写库；只有「重写选中」才会生成并写回， 且仍走质量闸门与失败重试。 ", -1)),
            (auditErrors.value.length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_4, _toDisplayString(auditErrors.value.join('；')), 1))
              : _createCommentVNode("", true)
          ]),
          _: 1
        }),
        (auditItems.value.length)
          ? (_openBlock(), _createBlock(_component_VCardText, {
              key: 0,
              class: "moe-table-wrap"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTable, { density: "compact" }, {
                  default: _withCtx(() => [
                    _cache[29] || (_cache[29] = _createElementVNode("thead", null, [
                      _createElementVNode("tr", null, [
                        _createElementVNode("th", { style: {"width":"40px"} }),
                        _createElementVNode("th", null, "类型"),
                        _createElementVNode("th", null, "标题"),
                        _createElementVNode("th", null, "集"),
                        _createElementVNode("th", null, "字数"),
                        _createElementVNode("th", null, "AI 味"),
                        _createElementVNode("th", null, "问题"),
                        _createElementVNode("th", null, "现简介")
                      ])
                    ], -1)),
                    _createElementVNode("tbody", null, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(filteredAuditItems.value, (item) => {
                        return (_openBlock(), _createElementBlock("tr", {
                          key: item.key
                        }, [
                          _createElementVNode("td", null, [
                            _createVNode(_component_VCheckbox, {
                              "model-value": auditSelectedSet.value.has(String(item.key)),
                              density: "compact",
                              "hide-details": "",
                              "onUpdate:modelValue": $event => (toggleAuditItem(item.key))
                            }, null, 8, ["model-value", "onUpdate:modelValue"])
                          ]),
                          _createElementVNode("td", null, _toDisplayString(kindLabel(item.kind)), 1),
                          _createElementVNode("td", null, _toDisplayString(item.title), 1),
                          _createElementVNode("td", null, _toDisplayString(item.kind === 'episode' ? `S${item.season}E${item.episode}` : '-'), 1),
                          _createElementVNode("td", null, _toDisplayString(item.chars), 1),
                          _createElementVNode("td", null, _toDisplayString(item.flavor || '-'), 1),
                          _createElementVNode("td", null, [
                            _createElementVNode("div", _hoisted_5, _toDisplayString(auditReasonText(item)), 1),
                            ((item.hints || []).length)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_6, _toDisplayString((item.hints || []).join('；')), 1))
                              : _createCommentVNode("", true)
                          ]),
                          _createElementVNode("td", _hoisted_7, _toDisplayString(item.preview), 1)
                        ]))
                      }), 128))
                    ])
                  ]),
                  _: 1
                }),
                _createElementVNode("div", _hoisted_8, " 共发现 " + _toDisplayString(auditTotal.value) + " 条；当前筛选 " + _toDisplayString(filteredAuditItems.value.length) + " 条（已保存 " + _toDisplayString(auditItems.value.length) + " 条）。 体检结果会保留到下次扫描。 ", 1)
              ]),
              _: 1
            }))
          : (_openBlock(), _createBlock(_component_VCardText, {
              key: 1,
              class: "text-caption text-medium-emphasis"
            }, {
              default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
                _createTextVNode(" 还没有体检结果。点击「开始体检」扫描当前媒体库。 ", -1)
              ]))]),
              _: 1
            }))
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
              default: _withCtx(() => [...(_cache[31] || (_cache[31] = [
                _createTextVNode("运行进度", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_VCardText, null, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_9, _toDisplayString(run.value.state === 'running' ? '执行中' : '已结束') + " · 共 " + _toDisplayString(run.value.total || 0) + " 条 · 成功 " + _toDisplayString(run.value.updated || 0) + " · 跳过 " + _toDisplayString(run.value.skipped || 0) + " · 失败 " + _toDisplayString(run.value.failed || 0), 1),
                _createVNode(_component_VProgressLinear, {
                  "model-value": progress.value,
                  color: "primary",
                  height: "10",
                  rounded: ""
                }, null, 8, ["model-value"]),
                _createElementVNode("div", _hoisted_10, _toDisplayString(run.value.message || ''), 1),
                (run.value.current)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_11, "当前：" + _toDisplayString(run.value.current), 1))
                  : _createCommentVNode("", true),
                (run.value.started_at)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_12, [
                      _createTextVNode(" 开始于 " + _toDisplayString(run.value.started_at), 1),
                      (run.value.finished_at)
                        ? (_openBlock(), _createElementBlock("span", _hoisted_13, " · 结束于 " + _toDisplayString(run.value.finished_at), 1))
                        : _createCommentVNode("", true)
                    ]))
                  : _createCommentVNode("", true),
                (run.value.llm && run.value.llm.calls)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_14, [
                      _createTextVNode(" 本轮大模型：调用 " + _toDisplayString(run.value.llm.calls) + " 次 · 失败 " + _toDisplayString(run.value.llm.errors || 0) + " · 空返回 " + _toDisplayString(run.value.llm.empty || 0) + " ", 1),
                      (run.value.llm.rate_limited)
                        ? (_openBlock(), _createElementBlock("span", _hoisted_15, "· 出现限流 " + _toDisplayString(run.value.llm.rate_limited) + " 次", 1))
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
                  "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((sourceFilter).value = $event)),
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
                    _cache[34] || (_cache[34] = _createElementVNode("thead", null, [
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
                              ? (_openBlock(), _createElementBlock("div", _hoisted_16, "将补 NFO"))
                              : _createCommentVNode("", true),
                            (item.need_avatar)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_17, "将补头像"))
                              : _createCommentVNode("", true)
                          ]),
                          _createElementVNode("td", _hoisted_18, [
                            (item.preview)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_19, _toDisplayString(item.preview), 1))
                              : _createCommentVNode("", true),
                            (item.quality)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_20, "质量提示：" + _toDisplayString(item.quality), 1))
                              : _createCommentVNode("", true),
                            (item.preview)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_21, [
                                  _createTextVNode(" AI 味 " + _toDisplayString(item.ai_flavor ?? '-') + " 分 ", 1),
                                  ((item.ai_flavor_reasons || []).length)
                                    ? (_openBlock(), _createElementBlock("span", _hoisted_22, " （" + _toDisplayString((item.ai_flavor_reasons || []).join('、')) + "） ", 1))
                                    : _createCommentVNode("", true),
                                  (item.similarity)
                                    ? (_openBlock(), _createElementBlock("span", _hoisted_23, " · 同季相似度 " + _toDisplayString(Math.round(item.similarity * 100)) + "%", 1))
                                    : _createCommentVNode("", true)
                                ]))
                              : _createCommentVNode("", true),
                            (item.new_title)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_24, " 新标题：" + _toDisplayString(item.new_title), 1))
                              : _createCommentVNode("", true)
                          ]),
                          _createElementVNode("td", null, [
                            (item.preview)
                              ? (_openBlock(), _createBlock(_component_VBtn, {
                                  key: 0,
                                  size: "x-small",
                                  variant: "tonal",
                                  color: "primary",
                                  disabled: running.value,
                                  loading: writingKey.value === String(item.key),
                                  onClick: $event => (writeSample(item))
                                }, {
                                  default: _withCtx(() => [...(_cache[32] || (_cache[32] = [
                                    _createTextVNode(" 写入此样张 ", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["disabled", "loading", "onClick"]))
                              : _createCommentVNode("", true),
                            _createVNode(_component_VBtn, {
                              size: "x-small",
                              variant: "text",
                              disabled: running.value,
                              loading: starting.value && writingKey.value !== String(item.key),
                              onClick: $event => (redoItem(item))
                            }, {
                              default: _withCtx(() => [...(_cache[33] || (_cache[33] = [
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
                _createElementVNode("div", _hoisted_25, " 样张只对前 " + _toDisplayString(previewSampled.value || 0) + " 条生成，不会写入媒体库；「写入此样张」会直接落库并记一次人工写入， 「重做」会强制重新生成该条。 ", 1)
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
                  default: _withCtx(() => [...(_cache[35] || (_cache[35] = [
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
                    _cache[36] || (_cache[36] = _createElementVNode("thead", null, [
                      _createElementVNode("tr", null, [
                        _createElementVNode("th", null, "类型"),
                        _createElementVNode("th", null, "标题"),
                        _createElementVNode("th", null, "集"),
                        _createElementVNode("th", null, "分类"),
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
                          _createElementVNode("td", null, [
                            _createVNode(_component_VChip, {
                              size: "x-small",
                              variant: "tonal",
                              color: "error"
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(failureKindLabels[row.error_kind] || row.error_kind || '未归类'), 1)
                              ]),
                              _: 2
                            }, 1024)
                          ]),
                          _createElementVNode("td", _hoisted_26, _toDisplayString(row.message), 1),
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
                  default: _withCtx(() => [...(_cache[37] || (_cache[37] = [
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
                    _cache[39] || (_cache[39] = _createElementVNode("thead", null, [
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
                          _createElementVNode("td", _hoisted_27, _toDisplayString(row.preview) + "（" + _toDisplayString(row.chars) + " 字）", 1),
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
                              default: _withCtx(() => [...(_cache[38] || (_cache[38] = [
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
          default: _withCtx(() => [...(_cache[40] || (_cache[40] = [
            _createTextVNode("最近日志", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_VCardText, { class: "moe-logs" }, {
          default: _withCtx(() => [
            (!(status.value.logs || []).length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_28, "暂无日志"))
              : _createCommentVNode("", true),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList((status.value.logs || []).slice().reverse(), (log, index) => {
              return (_openBlock(), _createElementBlock("div", {
                key: index,
                class: "moe-log-line"
              }, [
                _createElementVNode("span", _hoisted_29, "[" + _toDisplayString(log.time) + "]", 1),
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
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-52a197c0"]]);

export { AppPage as default };
