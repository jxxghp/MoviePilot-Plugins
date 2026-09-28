import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx,Fragment:_Fragment,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createBlock:_createBlock,renderList:_renderList} = await importShared('vue');


const _hoisted_1 = { class: "hrb-page" };
const _hoisted_2 = { class: "hrb-header" };
const _hoisted_3 = { class: "hrb-title" };
const _hoisted_4 = { class: "d-flex align-center" };
const _hoisted_5 = { class: "hrb-meta-line" };
const _hoisted_6 = { class: "hrb-center" };
const _hoisted_7 = { class: "text-caption text-disabled mt-3" };
const _hoisted_8 = {
  key: 0,
  class: "hrb-empty"
};
const _hoisted_9 = { class: "d-flex align-center" };
const _hoisted_10 = ["title"];
const _hoisted_11 = { class: "hrb-item-meta" };
const _hoisted_12 = { key: 0 };
const _hoisted_13 = { key: 1 };

const {onBeforeUnmount,onMounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: null },
},
  emits: ['switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

// 通知宿主切到 Config 弹窗（宿主插件页监听 @switch，见 PluginConfigDialog）
const emit = __emit;

const records = ref([]);
const total = ref(0);
const maxRecords = ref(100);
const version = ref('');
const hrSites = ref(0);
const loading = ref(false);
const dialog = ref(false);
const clearing = ref(false);
const confirmClear = ref(false);
let timer = null;
let confirmTimer = null;

function getApi() {
  return props.api || (typeof window !== 'undefined' ? window.MoviePilotAPI : null)
}

function unwrap(raw) {
  // 主框架 axios 已解包；仅当顶层没有 success 字段时才再解一层（防止误吞内层 data）
  return (raw && typeof raw === 'object' && 'success' in raw) ? raw : (raw?.data ?? raw)
}

async function fetchRecords() {
  const api = getApi();
  if (!api) return
  loading.value = true;
  try {
    const payload = unwrap(await api.get('plugin/HRBlocker/records'));
    const list = payload?.records ?? payload?.data?.records;
    if (Array.isArray(list)) {
      records.value = list;
      total.value = payload?.total ?? payload?.data?.total ?? list.length;
      maxRecords.value = payload?.max_records ?? payload?.data?.max_records ?? 100;
    }
  } catch (e) {
    console.error('[HRBlocker] 加载屏蔽记录失败', e);
  } finally {
    loading.value = false;
  }
}

async function fetchStatus() {
  const api = getApi();
  if (!api) return
  try {
    const payload = unwrap(await api.get('plugin/HRBlocker/status'));
    const body = payload?.data ?? payload;
    version.value = body?.version ? `v${body.version}` : '';
    hrSites.value = Array.isArray(body?.hr_active_sites) ? body.hr_active_sites.length : 0;
  } catch (e) {
    console.error('[HRBlocker] 加载状态失败', e);
  }
}

function openSettings() {
  emit('switch'); // 宿主切到 Config 弹窗
}

// 两段式确认：第一次点击变为「确认清除」（3秒内有效），第二次真正清空
function onClearClick() {
  if (!confirmClear.value) {
    confirmClear.value = true;
    confirmTimer = setTimeout(() => { confirmClear.value = false; }, 3000);
    return
  }
  if (confirmTimer) clearTimeout(confirmTimer);
  confirmClear.value = false;
  clearRecords();
}

async function clearRecords() {
  const api = getApi();
  if (!api) return
  clearing.value = true;
  try {
    await api.post('plugin/HRBlocker/records/clear');
    records.value = [];
    total.value = 0;
  } catch (e) {
    console.error('[HRBlocker] 清空屏蔽记录失败', e);
  } finally {
    clearing.value = false;
  }
}

function openDialog() {
  dialog.value = true;
  fetchRecords();
}

onMounted(() => {
  fetchRecords();
  fetchStatus();
  // 轻量轮询：仅弹窗打开时刷新列表
  timer = setInterval(() => { if (dialog.value) fetchRecords(); }, 5000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
  if (confirmTimer) clearTimeout(confirmTimer);
});

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_dialog = _resolveComponent("v-dialog");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _createVNode(_component_v_icon, {
          icon: "mdi-shield-alert",
          size: "34",
          color: "error",
          class: "mr-2"
        }),
        _createElementVNode("div", null, [
          _createElementVNode("div", _hoisted_4, [
            _cache[2] || (_cache[2] = _createElementVNode("h2", { class: "ma-0" }, "H&R Blocker", -1)),
            _createVNode(_component_v_chip, {
              class: "ml-2",
              size: "x-small",
              variant: "tonal",
              color: "grey"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(version.value), 1)
              ]),
              _: 1
            })
          ]),
          _createElementVNode("div", _hoisted_5, [
            _createTextVNode(" 已屏蔽 " + _toDisplayString(total.value) + "/" + _toDisplayString(maxRecords.value) + " 条 H&R 种子 ", 1),
            (hrSites.value > 0)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _createTextVNode(" · 联动 " + _toDisplayString(hrSites.value) + " 个全站H&R站点", 1)
                ], 64))
              : _createCommentVNode("", true)
          ])
        ])
      ]),
      _cache[3] || (_cache[3] = _createElementVNode("div", { class: "hrb-header-actions" }, null, -1))
    ]),
    _createElementVNode("div", _hoisted_6, [
      _createVNode(_component_v_btn, {
        color: "error",
        variant: "tonal",
        size: "large",
        "prepend-icon": "mdi-format-list-bulleted",
        onClick: openDialog
      }, {
        default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
          _createTextVNode(" 查看屏蔽记录 ", -1)
        ]))]),
        _: 1
      }),
      _createElementVNode("div", _hoisted_7, " 已屏蔽 " + _toDisplayString(total.value) + "/" + _toDisplayString(maxRecords.value) + " 条（保留最近 " + _toDisplayString(maxRecords.value) + " 条） ", 1)
    ]),
    _createVNode(_component_v_btn, {
      class: "hrb-settings-btn",
      color: "primary",
      variant: "tonal",
      size: "large",
      "prepend-icon": "mdi-cog-outline",
      title: "插件设置",
      onClick: openSettings
    }, {
      default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
        _createTextVNode(" 设置 ", -1)
      ]))]),
      _: 1
    }),
    _createVNode(_component_v_dialog, {
      modelValue: dialog.value,
      "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((dialog).value = $event)),
      "max-width": "560",
      scrollable: ""
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, { class: "d-flex align-center py-2 px-4" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  icon: "mdi-shield-alert",
                  class: "mr-2",
                  color: "error",
                  size: "20"
                }),
                _cache[6] || (_cache[6] = _createElementVNode("span", { class: "text-subtitle-1" }, "H&R 屏蔽记录", -1)),
                _createVNode(_component_v_chip, {
                  class: "ml-2",
                  size: "x-small",
                  color: "error",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(records.value.length) + " / " + _toDisplayString(maxRecords.value), 1)
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_spacer),
                (records.value.length > 0)
                  ? (_openBlock(), _createBlock(_component_v_btn, {
                      key: 0,
                      size: "small",
                      color: confirmClear.value ? 'error' : undefined,
                      variant: confirmClear.value ? 'flat' : 'text',
                      "prepend-icon": "mdi-delete-sweep-outline",
                      loading: clearing.value,
                      onClick: onClearClick
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(confirmClear.value ? '确认清除' : '清除记录'), 1)
                      ]),
                      _: 1
                    }, 8, ["color", "variant", "loading"]))
                  : _createCommentVNode("", true),
                _createVNode(_component_v_btn, {
                  icon: "mdi-refresh",
                  variant: "text",
                  size: "small",
                  loading: loading.value,
                  onClick: fetchRecords
                }, null, 8, ["loading"]),
                _createVNode(_component_v_btn, {
                  icon: "mdi-close",
                  variant: "text",
                  size: "small",
                  onClick: _cache[0] || (_cache[0] = $event => (dialog.value = false))
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_divider),
            _createVNode(_component_v_card_text, {
              class: "pa-2",
              style: {"height":"420px"}
            }, {
              default: _withCtx(() => [
                (records.value.length === 0 && !loading.value)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_8, [
                      _createVNode(_component_v_icon, {
                        icon: "mdi-shield-check-outline",
                        size: "40",
                        color: "success",
                        class: "mb-2"
                      }),
                      _cache[7] || (_cache[7] = _createElementVNode("div", { class: "text-medium-emphasis text-body-2" }, "暂无屏蔽记录", -1)),
                      _cache[8] || (_cache[8] = _createElementVNode("div", { class: "text-caption text-disabled mt-1" }, "被拦截的 H&R 种子会显示在这里", -1))
                    ]))
                  : _createCommentVNode("", true),
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(records.value, (rec, i) => {
                  return (_openBlock(), _createElementBlock("div", {
                    key: i,
                    class: "hrb-item"
                  }, [
                    _createElementVNode("div", _hoisted_9, [
                      _createVNode(_component_v_chip, {
                        size: "x-small",
                        color: rec.stage === '下载拦截' ? 'deep-orange' : 'warning',
                        variant: "flat",
                        class: "mr-2 flex-shrink-0"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(rec.stage), 1)
                        ]),
                        _: 2
                      }, 1032, ["color"]),
                      _createElementVNode("span", {
                        class: "hrb-title",
                        title: rec.title
                      }, _toDisplayString(rec.title), 9, _hoisted_10)
                    ]),
                    _createElementVNode("div", _hoisted_11, [
                      _createElementVNode("span", null, _toDisplayString(rec.time), 1),
                      (rec.site)
                        ? (_openBlock(), _createElementBlock("span", _hoisted_12, "站点：" + _toDisplayString(rec.site), 1))
                        : _createCommentVNode("", true),
                      _createElementVNode("span", null, _toDisplayString(rec.reason), 1),
                      (rec.source)
                        ? (_openBlock(), _createElementBlock("span", _hoisted_13, "来源：" + _toDisplayString(rec.source), 1))
                        : _createCommentVNode("", true)
                    ])
                  ]))
                }), 128))
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
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-7686036f"]]);

export { Page as default };
