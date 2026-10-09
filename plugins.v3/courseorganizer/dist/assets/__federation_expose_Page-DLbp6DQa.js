import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,resolveComponent:_resolveComponent,createVNode:_createVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createBlock:_createBlock,withModifiers:_withModifiers,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = {
  class: "course-review-page",
  "aria-labelledby": "course-review-title"
};
const _hoisted_2 = { class: "course-review-toolbar" };
const _hoisted_3 = { class: "text-body-2 text-medium-emphasis mt-1" };
const _hoisted_4 = { class: "course-review-toolbar__actions" };
const _hoisted_5 = { class: "flex-grow-1" };
const _hoisted_6 = { class: "text-body-2 font-weight-medium" };
const _hoisted_7 = { class: "text-caption text-medium-emphasis" };
const _hoisted_8 = { key: 0 };
const _hoisted_9 = {
  key: 0,
  class: "course-directory-rules mb-3"
};
const _hoisted_10 = { class: "d-flex align-center flex-wrap ga-2 mb-1" };
const _hoisted_11 = { class: "text-body-2" };
const _hoisted_12 = { class: "text-caption text-medium-emphasis text-break" };
const _hoisted_13 = { class: "text-body-2 text-medium-emphasis flex-grow-1" };
const _hoisted_14 = { class: "course-review-select-column" };
const _hoisted_15 = { class: "course-review-name" };
const _hoisted_16 = { class: "course-review-edit-cell" };
const _hoisted_17 = {
  key: 1,
  role: "status",
  "aria-live": "polite",
  class: "text-caption text-medium-emphasis mt-1"
};
const _hoisted_18 = {
  key: 2,
  class: "text-caption text-medium-emphasis mt-1"
};
const _hoisted_19 = { class: "course-review-library-cell" };
const _hoisted_20 = { class: "text-caption text-medium-emphasis mt-1 text-break" };
const _hoisted_21 = { class: "course-review-actions text-right" };
const _hoisted_22 = {
  key: 10,
  class: "course-review-cards"
};
const _hoisted_23 = { class: "text-break" };
const _hoisted_24 = {
  key: 1,
  role: "status",
  "aria-live": "polite",
  class: "text-caption text-medium-emphasis mb-2"
};
const _hoisted_25 = {
  key: 3,
  class: "text-caption text-medium-emphasis mb-1"
};
const _hoisted_26 = { class: "text-caption text-medium-emphasis mt-n3 mb-3 text-break" };
const _hoisted_27 = { class: "d-flex flex-wrap align-center ga-2" };

const {computed,nextTick,onMounted,onUnmounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
},
  emits: ['close'],
  setup(__props, { expose: __expose, emit: __emit }) {

const props = __props;
const emit = __emit;

const loading = ref(false);
const error = ref('');
const notice = ref('');
const items = ref([]);
const libraries = ref([]);
const directoryRules = ref([]);
const rulesReady = ref(false);
const rulesMessage = ref('');
const monitoringEnabled = ref(false);
const monitoringRules = ref([]);
const incomingPath = ref('');
const settingsUrl = ref('#/setting');
const rulesExpanded = ref(false);
const helpOpen = ref(false);
const selectedKeys = ref([]);
const batchRunning = ref(false);
const batchCurrent = ref(0);
const batchTotal = ref(0);
const savingKeys = ref([]);
const organizingKey = ref('');
const tmdbLoadingKeys = ref([]);
const tmdbSearchedKeys = ref([]);
const tmdbSearchFailedKeys = ref([]);
const tmdbCandidates = ref({});
const selectedCandidates = ref({});
const rowErrors = ref({});
let fileTransferSource = null;
const fileTransferText = ref('');
const fileTransferValue = ref(null);
const fileTransferSeenActive = ref(false);
const ignoredSystemEntries = new Set([
  '#recycle',
  '@eadir',
  '.ds_store',
  'thumbs.db',
  'desktop.ini',
]);

const hasItems = computed(() => items.value.length > 0);
const reviewSummary = computed(() => (
  hasItems.value ? `${items.value.length} 项待处理` : '检查名称与目标后再整理'
));
const directoryStatus = computed(() => {
  if (!directoryRules.value.length) return '未读取到目录规则'
  return rulesReady.value
    ? `已读取 ${directoryRules.value.length} 条目录规则`
    : '目录规则需要处理'
});
const monitoringRuleText = computed(() => (
  monitoringRules.value.length ? `“${monitoringRules.value.join('”“')}”` : '相关目录规则'
));
const queueableItems = computed(() => items.value.filter(item => canQueue(item)));
const selectedQueueableItems = computed(() => (
  queueableItems.value.filter(item => selectedKeys.value.includes(item.raw_title))
));
const allQueueableSelected = computed(() => (
  queueableItems.value.length > 0
  && selectedQueueableItems.value.length === queueableItems.value.length
));
const someQueueableSelected = computed(() => (
  selectedQueueableItems.value.length > 0 && !allQueueableSelected.value
));

function unwrap(response) {
  const body = response && Object.prototype.hasOwnProperty.call(response, 'success')
    ? response
    : (response?.data ?? response);
  if (body?.success === false) {
    throw new Error(body.message || '请求失败')
  }
  return body?.data ?? body ?? {}
}

function isIgnoredSystemItem(item) {
  const rawTitle = String(item?.raw_title || '').trim().toLowerCase();
  return rawTitle.startsWith('.') || ignoredSystemEntries.has(rawTitle)
}

function visibleReviewItems(data) {
  const rows = Array.isArray(data) ? data : (data?.items || []);
  return Array.isArray(rows) ? rows.filter(item => !isIgnoredSystemItem(item)) : []
}

function errorMessage(errorValue, fallback) {
  return errorValue?.message || fallback
}

async function openMoviePilotSettings() {
  const target = settingsUrl.value || '#/setting';
  emit('close');
  await nextTick();
  window.location.assign(target);
}

function rowErrorFor(row) {
  return rowErrors.value[row.raw_title] || ''
}

function setRowError(row, msg) {
  if (msg) {
    rowErrors.value = { ...rowErrors.value, [row.raw_title]: msg };
  } else {
    const next = { ...rowErrors.value };
    delete next[row.raw_title];
    rowErrors.value = next;
  }
}

function clearRowError(row) {
  setRowError(row, '');
}

function hasKey(refValue, key) {
  return refValue.value.includes(key)
}

function addKey(refValue, key) {
  if (!refValue.value.includes(key)) {
    refValue.value = [...refValue.value, key];
  }
}

function removeKey(refValue, key) {
  refValue.value = refValue.value.filter(item => item !== key);
}

function sanitizeProgressText(value) {
  return (typeof value === 'string' ? value : '').trim()
}

function stopFileTransferProgress() {
  if (!fileTransferSource) {
    return
  }
  fileTransferSource.close();
  fileTransferSource = null;
}

function startFileTransferProgress() {
  stopFileTransferProgress();
  fileTransferText.value = '正在校验目录并生成目标名称…';
  fileTransferValue.value = null;
  fileTransferSeenActive.value = false;
  try {
    const source = new EventSource('/api/v1/system/progress/filetransfer', {
      withCredentials: true,
    });
    source.onmessage = event => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return
      }
      if (!payload || typeof payload !== 'object' || typeof payload.enable !== 'boolean') {
        return
      }
      if (payload.enable) {
        fileTransferSeenActive.value = true;
        if (typeof payload.text === 'string' && payload.text.trim()) {
          fileTransferText.value = sanitizeProgressText(payload.text);
        }
        if (Number.isFinite(payload.value)) {
          const clipped = Math.max(0, Math.min(100, Number(payload.value)));
          fileTransferValue.value = Math.round(clipped);
        } else {
          fileTransferValue.value = null;
        }
        return
      }
      if (fileTransferSeenActive.value) {
        fileTransferText.value = '文件移动完成，正在写入整理记录…';
        fileTransferValue.value = 100;
      }
    };
    source.onerror = () => {
      // keep fallback indeterminate if EventSource is unavailable
    };
    fileTransferSource = source;
  } catch {
    // fallback to local text/value only
  }
}

async function loadReview() {
  loading.value = true;
  error.value = '';
  rowErrors.value = {};
  try {
    const response = await props.api.get('plugin/CourseOrganizer/review');
    const data = unwrap(response);
    items.value = visibleReviewItems(data);
    if (Array.isArray(data?.libraries) && data.libraries.length) {
      libraries.value = data.libraries;
    } else {
      libraries.value = [];
    }
    directoryRules.value = Array.isArray(data?.directory_rules) ? data.directory_rules : [];
    rulesReady.value = Boolean(data?.rules_ready);
    rulesMessage.value = data?.rules_message || '';
    monitoringEnabled.value = Boolean(data?.monitoring_enabled);
    monitoringRules.value = Array.isArray(data?.monitoring_rules) ? data.monitoring_rules : [];
    incomingPath.value = data?.incoming_path || '';
    settingsUrl.value = data?.settings_url || '#/setting';
    const restoredCandidates = {};
    const restoredSelections = {};
    for (const row of items.value) {
      const candidate = row?.selected_candidate;
      const candidateKey = row?.selected_candidate_key || candidate?.candidate_key || '';
      if (candidate?.candidate_key && candidate.candidate_key === candidateKey) {
        restoredCandidates[row.raw_title] = [candidate];
        restoredSelections[row.raw_title] = candidateKey;
      }
    }
    tmdbCandidates.value = restoredCandidates;
    selectedCandidates.value = restoredSelections;
    selectedKeys.value = [];
  } catch (loadError) {
    error.value = errorMessage(loadError, '加载人工复核列表失败');
  } finally {
    loading.value = false;
  }
}

async function refreshReview() {
  if (batchRunning.value) return
  loading.value = true;
  error.value = '';
  try {
    await props.api.post('plugin/CourseOrganizer/review/refresh');
    await loadReview();
    notice.value = '预览已重新扫描';
  } catch (refreshError) {
    error.value = errorMessage(refreshError, '刷新预览失败，请检查源目录后重试');
  } finally {
    loading.value = false;
  }
}

async function searchTmdb(row, silent = false) {
  if (batchRunning.value || isSaving(row) || isTmdbLoading(row)) return
  addKey(tmdbLoadingKeys, row.raw_title);
  error.value = '';
  if (!silent) notice.value = '';
  clearRowError(row);
  removeKey(tmdbSearchFailedKeys, row.raw_title);
  const selectedKey = selectedCandidateFor(row) || row.selected_candidate_key || '';
  const selectedCandidate = row.selected_candidate;
  try {
    const response = await props.api.post('plugin/CourseOrganizer/review/tmdb/search', {
      raw_title: row.raw_title,
      revision: row.revision,
      search_name: (row.final_title && row.final_title.trim()) || row.raw_title,
    });
    const data = unwrap(response);
    let candidates = Array.isArray(data?.items) ? data.items : [];
    if (
      selectedKey
      && selectedCandidate?.candidate_key === selectedKey
      && !candidates.some(candidate => candidate.candidate_key === selectedKey)
    ) {
      candidates = [selectedCandidate, ...candidates];
    }
    tmdbCandidates.value = { ...tmdbCandidates.value, [row.raw_title]: candidates };
    if (!silent) notice.value = data?.message || '已找到 TMDB 候选';
  } catch (searchError) {
    addKey(tmdbSearchFailedKeys, row.raw_title);
    if (!silent) setRowError(row, errorMessage(searchError, '搜索 TMDB 候选失败，请刷新后重试'));
  } finally {
    addKey(tmdbSearchedKeys, row.raw_title);
    removeKey(tmdbLoadingKeys, row.raw_title);
  }
}

async function autoSearchAll() {
  const todo = items.value.filter(item => !item.source_pending && !item.selected_candidate_key);
  for (const item of todo) {
    await searchTmdb(item, true);
  }
}

async function associateTmdb(row, candidate) {
  if (batchRunning.value || isSaving(row) || isTmdbLoading(row) || !candidate?.candidate_key) return
  addKey(savingKeys, row.raw_title);
  error.value = '';
  notice.value = '';
  clearRowError(row);
  try {
    const response = await props.api.post('plugin/CourseOrganizer/review/tmdb/associate', {
      raw_title: row.raw_title,
      revision: row.revision,
      candidate_key: candidate.candidate_key,
      search_name: (row.final_title && row.final_title.trim()) || row.raw_title,
    });
    const data = unwrap(response);
    // 记录选中的候选 key，让匹配下拉保持显示所选；并保留候选列表供展示
    selectedCandidates.value = { ...selectedCandidates.value, [row.raw_title]: candidate.candidate_key };
    notice.value = data?.final_title
      ? `已关联 TMDB：${data.final_title}`
      : (data?.message || '已保存 TMDB 关联');
    const updated = getUpdatedRow(row.raw_title, data);
    if (updated) {
      // 用返回的最新行替换：建议名称将更新为所选 TMDB 的标题
      items.value = replaceRow(row.raw_title, updated);
    }
  } catch (associateError) {
    setRowError(row, errorMessage(associateError, '保存 TMDB 关联失败，请刷新后重试'));
  } finally {
    removeKey(savingKeys, row.raw_title);
  }
}

async function saveReview(row, action, options = {}) {
  const queued = Boolean(options.queued);
  if ((batchRunning.value && !queued) || isSaving(row) || isTmdbLoading(row)) return false
  if (action === 'confirm' && organizingKey.value) return false
  if (action === 'confirm' && (!row.final_title || !row.target_library)) {
    setRowError(row, '请填写建议名称并选择目标媒体库');
    return false
  }
  if (!queued) {
    error.value = '';
    notice.value = '';
  }
  clearRowError(row);
  const payload = {
    raw_title: row.raw_title,
    revision: row.revision,
    action,
  };
  if (action === 'confirm') {
    payload.final_title = row.final_title;
    payload.target_library = row.target_library;
    startFileTransferProgress();
    organizingKey.value = row.raw_title;
  } else {
    addKey(savingKeys, row.raw_title);
  }
  try {
    const response = await props.api.post('plugin/CourseOrganizer/review', payload);
    const data = unwrap(response);
    if (action === 'confirm') {
      items.value = items.value.filter(item => item.raw_title !== row.raw_title);
      const nextCandidates = { ...tmdbCandidates.value };
      delete nextCandidates[row.raw_title];
      tmdbCandidates.value = nextCandidates;
      removeKey(selectedKeys, row.raw_title);
      if (!queued) notice.value = '整理完成';
    } else {
      notice.value = data?.message || '已保存人工决定';
      if (action === 'ignore') removeKey(selectedKeys, row.raw_title);
      const updated = getUpdatedRow(row.raw_title, data);
      if (updated) {
        items.value = replaceRow(row.raw_title, updated);
      }
    }
    return true
  } catch (saveError) {
    setRowError(row, errorMessage(
      saveError,
      action === 'confirm' ? '单条整理失败，记录已保留，请重试' : '保存人工决定失败，请刷新后重试',
    ));
    return false
  } finally {
    if (action === 'confirm') {
      stopFileTransferProgress();
      organizingKey.value = '';
    } else {
      removeKey(savingKeys, row.raw_title);
    }
  }
}

async function organizeSelected() {
  if (
    batchRunning.value
    || organizingKey.value
    || tmdbLoadingKeys.value.length
    || !selectedQueueableItems.value.length
  ) return
  const queue = [...selectedQueueableItems.value];
  batchRunning.value = true;
  batchCurrent.value = 0;
  batchTotal.value = queue.length;
  error.value = '';
  notice.value = '';
  let succeeded = 0;
  let failed = 0;
  try {
    for (let index = 0; index < queue.length; index += 1) {
      batchCurrent.value = index + 1;
      const row = items.value.find(item => item.raw_title === queue[index].raw_title);
      if (!row || !canQueue(row)) {
        failed += 1;
        continue
      }
      if (await saveReview(row, 'confirm', { queued: true })) succeeded += 1;
      else failed += 1;
    }
  } finally {
    batchRunning.value = false;
    if (failed) {
      error.value = `批量整理完成：成功 ${succeeded} 项，失败 ${failed} 项。失败项目已保留。`;
    } else {
      notice.value = `批量整理完成，共 ${succeeded} 项。`;
    }
  }
}

function getUpdatedRow(rawTitle, payload) {
  if (payload && typeof payload === 'object') {
    if (payload.raw_title) {
      return payload
    }
    if (payload.row && payload.row.raw_title) {
      return payload.row
    }
    if (payload.item && payload.item.raw_title) {
      return payload.item
    }
  }
  if (rawTitle && rawTitle === payload?.raw_title) {
    return payload
  }
  return null
}

function replaceRow(rawTitle, nextRow) {
  return items.value.map(item => (item.raw_title === rawTitle ? nextRow : item))
}

function isSaving(row) {
  return hasKey(savingKeys, row.raw_title)
}

function isTmdbLoading(row) {
  return hasKey(tmdbLoadingKeys, row.raw_title)
}

function isOrganizing(row) {
  return organizingKey.value === row.raw_title
}

function organizingProgress() {
  return ` ${fileTransferValue.value === null ? '' : `（${fileTransferValue.value}%）`}`
}

function hasOrganizingValue() {
  return fileTransferValue.value !== null && fileTransferSeenActive.value
}

function organizingStatusText() {
  if (!fileTransferText.value) {
    return '整理中'
  }
  return `${fileTransferText.value}${organizingProgress()}`
}

function libraryLabel(row) {
  return libraries.value.find(item => item.value === row.target_library)?.title || '待确认'
}

function hasLibrary(row) {
  return libraries.value.some(item => item.value === row.target_library)
}

function canConfirm(row) {
  return rulesReady.value && !row.source_pending && hasLibrary(row)
}

function canQueue(row) {
  return canConfirm(row) && Boolean(String(row.final_title || '').trim()) && row.status_label !== '已跳过'
}

function isSelected(row) {
  return selectedKeys.value.includes(row.raw_title)
}

function setSelected(row, selected) {
  if (selected) addKey(selectedKeys, row.raw_title);
  else removeKey(selectedKeys, row.raw_title);
}

function setAllQueueable(selected) {
  if (!selected) {
    selectedKeys.value = [];
    return
  }
  selectedKeys.value = queueableItems.value.map(item => item.raw_title);
}

function isSourcePending(row) {
  return Boolean(row.source_pending)
}

function statusChipColor(row) {
  if (isSourcePending(row)) return 'info'
  if (row.status_label === '可以整理') return 'success'
  if (row.status_label === '已跳过') return 'default'
  return 'warning'
}

function targetRoot(row) {
  const library = libraries.value.find(item => item.value === row.target_library);
  return library?.path || '请选择目标媒体库'
}

function handlingMode(row) {
  return row.association_required ? '按标题整理' : 'TMDB 整理'
}

function transferTypeLabel(value) {
  const normalized = String(value || '').toLowerCase();
  if (!normalized || normalized === 'move' || normalized.startsWith('rclone_move')) return '移动'
  if (normalized === 'copy' || normalized.startsWith('rclone_copy')) return '复制'
  if (normalized.includes('hardlink')) return '硬链接'
  if (normalized.includes('softlink') || normalized.includes('soft_link')) return '软链接'
  return value
}

function tmdbSearchHint(row) {
  if (isTmdbLoading(row)) return '正在查找 TMDB 候选…'
  if (hasKey(tmdbSearchFailedKeys, row.raw_title)) return '自动匹配失败，可稍后重试'
  if (hasKey(tmdbSearchedKeys, row.raw_title) && !tmdbCandidatesFor(row).length) {
    return '未找到匹配，可修改名称后重试'
  }
  return ''
}

function tmdbCandidatesFor(row) {
  return tmdbCandidates.value[row.raw_title] || []
}

function tmdbCandidateItems(row) {
  return tmdbCandidatesFor(row).map(c => ({
    ...c,
    title: `${c.title}${c.year ? `（${c.year}）` : ''} · ${c.label || c.media_type}`,
  }))
}

function selectedCandidateFor(row) {
  return selectedCandidates.value[row.raw_title] || null
}

function findCandidate(row, key) {
  return tmdbCandidatesFor(row).find(c => c.candidate_key === key) || null
}

onMounted(async () => {
  await loadReview();
  if (Array.isArray(items.value) && items.value.length) {
    autoSearchAll();
  }
});
onUnmounted(stopFileTransferProgress);

__expose({ loadReview, items, loading, savingKeys, tmdbCandidates });

return (_ctx, _cache) => {
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VSheet = _resolveComponent("VSheet");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VCheckbox = _resolveComponent("VCheckbox");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VTable = _resolveComponent("VTable");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VDialog = _resolveComponent("VDialog");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _createElementVNode("div", null, [
        _cache[7] || (_cache[7] = _createElementVNode("h1", {
          id: "course-review-title",
          class: "text-h5"
        }, "待整理项目", -1)),
        _createElementVNode("div", _hoisted_3, _toDisplayString(reviewSummary.value), 1)
      ]),
      _createElementVNode("div", _hoisted_4, [
        _createVNode(_component_VBtn, {
          icon: "mdi-help-circle-outline",
          variant: "text",
          "aria-label": "查看使用说明",
          onClick: _cache[0] || (_cache[0] = $event => (helpOpen.value = true))
        }),
        _createVNode(_component_VBtn, {
          "prepend-icon": "mdi-refresh",
          variant: "tonal",
          loading: loading.value,
          disabled: batchRunning.value,
          "aria-label": "重新扫描待整理项目",
          onClick: refreshReview
        }, {
          default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
            _createTextVNode(" 重新扫描 ", -1)
          ]))]),
          _: 1
        }, 8, ["loading", "disabled"]),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          disabled: batchRunning.value,
          "aria-label": "关闭待整理项目",
          onClick: _cache[1] || (_cache[1] = $event => (emit('close')))
        }, null, 8, ["disabled"])
      ])
    ]),
    _createVNode(_component_VSheet, {
      border: "",
      rounded: "",
      class: "course-directory-summary mb-3"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VIcon, {
          icon: rulesReady.value ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline',
          color: rulesReady.value ? 'success' : 'warning'
        }, null, 8, ["icon", "color"]),
        _createElementVNode("div", _hoisted_5, [
          _createElementVNode("div", _hoisted_6, _toDisplayString(directoryStatus.value), 1),
          _createElementVNode("div", _hoisted_7, [
            _cache[9] || (_cache[9] = _createTextVNode(" 沿用 MoviePilot 的目录与整理设置", -1)),
            (incomingPath.value)
              ? (_openBlock(), _createElementBlock("span", _hoisted_8, " · 来源 " + _toDisplayString(incomingPath.value), 1))
              : _createCommentVNode("", true)
          ])
        ]),
        (directoryRules.value.length)
          ? (_openBlock(), _createBlock(_component_VBtn, {
              key: 0,
              variant: "text",
              size: "small",
              "append-icon": rulesExpanded.value ? 'mdi-chevron-up' : 'mdi-chevron-down',
              onClick: _cache[2] || (_cache[2] = $event => (rulesExpanded.value = !rulesExpanded.value))
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(rulesExpanded.value ? '收起' : '查看规则'), 1)
              ]),
              _: 1
            }, 8, ["append-icon"]))
          : _createCommentVNode("", true),
        _createVNode(_component_VBtn, {
          variant: "text",
          color: "primary",
          size: "small",
          "prepend-icon": "mdi-folder-cog",
          disabled: batchRunning.value,
          onClick: _withModifiers(openMoviePilotSettings, ["stop"])
        }, {
          default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
            _createTextVNode(" 目录设置 ", -1)
          ]))]),
          _: 1
        }, 8, ["disabled"])
      ]),
      _: 1
    }),
    (rulesExpanded.value && directoryRules.value.length)
      ? (_openBlock(), _createElementBlock("div", _hoisted_9, [
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(directoryRules.value, (rule) => {
            return (_openBlock(), _createBlock(_component_VSheet, {
              key: `${rule.value}:${rule.download_path}:${rule.path}`,
              border: "",
              rounded: "",
              class: "course-directory-rule"
            }, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_10, [
                  _createElementVNode("strong", _hoisted_11, _toDisplayString(rule.title), 1),
                  _createVNode(_component_VChip, {
                    size: "x-small",
                    variant: "tonal"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(transferTypeLabel(rule.transfer_type)), 1)
                    ]),
                    _: 2
                  }, 1024),
                  _createVNode(_component_VChip, {
                    size: "x-small",
                    variant: "tonal",
                    color: rule.renaming ? 'success' : 'warning'
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(rule.renaming ? '智能重命名' : '未开启重命名'), 1)
                    ]),
                    _: 2
                  }, 1032, ["color"]),
                  (rule.scraping)
                    ? (_openBlock(), _createBlock(_component_VChip, {
                        key: 0,
                        size: "x-small",
                        variant: "tonal"
                      }, {
                        default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                          _createTextVNode("影视刮削", -1)
                        ]))]),
                        _: 1
                      }))
                    : _createCommentVNode("", true),
                  _createVNode(_component_VChip, {
                    size: "x-small",
                    variant: "tonal",
                    color: rule.monitor_type ? 'warning' : undefined
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(rule.monitor_type ? '自动监控' : '手动整理'), 1)
                    ]),
                    _: 2
                  }, 1032, ["color"])
                ]),
                _createElementVNode("div", _hoisted_12, _toDisplayString(rule.download_path) + " → " + _toDisplayString(rule.path), 1)
              ]),
              _: 2
            }, 1024))
          }), 128))
        ]))
      : _createCommentVNode("", true),
    (rulesMessage.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 1,
          type: "warning",
          variant: "tonal",
          density: "compact",
          class: "mb-2",
          role: "alert"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(rulesMessage.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (monitoringEnabled.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 2,
          type: "error",
          variant: "tonal",
          density: "compact",
          class: "mb-2",
          role: "alert"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(monitoringRuleText.value) + "与当前来源目录重叠；插件已自动禁止自动整理，仅保留安全预览。 ", 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (batchRunning.value || organizingKey.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 3,
          type: "info",
          variant: "tonal",
          density: "compact",
          class: "mb-2",
          role: "status"
        }, {
          default: _withCtx(() => [
            (batchRunning.value)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _createTextVNode(" 批量队列正在处理第 " + _toDisplayString(batchCurrent.value) + "/" + _toDisplayString(batchTotal.value) + " 项，其余项目将按顺序执行。 ", 1)
                ], 64))
              : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                  _createTextVNode("当前一次只能整理一个项目，完成后可继续下一项。")
                ], 64))
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (error.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 4,
          type: "error",
          variant: "tonal",
          class: "mb-4",
          role: "alert"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (notice.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 5,
          type: "success",
          variant: "tonal",
          class: "mb-4",
          role: "status"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(notice.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (hasItems.value && !loading.value)
      ? (_openBlock(), _createBlock(_component_VSheet, {
          key: 6,
          border: "",
          rounded: "",
          class: "course-batch-bar mb-3"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCheckbox, {
              "model-value": allQueueableSelected.value,
              indeterminate: someQueueableSelected.value,
              disabled: batchRunning.value || !queueableItems.value.length,
              "hide-details": "",
              density: "compact",
              label: "全选可整理项目",
              "aria-label": "全选可整理项目",
              "onUpdate:modelValue": setAllQueueable
            }, null, 8, ["model-value", "indeterminate", "disabled"]),
            _createElementVNode("div", _hoisted_13, " 已选 " + _toDisplayString(selectedQueueableItems.value.length) + " 项 ", 1),
            _createVNode(_component_VBtn, {
              color: "primary",
              variant: "tonal",
              "prepend-icon": "mdi-playlist-check",
              loading: batchRunning.value,
              disabled: batchRunning.value || Boolean(organizingKey.value) || Boolean(tmdbLoadingKeys.value.length) || !selectedQueueableItems.value.length,
              onClick: organizeSelected
            }, {
              default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                _createTextVNode(" 批量整理 ", -1)
              ]))]),
              _: 1
            }, 8, ["loading", "disabled"])
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (loading.value)
      ? (_openBlock(), _createBlock(_component_VProgressLinear, {
          key: 7,
          indeterminate: "",
          color: "primary",
          "aria-label": "正在加载"
        }))
      : (!hasItems.value)
        ? (_openBlock(), _createBlock(_component_VSheet, {
            key: 8,
            border: "",
            rounded: "",
            class: "course-empty-state",
            role: "status"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VIcon, {
                icon: "mdi-folder-search-outline",
                size: "42",
                color: "primary"
              }),
              _cache[14] || (_cache[14] = _createElementVNode("div", { class: "text-h6 mt-3" }, "暂无待整理项目", -1)),
              _cache[15] || (_cache[15] = _createElementVNode("div", { class: "text-body-2 text-medium-emphasis mt-1 mb-4" }, "重新扫描后，这里会显示需要确认的目录。", -1)),
              _createVNode(_component_VBtn, {
                color: "primary",
                variant: "tonal",
                "prepend-icon": "mdi-refresh",
                loading: loading.value,
                onClick: refreshReview
              }, {
                default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                  _createTextVNode(" 重新扫描 ", -1)
                ]))]),
                _: 1
              }, 8, ["loading"])
            ]),
            _: 1
          }))
        : (_openBlock(), _createBlock(_component_VSheet, {
            key: 9,
            border: "",
            rounded: "",
            class: "course-review-table-shell"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VTable, {
                class: "course-review-table",
                density: "comfortable"
              }, {
                default: _withCtx(() => [
                  _cache[21] || (_cache[21] = _createElementVNode("thead", null, [
                    _createElementVNode("tr", null, [
                      _createElementVNode("th", {
                        scope: "col",
                        class: "course-review-select-column"
                      }, "选择"),
                      _createElementVNode("th", { scope: "col" }, "原始名称"),
                      _createElementVNode("th", { scope: "col" }, "建议名称（可改）"),
                      _createElementVNode("th", { scope: "col" }, "目标媒体库"),
                      _createElementVNode("th", { scope: "col" }, "状态"),
                      _createElementVNode("th", {
                        scope: "col",
                        class: "text-right"
                      }, "操作")
                    ])
                  ], -1)),
                  _createElementVNode("tbody", null, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(items.value, (row) => {
                      return (_openBlock(), _createElementBlock("tr", {
                        key: row.raw_title
                      }, [
                        _createElementVNode("td", _hoisted_14, [
                          _createVNode(_component_VCheckbox, {
                            "model-value": isSelected(row),
                            disabled: batchRunning.value || (!canQueue(row) && !isSelected(row)),
                            "hide-details": "",
                            density: "compact",
                            "aria-label": `选择整理：${row.raw_title}`,
                            "onUpdate:modelValue": value => setSelected(row, value)
                          }, null, 8, ["model-value", "disabled", "aria-label", "onUpdate:modelValue"])
                        ]),
                        _createElementVNode("td", _hoisted_15, _toDisplayString(row.raw_title), 1),
                        _createElementVNode("td", _hoisted_16, [
                          _createVNode(_component_VTextField, {
                            modelValue: row.final_title,
                            "onUpdate:modelValue": $event => ((row.final_title) = $event),
                            "aria-label": `建议名称：${row.raw_title}`,
                            "hide-details": "",
                            density: "comfortable",
                            variant: "outlined",
                            autocomplete: "off",
                            disabled: batchRunning.value || isSaving(row) || isOrganizing(row),
                            placeholder: "建议名称（可修改）"
                          }, null, 8, ["modelValue", "onUpdate:modelValue", "aria-label", "disabled"]),
                          (isOrganizing(row))
                            ? (_openBlock(), _createBlock(_component_VProgressLinear, {
                                key: 0,
                                indeterminate: !hasOrganizingValue(),
                                "model-value": fileTransferValue.value || 0,
                                color: "primary",
                                class: "mt-2",
                                "aria-label": "正在整理"
                              }, null, 8, ["indeterminate", "model-value"]))
                            : _createCommentVNode("", true),
                          (isOrganizing(row))
                            ? (_openBlock(), _createElementBlock("div", _hoisted_17, _toDisplayString(organizingStatusText()), 1))
                            : _createCommentVNode("", true),
                          _createVNode(_component_VBtn, {
                            class: "mt-2",
                            variant: "tonal",
                            "min-width": "132",
                            loading: isTmdbLoading(row),
                            disabled: batchRunning.value || isSourcePending(row) || isSaving(row) || isTmdbLoading(row) || isOrganizing(row),
                            "aria-label": `重新搜索 TMDB：${row.raw_title}`,
                            onClick: $event => (searchTmdb(row))
                          }, {
                            default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                              _createTextVNode(" 重新搜索 TMDB ", -1)
                            ]))]),
                            _: 1
                          }, 8, ["loading", "disabled", "aria-label", "onClick"]),
                          (tmdbSearchHint(row))
                            ? (_openBlock(), _createElementBlock("div", _hoisted_18, _toDisplayString(tmdbSearchHint(row)), 1))
                            : _createCommentVNode("", true),
                          (tmdbCandidatesFor(row).length)
                            ? (_openBlock(), _createBlock(_component_VSelect, {
                                key: 3,
                                "model-value": selectedCandidateFor(row),
                                "onUpdate:modelValue": (v) => { const c = findCandidate(row, v); if (c) associateTmdb(row, c); },
                                items: tmdbCandidateItems(row),
                                "item-title": "title",
                                "item-value": "candidate_key",
                                "hide-details": "",
                                density: "compact",
                                variant: "outlined",
                                label: selectedCandidateFor(row) ? '已关联的 TMDB 作品' : '选择匹配的 TMDB 作品',
                                class: "mt-1",
                                disabled: batchRunning.value || isSaving(row) || isTmdbLoading(row) || isOrganizing(row),
                                "aria-label": `选择 TMDB 候选：${row.raw_title}`
                              }, null, 8, ["model-value", "onUpdate:modelValue", "items", "label", "disabled", "aria-label"]))
                            : _createCommentVNode("", true)
                        ]),
                        _createElementVNode("td", _hoisted_19, [
                          _createVNode(_component_VSelect, {
                            modelValue: row.target_library,
                            "onUpdate:modelValue": $event => ((row.target_library) = $event),
                            items: libraries.value,
                            "item-title": "title",
                            "item-value": "value",
                            "aria-label": `目标媒体库：${row.raw_title}`,
                            "hide-details": "",
                            density: "comfortable",
                            variant: "outlined",
                            disabled: batchRunning.value || isSaving(row) || isOrganizing(row)
                          }, null, 8, ["modelValue", "onUpdate:modelValue", "items", "aria-label", "disabled"]),
                          _createElementVNode("div", _hoisted_20, "目标：" + _toDisplayString(targetRoot(row)), 1)
                        ]),
                        _createElementVNode("td", null, [
                          _createVNode(_component_VChip, {
                            size: "small",
                            variant: "tonal",
                            class: "mr-1"
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(handlingMode(row)), 1)
                            ]),
                            _: 2
                          }, 1024),
                          (isOrganizing(row))
                            ? (_openBlock(), _createBlock(_component_VChip, {
                                key: 0,
                                size: "small",
                                variant: "tonal",
                                color: "info",
                                "aria-label": "整理中",
                                class: "course-review-organizing-chip"
                              }, {
                                default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                                  _createTextVNode(" 整理中 ", -1)
                                ]))]),
                                _: 1
                              }))
                            : (_openBlock(), _createBlock(_component_VChip, {
                                key: 1,
                                size: "small",
                                variant: "tonal",
                                color: statusChipColor(row),
                                "aria-label": `状态：${row.status_label || '需要确认'}`
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode(_toDisplayString(row.status_label || '需要确认'), 1)
                                ]),
                                _: 2
                              }, 1032, ["color", "aria-label"]))
                        ]),
                        _createElementVNode("td", _hoisted_21, [
                          _createVNode(_component_VBtn, {
                            color: "primary",
                            variant: "tonal",
                            "min-width": "108",
                            loading: isOrganizing(row),
                            disabled: batchRunning.value || Boolean(organizingKey.value) || !canConfirm(row) || isTmdbLoading(row),
                            "aria-label": `确认整理：${row.raw_title}`,
                            onClick: $event => (saveReview(row, 'confirm'))
                          }, {
                            default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                              _createTextVNode(" 确认并整理 ", -1)
                            ]))]),
                            _: 1
                          }, 8, ["loading", "disabled", "aria-label", "onClick"]),
                          (row.status_label !== '已跳过')
                            ? (_openBlock(), _createBlock(_component_VBtn, {
                                key: 0,
                                variant: "text",
                                "min-width": "76",
                                disabled: batchRunning.value || isSourcePending(row) || isSaving(row) || isOrganizing(row),
                                "aria-label": `跳过：${row.raw_title}`,
                                onClick: $event => (saveReview(row, 'ignore'))
                              }, {
                                default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                                  _createTextVNode(" 跳过 ", -1)
                                ]))]),
                                _: 1
                              }, 8, ["disabled", "aria-label", "onClick"]))
                            : (_openBlock(), _createBlock(_component_VBtn, {
                                key: 1,
                                variant: "text",
                                "min-width": "76",
                                disabled: batchRunning.value || isSourcePending(row) || isSaving(row) || isOrganizing(row),
                                "aria-label": `恢复处理：${row.raw_title}`,
                                onClick: $event => (saveReview(row, 'restore'))
                              }, {
                                default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
                                  _createTextVNode(" 恢复处理 ", -1)
                                ]))]),
                                _: 1
                              }, 8, ["disabled", "aria-label", "onClick"])),
                          (rowErrorFor(row))
                            ? (_openBlock(), _createBlock(_component_VAlert, {
                                key: 2,
                                type: "error",
                                density: "compact",
                                variant: "tonal",
                                class: "mt-2 text-left",
                                role: "alert",
                                "aria-label": `操作提示：${row.raw_title}`,
                                onClick: _cache[3] || (_cache[3] = _withModifiers(() => {}, ["stop"]))
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode(_toDisplayString(rowErrorFor(row)), 1)
                                ]),
                                _: 2
                              }, 1032, ["aria-label"]))
                            : _createCommentVNode("", true)
                        ])
                      ]))
                    }), 128))
                  ])
                ]),
                _: 1
              })
            ]),
            _: 1
          })),
    (hasItems.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_22, [
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(items.value, (row) => {
            return (_openBlock(), _createBlock(_component_VCard, {
              key: `card-${row.raw_title}`,
              border: "",
              variant: "outlined",
              class: "course-review-card"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, { class: "course-review-card__title text-subtitle-1" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCheckbox, {
                      "model-value": isSelected(row),
                      disabled: batchRunning.value || (!canQueue(row) && !isSelected(row)),
                      "hide-details": "",
                      density: "compact",
                      "aria-label": `选择整理：${row.raw_title}`,
                      "onUpdate:modelValue": value => setSelected(row, value)
                    }, null, 8, ["model-value", "disabled", "aria-label", "onUpdate:modelValue"]),
                    _createElementVNode("span", _hoisted_23, _toDisplayString(row.raw_title), 1)
                  ]),
                  _: 2
                }, 1024),
                _createVNode(_component_VCardText, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_VTextField, {
                      modelValue: row.final_title,
                      "onUpdate:modelValue": $event => ((row.final_title) = $event),
                      label: "建议名称",
                      "aria-label": `建议名称：${row.raw_title}`,
                      variant: "outlined",
                      density: "comfortable",
                      autocomplete: "off",
                      disabled: batchRunning.value || isSaving(row) || isOrganizing(row)
                    }, null, 8, ["modelValue", "onUpdate:modelValue", "aria-label", "disabled"]),
                    (isOrganizing(row))
                      ? (_openBlock(), _createBlock(_component_VProgressLinear, {
                          key: 0,
                          indeterminate: !hasOrganizingValue(),
                          "model-value": fileTransferValue.value || 0,
                          color: "primary",
                          class: "mb-2",
                          "aria-label": "正在整理"
                        }, null, 8, ["indeterminate", "model-value"]))
                      : _createCommentVNode("", true),
                    (isOrganizing(row))
                      ? (_openBlock(), _createElementBlock("div", _hoisted_24, _toDisplayString(organizingStatusText()), 1))
                      : _createCommentVNode("", true),
                    (isOrganizing(row))
                      ? (_openBlock(), _createBlock(_component_VChip, {
                          key: 2,
                          size: "small",
                          variant: "tonal",
                          color: "info",
                          class: "mb-2",
                          "aria-label": "整理中"
                        }, {
                          default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                            _createTextVNode(" 整理中 ", -1)
                          ]))]),
                          _: 1
                        }))
                      : _createCommentVNode("", true),
                    _createVNode(_component_VBtn, {
                      class: "mb-3",
                      variant: "tonal",
                      "min-width": "132",
                      loading: isTmdbLoading(row),
                      disabled: batchRunning.value || isSourcePending(row) || isSaving(row) || isTmdbLoading(row) || isOrganizing(row),
                      "aria-label": `重新搜索 TMDB：${row.raw_title}`,
                      onClick: $event => (searchTmdb(row))
                    }, {
                      default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                        _createTextVNode(" 重新搜索 TMDB ", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading", "disabled", "aria-label", "onClick"]),
                    (tmdbSearchHint(row))
                      ? (_openBlock(), _createElementBlock("div", _hoisted_25, _toDisplayString(tmdbSearchHint(row)), 1))
                      : _createCommentVNode("", true),
                    (tmdbCandidatesFor(row).length)
                      ? (_openBlock(), _createBlock(_component_VSelect, {
                          key: 4,
                          "model-value": selectedCandidateFor(row),
                          "onUpdate:modelValue": (v) => { const c = findCandidate(row, v); if (c) associateTmdb(row, c); },
                          items: tmdbCandidateItems(row),
                          "item-title": "title",
                          "item-value": "candidate_key",
                          "hide-details": "",
                          density: "compact",
                          variant: "outlined",
                          label: selectedCandidateFor(row) ? '已关联的 TMDB 作品' : '选择匹配的 TMDB 作品',
                          class: "mb-3",
                          disabled: batchRunning.value || isSaving(row) || isTmdbLoading(row) || isOrganizing(row),
                          "aria-label": `选择 TMDB 候选：${row.raw_title}`
                        }, null, 8, ["model-value", "onUpdate:modelValue", "items", "label", "disabled", "aria-label"]))
                      : _createCommentVNode("", true),
                    _createVNode(_component_VSelect, {
                      modelValue: row.target_library,
                      "onUpdate:modelValue": $event => ((row.target_library) = $event),
                      items: libraries.value,
                      "item-title": "title",
                      "item-value": "value",
                      label: "目标媒体库",
                      "aria-label": `目标媒体库：${row.raw_title}`,
                      variant: "outlined",
                      density: "comfortable",
                      disabled: batchRunning.value || isSaving(row) || isOrganizing(row)
                    }, null, 8, ["modelValue", "onUpdate:modelValue", "items", "aria-label", "disabled"]),
                    _createElementVNode("div", _hoisted_26, "目标：" + _toDisplayString(targetRoot(row)), 1),
                    _createElementVNode("div", _hoisted_27, [
                      _createVNode(_component_VChip, {
                        size: "small",
                        variant: "tonal"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(libraryLabel(row)), 1)
                        ]),
                        _: 2
                      }, 1024),
                      _createVNode(_component_VChip, {
                        size: "small",
                        variant: "tonal"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(handlingMode(row)), 1)
                        ]),
                        _: 2
                      }, 1024),
                      _createVNode(_component_VChip, {
                        size: "small",
                        variant: "tonal",
                        color: statusChipColor(row)
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(row.status_label || '需要确认'), 1)
                        ]),
                        _: 2
                      }, 1032, ["color"]),
                      _createVNode(_component_VSpacer),
                      _createVNode(_component_VBtn, {
                        color: "primary",
                        variant: "tonal",
                        "min-width": "108",
                        loading: isOrganizing(row),
                        disabled: batchRunning.value || Boolean(organizingKey.value) || !canConfirm(row) || isTmdbLoading(row),
                        "aria-label": `确认整理：${row.raw_title}`,
                        onClick: $event => (saveReview(row, 'confirm'))
                      }, {
                        default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                          _createTextVNode(" 确认并整理 ", -1)
                        ]))]),
                        _: 1
                      }, 8, ["loading", "disabled", "aria-label", "onClick"]),
                      (row.status_label !== '已跳过')
                        ? (_openBlock(), _createBlock(_component_VBtn, {
                            key: 0,
                            variant: "text",
                            "min-width": "76",
                            disabled: batchRunning.value || isSourcePending(row) || isSaving(row) || isOrganizing(row),
                            "aria-label": `跳过：${row.raw_title}`,
                            onClick: $event => (saveReview(row, 'ignore'))
                          }, {
                            default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                              _createTextVNode(" 跳过 ", -1)
                            ]))]),
                            _: 1
                          }, 8, ["disabled", "aria-label", "onClick"]))
                        : (_openBlock(), _createBlock(_component_VBtn, {
                            key: 1,
                            variant: "text",
                            "min-width": "76",
                            disabled: batchRunning.value || isSourcePending(row) || isSaving(row) || isOrganizing(row),
                            "aria-label": `恢复处理：${row.raw_title}`,
                            onClick: $event => (saveReview(row, 'restore'))
                          }, {
                            default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                              _createTextVNode(" 恢复处理 ", -1)
                            ]))]),
                            _: 1
                          }, 8, ["disabled", "aria-label", "onClick"]))
                    ]),
                    (rowErrorFor(row))
                      ? (_openBlock(), _createBlock(_component_VAlert, {
                          key: 5,
                          type: "error",
                          density: "compact",
                          variant: "tonal",
                          class: "mt-2",
                          role: "alert",
                          "aria-label": `操作提示：${row.raw_title}`
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(rowErrorFor(row)), 1)
                          ]),
                          _: 2
                        }, 1032, ["aria-label"]))
                      : _createCommentVNode("", true)
                  ]),
                  _: 2
                }, 1024)
              ]),
              _: 2
            }, 1024))
          }), 128))
        ]))
      : _createCommentVNode("", true),
    _createVNode(_component_VDialog, {
      modelValue: helpOpen.value,
      "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((helpOpen).value = $event)),
      "max-width": "680"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, null, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "d-flex align-center pa-4" }, {
              default: _withCtx(() => [
                _cache[27] || (_cache[27] = _createElementVNode("span", null, "使用说明", -1)),
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  icon: "mdi-close",
                  variant: "text",
                  "aria-label": "关闭使用说明",
                  onClick: _cache[4] || (_cache[4] = $event => (helpOpen.value = false))
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VDivider),
            _createVNode(_component_VCardText, { class: "course-help-content" }, {
              default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
                _createElementVNode("div", null, [
                  _createElementVNode("strong", null, "1. 目录来自 MoviePilot"),
                  _createElementVNode("p", null, "插件直接读取「设置 → 存储 & 目录」，沿用媒体类型、媒体类别、存储、整理方式、智能重命名和影视刮削。")
                ], -1),
                _createElementVNode("div", null, [
                  _createElementVNode("strong", null, "2. 文件夹何时显示"),
                  _createElementVNode("p", null, "插件会递归检查整个文件夹。目录内没有正在下载的临时或缓存文件，并且内容保持稳定后，才会显示在待整理列表。")
                ], -1),
                _createElementVNode("div", null, [
                  _createElementVNode("strong", null, "3. 自动整理符合条件的项目"),
                  _createElementVNode("p", null, "默认只扫描并生成建议，不会移动文件。开启自动整理后，仅识别可靠且目标媒体库明确的项目会自动执行；不确定项目仍等待人工确认。")
                ], -1),
                _createElementVNode("div", null, [
                  _createElementVNode("strong", null, "4. 智能助手（如 DeepSeek）"),
                  _createElementVNode("p", null, "插件直接使用 MoviePilot「设置 → 智能助手」中的模型，无需在插件内重复配置。复杂目录名会先提取 TMDB 搜索词再复核候选；不可用或判断不明确时不会自动整理。")
                ], -1),
                _createElementVNode("div", null, [
                  _createElementVNode("strong", null, "5. 两种整理方式"),
                  _createElementVNode("p", null, "已关联媒体信息的项目使用 MoviePilot 的 TMDB 整理；课程等无媒体 ID 的项目按确认后的标题整理。")
                ], -1),
                _createElementVNode("div", null, [
                  _createElementVNode("strong", null, "6. 避免重复监控"),
                  _createElementVNode("p", null, "同一来源目录不要同时启用 MoviePilot 自动监控和插件自动整理，避免两个任务竞争同一批文件。")
                ], -1),
                _createElementVNode("div", null, [
                  _createElementVNode("strong", null, "7. 批量任务自动排队"),
                  _createElementVNode("p", null, "可勾选多个项目后批量整理。任务会按顺序逐项执行，失败项目保留并继续下一项。")
                ], -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_VCardActions, { class: "pa-4 pt-0" }, {
              default: _withCtx(() => [
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  variant: "tonal",
                  onClick: _cache[5] || (_cache[5] = $event => (helpOpen.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[29] || (_cache[29] = [
                    _createTextVNode("知道了", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-35781e2e"]]);

export { Page as default };
