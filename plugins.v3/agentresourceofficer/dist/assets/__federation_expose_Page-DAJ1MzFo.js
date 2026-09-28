import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import Config from './__federation_expose_Config-SJKIC-xp.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {



const emit = __emit;

return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(Config, {
    api: __props.api,
    "initial-config": __props.initialConfig,
    onSave: _cache[0] || (_cache[0] = payload => emit('save', payload)),
    onClose: _cache[1] || (_cache[1] = $event => (emit('close')))
  }, null, 8, ["api", "initial-config"]))
}
}

};

export { _sfc_main as default };
