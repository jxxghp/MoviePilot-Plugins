import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { P as PTStatsWorkbench } from './PTStatsWorkbench-97SNm8Dp.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const {onMounted} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'PTDataStatistics' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
},
  emits: ['layout', 'save', 'close', 'switch'],
  setup(__props, { emit: __emit }) {


const emit = __emit;

onMounted(() => emit('layout', { maxWidth: '80rem' }));

return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(PTStatsWorkbench, {
    api: __props.api,
    "plugin-id": __props.pluginId,
    "initial-settings": __props.initialConfig,
    "host-managed-config": "",
    "initial-tab": "config",
    "show-close": "",
    compact: "",
    onSave: _cache[0] || (_cache[0] = $event => (_ctx.$emit('save', $event))),
    onClose: _cache[1] || (_cache[1] = $event => (_ctx.$emit('close')))
  }, null, 8, ["api", "plugin-id", "initial-settings"]))
}
}

};

export { _sfc_main as default };
