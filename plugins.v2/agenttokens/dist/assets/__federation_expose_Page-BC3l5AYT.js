import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import AppPage from './__federation_expose_AppPage-CYUQYkoo.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "agenttokens-page-wrapper" };


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
  const _component_VToolbarTitle = _resolveComponent("VToolbarTitle");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VToolbar, {
      density: "comfortable",
      color: "transparent"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VToolbarTitle, null, {
          default: _withCtx(() => [...(_cache[1] || (_cache[1] = [
            _createTextVNode("Agent Tokens 数据", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_VSpacer),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VDivider),
    _createVNode(AppPage, {
      api: __props.api,
      "plugin-id": "AgentTokens",
      "hide-title": ""
    }, null, 8, ["api"])
  ]))
}
}

};

export { _sfc_main as default };
