import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import _sfc_main$1 from './__federation_expose_AppPage-EV4Kchio.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-B_eZRIX_.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "agenttokens-page-wrapper" };

const {ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
},
  emits: ['close'],
  setup(__props, { emit: __emit }) {


const emit = __emit;

const pageRef = ref(null);

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VToolbar, {
      density: "comfortable",
      class: "sticky-toolbar"
    }, {
      default: _withCtx(() => [
        _cache[3] || (_cache[3] = _createElementVNode("div", { class: "text-h6 ms-3" }, "Agent Tokens 管理", -1)),
        _createVNode(_component_VSpacer),
        _createVNode(_component_VBtn, {
          icon: "mdi-refresh",
          variant: "text",
          loading: pageRef.value?.loading,
          onClick: _cache[0] || (_cache[0] = $event => (pageRef.value?.loadStatus()))
        }, null, 8, ["loading"]),
        _createVNode(_component_VBtn, {
          icon: "mdi-content-save",
          variant: "text",
          color: "primary",
          loading: pageRef.value?.saving,
          onClick: _cache[1] || (_cache[1] = $event => (pageRef.value?.saveConfig()))
        }, null, 8, ["loading"]),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VDivider),
    _createVNode(_sfc_main$1, {
      ref_key: "pageRef",
      ref: pageRef,
      api: __props.api,
      "plugin-id": "AgentTokens",
      "hide-title": ""
    }, null, 8, ["api"])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-2f12fb0f"]]);

export { Page as default };
