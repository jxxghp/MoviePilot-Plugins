import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import AppPage from './__federation_expose_AppPage-1IwdIgsZ.js';

const {normalizeProps:_normalizeProps,guardReactiveProps:_guardReactiveProps,openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'LunaTVSource' },
  navKey: { type: String, default: 'main' },
},
  setup(__props) {



return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(AppPage, _normalizeProps(_guardReactiveProps(_ctx.$props)), null, 16))
}
}

};

export { _sfc_main as default };
