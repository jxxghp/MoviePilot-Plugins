import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "config-note" };


const _sfc_main = {
  __name: 'Config',
  props: {
  pluginId: { type: String, default: 'StorageCleanup' },
},
  setup(__props) {



return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [...(_cache[0] || (_cache[0] = [
    _createElementVNode("strong", null, "存储清理已接入 MoviePilot", -1),
    _createElementVNode("span", null, "请从左侧“存储清理”进入完整页面。3000 端口页面继续保留。", -1)
  ]))]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-ed9f201d"]]);

export { Config as default };
