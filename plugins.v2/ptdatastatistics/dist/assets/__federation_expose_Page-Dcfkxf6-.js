import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { P as PTStatsWorkbench } from './PTStatsWorkbench-97SNm8Dp.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'PTDataStatistics' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
},
  emits: ['action', 'switch', 'close'],
  setup(__props) {




return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(PTStatsWorkbench, {
    api: __props.api,
    "plugin-id": __props.pluginId,
    "show-close": "",
    compact: "",
    onAction: _cache[0] || (_cache[0] = $event => (_ctx.$emit('action'))),
    onClose: _cache[1] || (_cache[1] = $event => (_ctx.$emit('close')))
  }, null, 8, ["api", "plugin-id"]))
}
}

};

export { _sfc_main as default };
