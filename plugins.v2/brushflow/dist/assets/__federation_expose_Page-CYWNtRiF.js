import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { B as BrushFlowWorkbench } from './BrushFlowWorkbench-CEPlntF9.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
},
  emits: ['action', 'switch', 'close'],
  setup(__props) {





return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(BrushFlowWorkbench, {
    api: __props.api,
    "plugin-id": "BrushFlow",
    "show-close": "",
    "show-switch": "",
    compact: "",
    onAction: _cache[0] || (_cache[0] = $event => (_ctx.$emit('action'))),
    onSwitch: _cache[1] || (_cache[1] = $event => (_ctx.$emit('switch'))),
    onClose: _cache[2] || (_cache[2] = $event => (_ctx.$emit('close')))
  }, null, 8, ["api"]))
}
}

};

export { _sfc_main as default };
