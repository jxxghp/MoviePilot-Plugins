import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const FILTERS = [
  { id: 'all', label: '全部资源' },
  { id: 'library', label: '媒体库已入库' },
  { id: 'hr', label: 'H&R 保护中' },
  { id: 'brush', label: '刷流任务' },
  { id: 'review', label: '无做种限制' },
  { id: 'names', label: '名称待核' },
];

const ACTIONS = {
  pause: {
    title: '停止做种',
    detail: '保留 qB 任务和全部文件',
  },
  retire: {
    title: '退出做种',
    detail: '移除 qB 任务，媒体仍保留',
  },
  delete: {
    title: '完整删除',
    detail: '移除任务、媒体和全部链接',
  },
};

function unwrapResponse(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

function createLatestPlanApi(api) {
  let generation = 0;
  let latestPlanResult = null;

  return {
    ...api,
    get(...args) {
      return api.get(...args)
    },
    post(path, body, ...args) {
      if (!String(path || '').endsWith('/plan')) {
        return api.post(path, body, ...args)
      }

      const requestGeneration = ++generation;
      let rawRequest;
      try {
        rawRequest = Promise.resolve(api.post(path, body, ...args));
      } catch (error) {
        rawRequest = Promise.reject(error);
      }

      const result = (async () => {
        try {
          const response = await rawRequest;
          if (requestGeneration !== generation && latestPlanResult) {
            return await latestPlanResult
          }
          return response
        } catch (error) {
          if (requestGeneration !== generation && latestPlanResult) {
            return await latestPlanResult
          }
          throw error
        }
      })();
      latestPlanResult = result;
      return result
    },
  }
}

function matchesFilter(item, filter) {
  if (filter === 'all') return true
  if (filter === 'library') return Boolean(item.library)
  if (filter === 'hr') return Boolean(item.hr || item.hrPending)
  if (filter === 'brush') return Boolean(item.brush)
  if (filter === 'review') return !item.protected && item.qbSummary === '无 qB 任务'
  return item.metadataVerified === false
}

function isDirectlyCleanable(item) {
  return !item.protected && item.qbSummary === '无 qB 任务'
}

function filterResources(resources, { filter, search, safeOnly, descending }) {
  const query = String(search || '').trim().toLowerCase();
  return [...(resources || [])]
    .filter(item => {
      const text = `${item.title || ''} ${item.englishTitle || ''} ${item.edition || ''} ${item.siteSummary || ''}`.toLowerCase();
      return matchesFilter(item, filter) &&
        (!safeOnly || isDirectlyCleanable(item)) &&
        (!query || text.includes(query))
    })
    .sort((left, right) => {
      const order = descending ? Number(right.size || 0) - Number(left.size || 0) : Number(left.size || 0) - Number(right.size || 0);
      return order || String(left.title || '').localeCompare(String(right.title || ''), 'zh-CN')
    })
}

function formatGiB(size) {
  const numeric = Number(size || 0);
  return numeric >= 1024 ? `${(numeric / 1024).toFixed(2)} TB` : `${numeric.toFixed(1)} GB`
}

function formatBytes(size) {
  return formatGiB(Number(size || 0) / 1024 ** 3)
}

function issueKey(issue, index) {
  return `${issue?.code || 'issue'}-${index}`
}

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,normalizeClass:_normalizeClass,vModelText:_vModelText,withDirectives:_withDirectives,vModelCheckbox:_vModelCheckbox,createTextVNode:_createTextVNode,renderList:_renderList,Fragment:_Fragment,unref:_unref,withModifiers:_withModifiers,Teleport:_Teleport,createBlock:_createBlock} = await importShared('vue');


const _hoisted_1 = { class: "cleanup-app" };
const _hoisted_2 = {
  key: 0,
  class: "page-header"
};
const _hoisted_3 = { key: 0 };
const _hoisted_4 = { class: "toolbar" };
const _hoisted_5 = { class: "search" };
const _hoisted_6 = { class: "safe-toggle" };
const _hoisted_7 = ["disabled"];
const _hoisted_8 = {
  class: "filters",
  "aria-label": "资源筛选"
};
const _hoisted_9 = ["onClick"];
const _hoisted_10 = { class: "resource-card" };
const _hoisted_11 = { class: "table-head" };
const _hoisted_12 = {
  key: 0,
  class: "empty-state"
};
const _hoisted_13 = ["disabled", "onClick"];
const _hoisted_14 = { class: "resource-title" };
const _hoisted_15 = {
  class: "stack-cell library",
  "data-label": "媒体库"
};
const _hoisted_16 = {
  class: "seed-cell",
  "data-label": "做种与保护"
};
const _hoisted_17 = {
  key: 1,
  class: "stack-cell"
};
const _hoisted_18 = {
  class: "stack-cell size",
  "data-label": "实际占用"
};
const _hoisted_19 = {
  key: 2,
  class: "empty-state"
};
const _hoisted_20 = {
  key: 0,
  class: "action-bar"
};
const _hoisted_21 = { class: "selected-count" };
const _hoisted_22 = { class: "action-buttons" };
const _hoisted_23 = ["onClick"];
const _hoisted_24 = {
  class: "modal plan-modal",
  role: "dialog",
  "aria-modal": "true"
};
const _hoisted_25 = ["disabled"];
const _hoisted_26 = { key: 0 };
const _hoisted_27 = { key: 1 };
const _hoisted_28 = { class: "plan-resources" };
const _hoisted_29 = {
  key: 0,
  class: "plan-state"
};
const _hoisted_30 = {
  key: 1,
  class: "plan-state blocked"
};
const _hoisted_31 = {
  key: 0,
  class: "issues blocked"
};
const _hoisted_32 = {
  key: 1,
  class: "issues warning"
};
const _hoisted_33 = {
  key: 2,
  class: "risk-check"
};
const _hoisted_34 = ["checked"];
const _hoisted_35 = {
  key: 3,
  class: "plan-state blocked"
};
const _hoisted_36 = { class: "safety-note" };
const _hoisted_37 = {
  key: 3,
  class: "execution-result"
};
const _hoisted_38 = {
  key: 4,
  class: "final-confirmation"
};
const _hoisted_39 = {
  key: 0,
  class: "error-text"
};
const _hoisted_40 = ["disabled"];
const _hoisted_41 = ["disabled"];
const _hoisted_42 = ["disabled"];
const _hoisted_43 = { class: "modal compact-modal" };
const _hoisted_44 = {
  key: 0,
  class: "empty-state"
};
const _hoisted_45 = {
  key: 1,
  class: "plan-state blocked"
};
const _hoisted_46 = { class: "modal compact-modal" };
const _hoisted_47 = {
  key: 0,
  class: "empty-state"
};
const _hoisted_48 = {
  key: 1,
  class: "plan-state blocked"
};
const _hoisted_49 = ["onClick"];
const _hoisted_50 = ["onClick"];
const _hoisted_51 = {
  key: 2,
  class: "recovery-confirm"
};
const _hoisted_52 = ["disabled"];

const {computed,onMounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'AppPage',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'StorageCleanup' },
  hideTitle: { type: Boolean, default: false },
},
  setup(__props) {

const props = __props;

const emptySnapshot = {
  schemaVersion: 2,
  snapshotId: '',
  generatedAt: '',
  stats: {},
  resources: [],
};

const snapshot = ref(emptySnapshot);
const health = ref({});
const loading = ref(true);
const refreshing = ref(false);
const error = ref('');
const search = ref('');
const activeFilter = ref('all');
const safeOnly = ref(false);
const descending = ref(true);
const selected = ref([]);

const planOpen = ref(false);
const planMode = ref(null);
const plan = ref(null);
const planLoading = ref(false);
const planError = ref('');
const acknowledgeSiteRisk = ref(false);
const finalConfirmation = ref(false);
const executing = ref(false);
const executeError = ref('');
const executeResult = ref(null);

const gapOpen = ref(false);
const gapLoading = ref(false);
const gaps = ref([]);
const gapError = ref('');

const recoveryOpen = ref(false);
const recoveryLoading = ref(false);
const recoveries = ref([]);
const recoveryError = ref('');
const recoveryTarget = ref(null);
const recoveryAction = ref(null);
const recoveryPhrase = ref('');
const recovering = ref(false);

const pluginBase = computed(() => `plugin/${props.pluginId || 'StorageCleanup'}`);
const resources = computed(() => snapshot.value.resources || []);
const visible = computed(() => filterResources(resources.value, {
  filter: activeFilter.value,
  search: search.value,
  safeOnly: safeOnly.value,
  descending: descending.value,
}));
const selectedItems = computed(() => resources.value.filter(item => selected.value.includes(item.id)));
const selectedSize = computed(() => selectedItems.value.reduce((total, item) => total + Number(item.size || 0), 0));
const executionEnabled = computed(() => Boolean(health.value.executionEnabled));
const inventoryCurrent = computed(() => health.value.inventoryCurrent !== false);
const unresolvedTransactions = computed(() => Number(snapshot.value.stats?.unresolvedTransactions || 0));
const hrGap = computed(() => Math.max(
  0,
  Number(
    snapshot.value.stats?.hrMissingQbTasks ??
    Number(snapshot.value.stats?.hrActiveTitles || 0) - Number(snapshot.value.stats?.hrMatchedQbTasks || 0),
  ),
));
const hrUnassigned = computed(() => Number(
  snapshot.value.stats?.hrMissingUnassigned ??
  snapshot.value.stats?.hrMissingUncovered ??
  0,
));
const filters = computed(() => FILTERS.map(filter => ({
  ...filter,
  count: resources.value.filter(item => {
    if (filter.id === 'all') return true
    return filterResources([item], {
      filter: filter.id,
      search: '',
      safeOnly: false,
      descending: true,
    }).length === 1
  }).length,
})));
const allVisibleSelected = computed(() => {
  const selectable = visible.value.filter(item => !item.protected);
  return selectable.length > 0 && selectable.every(item => selected.value.includes(item.id))
});
const currentAction = computed(() => planMode.value ? ACTIONS[planMode.value] : null);
const planExpired = computed(() => Boolean(plan.value && Date.parse(plan.value.expiresAt) <= Date.now()));

function payloadError(payload, fallback) {
  return payload?.error?.message || fallback
}

async function get(path) {
  return unwrapResponse(await props.api.get(`${pluginBase.value}${path}`))
}

async function post(path, body) {
  return unwrapResponse(await props.api.post(`${pluginBase.value}${path}`, body))
}

function acceptSnapshot(next) {
  if (!next || next.schemaVersion !== 2 || !next.snapshotId || !Array.isArray(next.resources)) {
    throw new Error('资源快照格式不受支持。')
  }
  snapshot.value = next;
  const available = new Set(next.resources.map(item => item.id));
  selected.value = selected.value.filter(id => available.has(id));
}

async function loadStatus() {
  loading.value = true;
  error.value = '';
  try {
    const payload = await get('/status');
    if (!payload?.ok || !payload.snapshot) throw new Error(payloadError(payload, '无法读取清理台状态。'))
    health.value = payload.health || {};
    acceptSnapshot(payload.snapshot);
  } catch (err) {
    error.value = err?.message || '无法读取清理台状态。';
  } finally {
    loading.value = false;
  }
}

async function refreshSnapshot() {
  refreshing.value = true;
  error.value = '';
  try {
    const payload = await post('/refresh', {});
    if (!payload?.ok || !payload.snapshot) throw new Error(payloadError(payload, '刷新失败。'))
    acceptSnapshot(payload.snapshot);
    health.value = { ...health.value, inventoryCurrent: true };
  } catch (err) {
    error.value = err?.message || '刷新失败，继续显示上次快照。';
    health.value = { ...health.value, inventoryCurrent: false };
  } finally {
    refreshing.value = false;
  }
}

function toggle(item) {
  if (item.protected) return
  selected.value = selected.value.includes(item.id)
    ? selected.value.filter(id => id !== item.id)
    : [...selected.value, item.id];
}

function toggleVisible() {
  const ids = visible.value.filter(item => !item.protected).map(item => item.id);
  selected.value = allVisibleSelected.value
    ? selected.value.filter(id => !ids.includes(id))
    : [...new Set([...selected.value, ...ids])];
}

async function requestPlan(mode, acknowledged = false) {
  planLoading.value = true;
  planError.value = '';
  plan.value = null;
  finalConfirmation.value = false;
  try {
    const payload = await post('/plan', {
      snapshotId: snapshot.value.snapshotId,
      resourceIds: selected.value,
      mode,
      acknowledgeSiteRisk: acknowledged,
    });
    if (!payload?.ok || !payload.plan) throw new Error(payloadError(payload, '无法生成执行计划。'))
    plan.value = payload.plan;
  } catch (err) {
    planError.value = err?.message || '无法生成执行计划。';
  } finally {
    planLoading.value = false;
  }
}

function openPlan(mode) {
  planMode.value = mode;
  planOpen.value = true;
  acknowledgeSiteRisk.value = false;
  executeResult.value = null;
  executeError.value = '';
  requestPlan(mode, false);
}

function closePlan() {
  if (executing.value) return
  planOpen.value = false;
  planMode.value = null;
  plan.value = null;
  planError.value = '';
  finalConfirmation.value = false;
  executeResult.value = null;
}

async function setSiteRisk(value) {
  acknowledgeSiteRisk.value = value;
  await requestPlan(planMode.value, value);
}

async function executePlan() {
  if (!plan.value || planExpired.value || executing.value) return
  executing.value = true;
  executeError.value = '';
  try {
    const payload = await post('/execute', {
      planId: plan.value.planId,
      confirmPhrase: plan.value.confirmPhrase,
    });
    if (!payload?.ok || !payload.result) {
      if (payload?.error?.plan) plan.value = payload.error.plan;
      throw new Error(payloadError(payload, '执行失败。'))
    }
    executeResult.value = payload.result;
    selected.value = [];
    if (payload.result.snapshotRefreshPending) {
      health.value = { ...health.value, inventoryCurrent: false };
    } else {
      const latest = await get('/snapshot');
      if (latest?.snapshot) acceptSnapshot(latest.snapshot);
    }
  } catch (err) {
    executeError.value = err?.message || '执行失败。';
    finalConfirmation.value = false;
  } finally {
    executing.value = false;
  }
}

async function loadGaps() {
  gapOpen.value = true;
  gapLoading.value = true;
  gapError.value = '';
  try {
    const payload = await get('/protection-gaps');
    if (!payload?.ok) throw new Error(payloadError(payload, '无法读取 H&R 缺口。'))
    gaps.value = payload.gaps || [];
  } catch (err) {
    gapError.value = err?.message || '无法读取 H&R 缺口。';
  } finally {
    gapLoading.value = false;
  }
}

async function loadRecoveries() {
  recoveryOpen.value = true;
  recoveryLoading.value = true;
  recoveryError.value = '';
  recoveryTarget.value = null;
  try {
    const payload = await get('/recovery');
    if (!payload?.ok) throw new Error(payloadError(payload, '无法读取恢复状态。'))
    recoveries.value = payload.recoveries || [];
  } catch (err) {
    recoveryError.value = err?.message || '无法读取恢复状态。';
  } finally {
    recoveryLoading.value = false;
  }
}

function chooseRecovery(item, action) {
  recoveryTarget.value = item;
  recoveryAction.value = action;
  recoveryPhrase.value = '';
  recoveryError.value = '';
}

async function runRecovery() {
  if (!recoveryTarget.value || !recoveryAction.value || recovering.value) return
  recovering.value = true;
  recoveryError.value = '';
  try {
    const payload = await post('/recovery', {
      planId: recoveryTarget.value.planId,
      action: recoveryAction.value,
      confirmPhrase: recoveryPhrase.value,
    });
    if (!payload?.ok) throw new Error(payloadError(payload, '恢复操作失败。'))
    await refreshSnapshot();
    await loadRecoveries();
  } catch (err) {
    recoveryError.value = err?.message || '恢复操作失败。';
  } finally {
    recovering.value = false;
  }
}

function recoveryExpectedPhrase() {
  if (!recoveryTarget.value || !recoveryAction.value) return ''
  return recoveryAction.value === 'rollback'
    ? recoveryTarget.value.rollbackPhrase
    : recoveryTarget.value.finalizePhrase
}

onMounted(loadStatus);

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("main", _hoisted_1, [
    (!__props.hideTitle)
      ? (_openBlock(), _createElementBlock("header", _hoisted_2, [
          _cache[12] || (_cache[12] = _createElementVNode("div", null, [
            _createElementVNode("p", { class: "eyebrow" }, "PiNAS · MoviePilot 原生页面"),
            _createElementVNode("h1", null, "存储清理"),
            _createElementVNode("span", null, "一部电影一行，一部剧一行；先看清影响，再选择清理等级。")
          ], -1)),
          _createElementVNode("div", {
            class: _normalizeClass(['status-card', { danger: error.value || !inventoryCurrent.value }])
          }, [
            _createElementVNode("i", null, _toDisplayString(error.value || !inventoryCurrent.value ? '!' : '✓'), 1),
            _createElementVNode("p", null, [
              _createElementVNode("strong", null, _toDisplayString(error.value || (executionEnabled.value ? '执行链路已连接' : '只读模式')), 1),
              (snapshot.value.generatedAt)
                ? (_openBlock(), _createElementBlock("span", _hoisted_3, "更新于 " + _toDisplayString(snapshot.value.generatedAt.slice(5, 16).replace('T', ' ')), 1))
                : _createCommentVNode("", true)
            ])
          ], 2)
        ]))
      : _createCommentVNode("", true),
    _createElementVNode("section", _hoisted_4, [
      _createElementVNode("label", _hoisted_5, [
        _cache[13] || (_cache[13] = _createElementVNode("span", null, "⌕", -1)),
        _withDirectives(_createElementVNode("input", {
          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((search).value = $event)),
          "aria-label": "搜索资源",
          placeholder: "搜索电影、剧集、季度或站点"
        }, null, 512), [
          [_vModelText, search.value]
        ])
      ]),
      _createElementVNode("label", _hoisted_6, [
        _withDirectives(_createElementVNode("input", {
          "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((safeOnly).value = $event)),
          type: "checkbox"
        }, null, 512), [
          [_vModelCheckbox, safeOnly.value]
        ]),
        _cache[14] || (_cache[14] = _createElementVNode("span", null, null, -1)),
        _cache[15] || (_cache[15] = _createTextVNode(" 仅看无做种限制 ", -1))
      ]),
      _createElementVNode("button", {
        class: "soft-button",
        type: "button",
        onClick: _cache[2] || (_cache[2] = $event => (descending.value = !descending.value))
      }, " 实际占用 " + _toDisplayString(descending.value ? '↓' : '↑'), 1),
      _createElementVNode("button", {
        class: "icon-button",
        type: "button",
        disabled: refreshing.value,
        onClick: refreshSnapshot
      }, _toDisplayString(refreshing.value ? '…' : '↻'), 9, _hoisted_7)
    ]),
    (unresolvedTransactions.value)
      ? (_openBlock(), _createElementBlock("button", {
          key: 1,
          class: "notice critical",
          type: "button",
          onClick: loadRecoveries
        }, [
          _cache[17] || (_cache[17] = _createElementVNode("i", null, "!", -1)),
          _createElementVNode("p", null, [
            _createElementVNode("strong", null, _toDisplayString(unresolvedTransactions.value) + " 个未完成清理事务", 1),
            _cache[16] || (_cache[16] = _createElementVNode("span", null, "新操作已锁定；请先核对并恢复原事务。", -1))
          ]),
          _cache[18] || (_cache[18] = _createElementVNode("b", null, "查看恢复状态", -1))
        ]))
      : (hrGap.value)
        ? (_openBlock(), _createElementBlock("button", {
            key: 2,
            class: _normalizeClass(['notice', { warning: hrUnassigned.value }]),
            type: "button",
            onClick: loadGaps
          }, [
            _cache[19] || (_cache[19] = _createElementVNode("i", null, "H", -1)),
            _createElementVNode("p", null, [
              _createElementVNode("strong", null, _toDisplayString(hrGap.value) + " 个学校站 H&R 尚未恢复完成", 1),
              _createElementVNode("span", null, _toDisplayString(hrUnassigned.value
            ? `${hrUnassigned.value} 个未精确关联媒体；不会锁定无关资源。`
            : '缺失任务只锁定精确关联资源，其他资源可独立清理。'), 1)
            ]),
            _cache[20] || (_cache[20] = _createElementVNode("b", null, "查看明细", -1))
          ], 2))
        : _createCommentVNode("", true),
    _createElementVNode("nav", _hoisted_8, [
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(filters.value, (filter) => {
        return (_openBlock(), _createElementBlock("button", {
          key: filter.id,
          class: _normalizeClass({ active: activeFilter.value === filter.id }),
          type: "button",
          onClick: $event => (activeFilter.value = filter.id)
        }, [
          _createTextVNode(_toDisplayString(filter.label) + " ", 1),
          _createElementVNode("span", null, _toDisplayString(filter.count), 1)
        ], 10, _hoisted_9))
      }), 128))
    ]),
    _createElementVNode("section", _hoisted_10, [
      _createElementVNode("div", _hoisted_11, [
        _createElementVNode("button", {
          class: "select-all",
          type: "button",
          onClick: toggleVisible
        }, _toDisplayString(allVisibleSelected.value ? '✓' : ''), 1),
        _cache[21] || (_cache[21] = _createElementVNode("span", null, "资源", -1)),
        _cache[22] || (_cache[22] = _createElementVNode("span", null, "媒体库", -1)),
        _cache[23] || (_cache[23] = _createElementVNode("span", null, "做种与保护", -1)),
        _cache[24] || (_cache[24] = _createElementVNode("span", null, "实际占用", -1)),
        _cache[25] || (_cache[25] = _createElementVNode("span", null, "完整删除影响", -1))
      ]),
      (loading.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_12, "正在读取真实资源关系…"))
        : (_openBlock(true), _createElementBlock(_Fragment, { key: 1 }, _renderList(visible.value, (item) => {
            return (_openBlock(), _createElementBlock("article", {
              key: item.id,
              class: _normalizeClass(['resource-row', { selected: selected.value.includes(item.id) }])
            }, [
              _createElementVNode("button", {
                class: _normalizeClass(['row-check', { locked: item.protected }]),
                type: "button",
                disabled: item.protected,
                onClick: $event => (toggle(item))
              }, _toDisplayString(item.protected ? '锁' : selected.value.includes(item.id) ? '✓' : ''), 11, _hoisted_13),
              _createElementVNode("div", _hoisted_14, [
                _createElementVNode("strong", null, _toDisplayString(item.title), 1),
                _createElementVNode("b", null, _toDisplayString(item.englishTitle), 1),
                _createElementVNode("span", null, _toDisplayString([item.type, item.year, item.edition].filter(Boolean).join(' · ')), 1)
              ]),
              _createElementVNode("div", _hoisted_15, [
                _createElementVNode("strong", null, _toDisplayString(item.librarySummary), 1),
                _createElementVNode("span", null, _toDisplayString(item.libraryDetail), 1)
              ]),
              _createElementVNode("div", _hoisted_16, [
                (item.seedTasks?.length)
                  ? (_openBlock(true), _createElementBlock(_Fragment, { key: 0 }, _renderList(item.seedTasks, (task, index) => {
                      return (_openBlock(), _createElementBlock("div", {
                        key: `${task.site}-${task.scope}-${index}`,
                        class: _normalizeClass(['seed-task', task.tone])
                      }, [
                        _createElementVNode("i", null, _toDisplayString(task.status), 1),
                        _createElementVNode("strong", null, _toDisplayString(task.site), 1),
                        _createElementVNode("span", null, _toDisplayString(task.scope) + _toDisplayString(task.count > 1 ? ` · ${task.count} 个任务` : ''), 1)
                      ], 2))
                    }), 128))
                  : (_openBlock(), _createElementBlock("div", _hoisted_17, [
                      _createElementVNode("strong", null, _toDisplayString(item.qbSummary), 1),
                      _createElementVNode("span", null, _toDisplayString(item.siteSummary), 1)
                    ]))
              ]),
              _createElementVNode("div", _hoisted_18, [
                _createElementVNode("strong", null, _toDisplayString(item.sizeLabel), 1),
                _createElementVNode("span", null, _toDisplayString(item.reclaimLabel), 1)
              ]),
              _createElementVNode("div", {
                class: _normalizeClass(['impact', { danger: item.protected }]),
                "data-label": "完整删除影响"
              }, [
                _createElementVNode("strong", null, _toDisplayString(item.impactTitle), 1),
                _createElementVNode("span", null, _toDisplayString(item.impactDetail), 1)
              ], 2)
            ], 2))
          }), 128)),
      (!loading.value && !visible.value.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_19, " 没有符合条件的资源，请取消筛选或更换关键词。 "))
        : _createCommentVNode("", true)
    ]),
    (_openBlock(), _createBlock(_Teleport, { to: "body" }, [
      (selected.value.length)
        ? (_openBlock(), _createElementBlock("aside", _hoisted_20, [
            _createElementVNode("div", _hoisted_21, _toDisplayString(selected.value.length), 1),
            _createElementVNode("p", null, [
              _cache[26] || (_cache[26] = _createElementVNode("strong", null, "已加入清理计划", -1)),
              _createElementVNode("span", null, "完整删除上限 " + _toDisplayString(_unref(formatGiB)(selectedSize.value)), 1)
            ]),
            _createElementVNode("button", {
              class: "clear-button",
              type: "button",
              onClick: _cache[3] || (_cache[3] = $event => (selected.value = []))
            }, "清空"),
            _createElementVNode("div", _hoisted_22, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_unref(ACTIONS), (action, mode) => {
                return (_openBlock(), _createElementBlock("button", {
                  key: mode,
                  class: _normalizeClass(['action-level', { delete: mode === 'delete' }]),
                  type: "button",
                  onClick: $event => (openPlan(mode))
                }, [
                  _createElementVNode("strong", null, _toDisplayString(action.title), 1),
                  _createElementVNode("span", null, _toDisplayString(action.detail), 1)
                ], 10, _hoisted_23))
              }), 128))
            ])
          ]))
        : _createCommentVNode("", true),
      (planOpen.value)
        ? (_openBlock(), _createElementBlock("div", {
            key: 1,
            class: "modal-backdrop",
            onClick: _withModifiers(closePlan, ["self"])
          }, [
            _createElementVNode("section", _hoisted_24, [
              _createElementVNode("header", null, [
                _createElementVNode("div", null, [
                  _cache[27] || (_cache[27] = _createElementVNode("span", null, "清理等级 · 真实预演", -1)),
                  _createElementVNode("h2", null, _toDisplayString(currentAction.value?.title), 1)
                ]),
                _createElementVNode("button", {
                  type: "button",
                  disabled: executing.value,
                  onClick: closePlan
                }, "×", 8, _hoisted_25)
              ]),
              _createElementVNode("div", {
                class: _normalizeClass(['mode-summary', planMode.value])
              }, [
                (plan.value && planMode.value === 'delete')
                  ? (_openBlock(), _createElementBlock("strong", _hoisted_26, "已核算可释放 " + _toDisplayString(_unref(formatBytes)(plan.value.estimatedReclaimBytes)), 1))
                  : (_openBlock(), _createElementBlock("strong", _hoisted_27, _toDisplayString(currentAction.value?.detail), 1)),
                _createElementVNode("span", null, _toDisplayString(planMode.value === 'pause'
              ? '只改变 qB 运行状态，不删除任务或文件。'
              : planMode.value === 'retire'
                ? '移除 qB 任务但保留文件，媒体库继续可播放。'
                : '仅当全部路径、硬链接、H&R 与任务状态通过校验才会放行。'), 1)
              ], 2),
              _createElementVNode("div", _hoisted_28, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(selectedItems.value, (item) => {
                  return (_openBlock(), _createElementBlock("div", {
                    key: item.id
                  }, [
                    _createElementVNode("p", null, [
                      _createElementVNode("strong", null, _toDisplayString(item.title), 1),
                      _createElementVNode("span", null, _toDisplayString(item.englishTitle) + " · " + _toDisplayString(item.edition), 1)
                    ]),
                    _createElementVNode("b", null, _toDisplayString(item.sizeLabel), 1)
                  ]))
                }), 128))
              ]),
              (planLoading.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_29, "正在刷新 NAS 状态并复核关系…"))
                : (planError.value)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_30, [
                      _cache[28] || (_cache[28] = _createElementVNode("strong", null, "无法生成计划", -1)),
                      _createElementVNode("span", null, _toDisplayString(planError.value), 1)
                    ]))
                  : (plan.value)
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                        _createElementVNode("div", {
                          class: _normalizeClass(['plan-state', plan.value.canExecute ? 'passed' : 'blocked'])
                        }, [
                          _createElementVNode("strong", null, _toDisplayString(plan.value.canExecute ? '安全预演通过' : '计划已被安全门禁拦截'), 1),
                          _createElementVNode("span", null, " 停止 " + _toDisplayString(plan.value.operationCounts.qbStop) + " 个任务 · 退出 " + _toDisplayString(plan.value.operationCounts.qbRemoveKeepFiles) + " 个任务 · 解除 " + _toDisplayString(plan.value.operationCounts.unlinkFiles) + " 个文件入口 ", 1)
                        ], 2),
                        (plan.value.blocks?.length)
                          ? (_openBlock(), _createElementBlock("ul", _hoisted_31, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(plan.value.blocks, (issue, index) => {
                                return (_openBlock(), _createElementBlock("li", {
                                  key: _unref(issueKey)(issue, index)
                                }, _toDisplayString(issue.message), 1))
                              }), 128))
                            ]))
                          : _createCommentVNode("", true),
                        (plan.value.warnings?.length)
                          ? (_openBlock(), _createElementBlock("ul", _hoisted_32, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(plan.value.warnings, (issue, index) => {
                                return (_openBlock(), _createElementBlock("li", {
                                  key: _unref(issueKey)(issue, index)
                                }, _toDisplayString(issue.message), 1))
                              }), 128))
                            ]))
                          : _createCommentVNode("", true),
                        (plan.value.requiresSiteAcknowledgement)
                          ? (_openBlock(), _createElementBlock("label", _hoisted_33, [
                              _createElementVNode("input", {
                                checked: acknowledgeSiteRisk.value,
                                type: "checkbox",
                                onChange: _cache[4] || (_cache[4] = $event => (setSiteRisk($event.target.checked)))
                              }, null, 40, _hoisted_34),
                              _cache[29] || (_cache[29] = _createElementVNode("span", null, null, -1)),
                              _cache[30] || (_cache[30] = _createTextVNode(" 我已确认会影响私有站做种，并接受站点规则风险 ", -1))
                            ]))
                          : _createCommentVNode("", true),
                        (planExpired.value)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_35, [...(_cache[31] || (_cache[31] = [
                              _createElementVNode("strong", null, "安全预演已过期", -1),
                              _createElementVNode("span", null, "请关闭后重新生成。", -1)
                            ]))]))
                          : _createCommentVNode("", true)
                      ], 64))
                    : _createCommentVNode("", true),
              _createElementVNode("div", _hoisted_36, [
                _cache[33] || (_cache[33] = _createElementVNode("i", null, "盾", -1)),
                _createElementVNode("p", null, [
                  _createElementVNode("strong", null, _toDisplayString(executionEnabled.value ? '执行前还需第二次确认' : '执行引擎未启用'), 1),
                  _cache[32] || (_cache[32] = _createElementVNode("span", null, "最终执行前会重新读取 qB、路径、硬链接和保护状态。", -1))
                ])
              ]),
              (executeResult.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_37, [
                    _createElementVNode("strong", null, _toDisplayString(currentAction.value?.title) + "已完成", 1),
                    _createElementVNode("span", null, " 停止 " + _toDisplayString(executeResult.value.qbStopped) + " · 退出 " + _toDisplayString(executeResult.value.qbRemoved) + " · 删除文件入口 " + _toDisplayString(executeResult.value.filesDeleted) + " · 清理索引 " + _toDisplayString(executeResult.value.moviepilotIndexesDeleted), 1),
                    _createElementVNode("button", {
                      type: "button",
                      onClick: closePlan
                    }, "完成")
                  ]))
                : (finalConfirmation.value)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_38, [
                      _cache[34] || (_cache[34] = _createElementVNode("strong", null, "再次确认：系统将立即执行这份计划", -1)),
                      (executeError.value)
                        ? (_openBlock(), _createElementBlock("span", _hoisted_39, _toDisplayString(executeError.value), 1))
                        : _createCommentVNode("", true),
                      _createElementVNode("div", null, [
                        _createElementVNode("button", {
                          type: "button",
                          disabled: executing.value,
                          onClick: _cache[5] || (_cache[5] = $event => (finalConfirmation.value = false))
                        }, "返回", 8, _hoisted_40),
                        _createElementVNode("button", {
                          class: _normalizeClass({ danger: planMode.value === 'delete' }),
                          type: "button",
                          disabled: executing.value || planExpired.value,
                          onClick: executePlan
                        }, _toDisplayString(executing.value ? '正在二次复核…' : `确认${currentAction.value?.title}`), 11, _hoisted_41)
                      ])
                    ]))
                  : (_openBlock(), _createElementBlock("button", {
                      key: 5,
                      class: "confirm-button",
                      type: "button",
                      disabled: !executionEnabled.value || !plan.value?.canExecute || planExpired.value,
                      onClick: _cache[6] || (_cache[6] = $event => (finalConfirmation.value = true))
                    }, " 进入最终确认 ", 8, _hoisted_42))
            ])
          ]))
        : _createCommentVNode("", true),
      (gapOpen.value)
        ? (_openBlock(), _createElementBlock("div", {
            key: 2,
            class: "modal-backdrop",
            onClick: _cache[8] || (_cache[8] = _withModifiers($event => (gapOpen.value = false), ["self"]))
          }, [
            _createElementVNode("section", _hoisted_43, [
              _createElementVNode("header", null, [
                _cache[35] || (_cache[35] = _createElementVNode("div", null, [
                  _createElementVNode("span", null, "学校站实时保护"),
                  _createElementVNode("h2", null, "H&R 缺口明细")
                ], -1)),
                _createElementVNode("button", {
                  onClick: _cache[7] || (_cache[7] = $event => (gapOpen.value = false))
                }, "×")
              ]),
              (gapLoading.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_44, "正在核对…"))
                : _createCommentVNode("", true),
              (gapError.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_45, _toDisplayString(gapError.value), 1))
                : _createCommentVNode("", true),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(gaps.value, (item) => {
                return (_openBlock(), _createElementBlock("div", {
                  key: item.title,
                  class: "gap-row"
                }, [
                  _createElementVNode("p", null, [
                    _createElementVNode("strong", null, _toDisplayString(item.title), 1),
                    _createElementVNode("span", null, _toDisplayString(item.linkedResourceTitle || '尚未精确关联媒体'), 1)
                  ]),
                  _createElementVNode("b", null, _toDisplayString(item.qbTaskPresent ? 'qB 已存在' : item.coveredByCandidate ? '候选恢复中' : '任务缺失'), 1)
                ]))
              }), 128))
            ])
          ]))
        : _createCommentVNode("", true),
      (recoveryOpen.value)
        ? (_openBlock(), _createElementBlock("div", {
            key: 3,
            class: "modal-backdrop",
            onClick: _cache[11] || (_cache[11] = _withModifiers($event => (recoveryOpen.value = false), ["self"]))
          }, [
            _createElementVNode("section", _hoisted_46, [
              _createElementVNode("header", null, [
                _cache[36] || (_cache[36] = _createElementVNode("div", null, [
                  _createElementVNode("span", null, "失败关闭"),
                  _createElementVNode("h2", null, "恢复未完成清理")
                ], -1)),
                _createElementVNode("button", {
                  onClick: _cache[9] || (_cache[9] = $event => (recoveryOpen.value = false))
                }, "×")
              ]),
              (recoveryLoading.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_47, "正在读取事务…"))
                : _createCommentVNode("", true),
              (recoveryError.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_48, _toDisplayString(recoveryError.value), 1))
                : _createCommentVNode("", true),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(recoveries.value, (item) => {
                return (_openBlock(), _createElementBlock("div", {
                  key: item.planId,
                  class: "recovery-row"
                }, [
                  _createElementVNode("p", null, [
                    _createElementVNode("strong", null, _toDisplayString(item.mode) + " · " + _toDisplayString(item.phase), 1),
                    _createElementVNode("span", null, _toDisplayString(item.planId.slice(-10)), 1)
                  ]),
                  _createElementVNode("button", {
                    type: "button",
                    onClick: $event => (chooseRecovery(item, 'rollback'))
                  }, "回滚", 8, _hoisted_49),
                  _createElementVNode("button", {
                    type: "button",
                    onClick: $event => (chooseRecovery(item, 'finalize'))
                  }, "完成原事务", 8, _hoisted_50)
                ]))
              }), 128)),
              (recoveryTarget.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_51, [
                    _createElementVNode("label", null, [
                      _cache[37] || (_cache[37] = _createTextVNode("输入确认短语 ", -1)),
                      _createElementVNode("code", null, _toDisplayString(recoveryExpectedPhrase()), 1)
                    ]),
                    _withDirectives(_createElementVNode("input", {
                      "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((recoveryPhrase).value = $event)),
                      autocomplete: "off"
                    }, null, 512), [
                      [_vModelText, recoveryPhrase.value]
                    ]),
                    _createElementVNode("button", {
                      type: "button",
                      disabled: recovering.value || recoveryPhrase.value !== recoveryExpectedPhrase(),
                      onClick: runRecovery
                    }, _toDisplayString(recovering.value ? '处理中…' : '执行恢复'), 9, _hoisted_52)
                  ]))
                : _createCommentVNode("", true)
            ])
          ]))
        : _createCommentVNode("", true)
    ]))
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-55ee4f66"]]);

export { createLatestPlanApi as c, AppPage as default };
