import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { B as BrushFlowWorkbench } from './BrushFlowWorkbench-ByYFfUXn.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const {onMounted} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
},
  emits: ['layout', 'close'],
  setup(__props, { emit: __emit }) {



const emit = __emit;

onMounted(() => {
  emit('layout', { maxWidth: '80rem' });
});

return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(BrushFlowWorkbench, {
    api: __props.api,
    "plugin-id": "BrushFlow",
    "initial-tab": "config",
    "show-close": "",
    compact: "",
    onClose: _cache[0] || (_cache[0] = $event => (_ctx.$emit('close')))
  }, null, 8, ["api"]))
}
}

};

export { _sfc_main as default };
