import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import AppPage from './__federation_expose_AppPage-DV__XoqY.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,mergeProps:_mergeProps,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "moe-page-wrapper" };

const {ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'MediaOverviewEnhancer' },
  navKey: { type: String, default: 'main' },
  show_switch: { type: Boolean, default: true },
},
  emits: ['close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const pageRef = ref(null);

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VTooltip = _resolveComponent("VTooltip");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VToolbar, {
      density: "comfortable",
      class: "moe-toolbar"
    }, {
      default: _withCtx(() => [
        _cache[2] || (_cache[2] = _createElementVNode("div", { class: "text-h6 ms-3" }, "影视简介增强", -1)),
        _createVNode(_component_VSpacer),
        (props.show_switch)
          ? (_openBlock(), _createBlock(_component_VTooltip, {
              key: 0,
              text: "插件设置",
              location: "bottom"
            }, {
              activator: _withCtx(({ props: tooltipProps }) => [
                _createVNode(_component_VBtn, _mergeProps(tooltipProps, {
                  icon: "mdi-cog-outline",
                  variant: "text",
                  "aria-label": "插件设置",
                  onClick: _cache[0] || (_cache[0] = $event => (emit('switch')))
                }), null, 16)
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          "aria-label": "关闭",
          onClick: _cache[1] || (_cache[1] = $event => (emit('close')))
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VDivider),
    _createVNode(AppPage, {
      ref_key: "pageRef",
      ref: pageRef,
      api: props.api,
      "plugin-id": props.pluginId,
      "nav-key": props.navKey,
      "hide-title": ""
    }, null, 8, ["api", "plugin-id", "nav-key"])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-c6b7dd00"]]);

export { Page as default };
