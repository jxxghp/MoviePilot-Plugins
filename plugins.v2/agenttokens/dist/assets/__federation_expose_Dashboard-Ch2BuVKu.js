import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { f as formatTokens, u as unwrapResponse } from './provider-BURm2Fqi.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,resolveComponent:_resolveComponent,createVNode:_createVNode,unref:_unref,renderList:_renderList,Fragment:_Fragment,openBlock:_openBlock,createElementBlock:_createElementBlock,createTextVNode:_createTextVNode,withCtx:_withCtx,createBlock:_createBlock} = await importShared('vue');


const _hoisted_1 = { class: "agenttokens-dashboard" };
const _hoisted_2 = { class: "d-flex align-center mb-3" };
const _hoisted_3 = { class: "text-h5" };
const _hoisted_4 = { class: "text-caption text-medium-emphasis mb-3" };
const _hoisted_5 = { class: "text-caption" };

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Dashboard',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
  allowRefresh: {
    type: Boolean,
    default: true,
  },
},
  setup(__props) {

const props = __props;

const loading = ref(false);
const status = ref({ providers: [], summary: {} });
let timer = null;

const summary = computed(() => status.value.summary || {});
const providers = computed(() => status.value.providers || []);

// 读取仪表板所需的精简状态。
async function loadStatus() {
  if (!props.allowRefresh) return
  loading.value = true;
  try {
    const response = await props.api.get('plugin/AgentTokens/status');
    status.value = unwrapResponse(response) || status.value;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadStatus();
  timer = window.setInterval(loadStatus, 30000);
});

onUnmounted(() => {
  if (timer) {
    window.clearInterval(timer);
  }
});

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VListItem = _resolveComponent("VListItem");
  const _component_VList = _resolveComponent("VList");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _createElementVNode("div", null, [
        _cache[0] || (_cache[0] = _createElementVNode("div", { class: "text-subtitle-2" }, "Agent Tokens 管理", -1)),
        _createElementVNode("div", _hoisted_3, _toDisplayString(summary.value.available_count || 0) + " / " + _toDisplayString(summary.value.enabled_count || 0), 1)
      ]),
      _createVNode(_component_VSpacer),
      _createVNode(_component_VBtn, {
        icon: "mdi-refresh",
        variant: "text",
        size: "small",
        loading: loading.value,
        onClick: loadStatus
      }, null, 8, ["loading"])
    ]),
    _createVNode(_component_VProgressLinear, {
      "model-value": summary.value.total_limit ? Math.min((summary.value.total_used || 0) * 100 / summary.value.total_limit, 100) : 0,
      color: "primary",
      height: "8",
      rounded: "",
      class: "mb-3"
    }, null, 8, ["model-value"]),
    _createElementVNode("div", _hoisted_4, _toDisplayString(_unref(formatTokens)(summary.value.total_used)) + " / " + _toDisplayString(summary.value.total_limit ? _unref(formatTokens)(summary.value.total_limit) : '不限'), 1),
    _createVNode(_component_VList, {
      density: "compact",
      class: "py-0"
    }, {
      default: _withCtx(() => [
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(providers.value.slice(0, 4), (row) => {
          return (_openBlock(), _createBlock(_component_VListItem, {
            key: row.id,
            title: row.name,
            subtitle: row.model
          }, {
            prepend: _withCtx(() => [
              _createVNode(_component_VIcon, {
                color: row.usage?.exhausted ? 'error' : 'success',
                size: "small"
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(row.usage?.exhausted ? 'mdi-alert-circle' : 'mdi-check-circle'), 1)
                ]),
                _: 2
              }, 1032, ["color"])
            ]),
            append: _withCtx(() => [
              _createElementVNode("span", _hoisted_5, _toDisplayString(_unref(formatTokens)(row.usage?.total_tokens)), 1)
            ]),
            _: 2
          }, 1032, ["title", "subtitle"]))
        }), 128))
      ]),
      _: 1
    })
  ]))
}
}

};

export { _sfc_main as default };
