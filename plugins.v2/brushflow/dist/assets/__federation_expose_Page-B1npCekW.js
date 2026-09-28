import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { B as BrushFlowWorkbench } from './BrushFlowWorkbench-ByYFfUXn.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
},
  emits: ['action', 'close'],
  setup(__props) {





return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(BrushFlowWorkbench, {
    api: __props.api,
    "plugin-id": "BrushFlow",
    "show-close": "",
    compact: "",
    onAction: _cache[0] || (_cache[0] = $event => (_ctx.$emit('action'))),
    onClose: _cache[1] || (_cache[1] = $event => (_ctx.$emit('close')))
  }, null, 8, ["api"]))
}
}

};

export { _sfc_main as default };
