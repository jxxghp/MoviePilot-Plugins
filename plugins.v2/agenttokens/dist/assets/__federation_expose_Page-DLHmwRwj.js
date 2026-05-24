import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import AppPage from './__federation_expose_AppPage-D1Hk5N0X.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
},
  setup(__props) {



return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(AppPage, {
    api: __props.api,
    "plugin-id": "AgentTokens"
  }, null, 8, ["api"]))
}
}

};

export { _sfc_main as default };
