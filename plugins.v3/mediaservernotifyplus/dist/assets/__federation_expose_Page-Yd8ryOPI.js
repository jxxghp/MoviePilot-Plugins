import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = {
  class: "page-forward",
  "aria-live": "polite"
};

const {onMounted} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'MediaServerNotifyPlus' },
},
  emits: ['action', 'switch', 'close'],
  setup(__props, { emit: __emit }) {


const emit = __emit;

// 插件卡片只保留一个界面：点击后直接进入 Config。
onMounted(() => emit('switch'));

return (_ctx, _cache) => {
  const _component_VProgressCircular = _resolveComponent("VProgressCircular");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VProgressCircular, {
      indeterminate: "",
      color: "primary",
      size: "28"
    }),
    _cache[0] || (_cache[0] = _createElementVNode("span", null, "正在打开媒体库通知…", -1))
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-a063b0c7"]]);

export { Page as default };
