import { a as __mf_19, b as __mf_9 } from './_plugin-vue_export-helper-C960cP-z.js';
import { B as BrushFlowWorkbench } from './BrushFlowWorkbench-CfskpesI.js';

const _sfc_main = {
  __name: 'AppPage',
  props: {
  api: { type: Object, default: () => ({}) },
  navKey: { type: String, default: 'main' },
  pluginId: { type: String, default: 'BrushFlow' },
},
  emits: ['action'],
  setup(__props) {





return (_ctx, _cache) => {
  return (__mf_19(), __mf_9(BrushFlowWorkbench, {
    api: __props.api,
    "plugin-id": __props.pluginId,
    onAction: _cache[0] || (_cache[0] = $event => (_ctx.$emit('action')))
  }, null, 8, ["api", "plugin-id"]))
}
}

};

export { _sfc_main as default };
