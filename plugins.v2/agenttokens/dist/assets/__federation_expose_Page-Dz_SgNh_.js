import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import AppPage from './__federation_expose_AppPage-BniPA2RJ.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


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

return (_ctx, _cache) => {
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");

  return (_openBlock(), _createBlock(_component_VCard, null, {
    default: _withCtx(() => [
      _createVNode(_component_VCardTitle, { class: "d-flex justify-space-between align-center" }, {
        default: _withCtx(() => [
          _cache[1] || (_cache[1] = _createElementVNode("span", null, "Agent Tokens 配置", -1)),
          _createVNode(_component_VBtn, {
            icon: "mdi-close",
            variant: "text",
            onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCardText, { class: "pa-0" }, {
        default: _withCtx(() => [
          _createVNode(AppPage, {
            api: __props.api,
            "plugin-id": "AgentTokens"
          }, null, 8, ["api"])
        ]),
        _: 1
      })
    ]),
    _: 1
  }))
}
}

};

export { _sfc_main as default };
