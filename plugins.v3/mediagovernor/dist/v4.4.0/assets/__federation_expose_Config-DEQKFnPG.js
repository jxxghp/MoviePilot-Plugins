import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,vModelCheckbox:_vModelCheckbox,withDirectives:_withDirectives,createTextVNode:_createTextVNode,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "config-page" };

const {reactive} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: { initialConfig: { type: Object, default: () => ({}) } },
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const config = reactive({ enabled: false, ...props.initialConfig });

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("main", _hoisted_1, [
    _cache[4] || (_cache[4] = _createElementVNode("h2", null, "媒体治理设置", -1)),
    _createElementVNode("label", null, [
      _withDirectives(_createElementVNode("input", {
        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.enabled) = $event)),
        type: "checkbox"
      }, null, 512), [
        [_vModelCheckbox, config.enabled]
      ]),
      _cache[3] || (_cache[3] = _createTextVNode(" 启用媒体治理", -1))
    ]),
    _cache[5] || (_cache[5] = _createElementVNode("p", null, "启用后才可打开治理台；检查只在你点击开始后发生。", -1)),
    _cache[6] || (_cache[6] = _createElementVNode("aside", null, "插件不会保存路径、不会自行删除、移动或改名文件。真正整理由 MoviePilot 官方预览和确认流程执行。", -1)),
    _createElementVNode("footer", null, [
      _createElementVNode("button", {
        onClick: _cache[1] || (_cache[1] = $event => (emit('close')))
      }, "关闭"),
      _createElementVNode("button", {
        class: "primary",
        onClick: _cache[2] || (_cache[2] = $event => (emit('save', config)))
      }, "保存")
    ])
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-44d38bb6"]]);

export { Config as default };
