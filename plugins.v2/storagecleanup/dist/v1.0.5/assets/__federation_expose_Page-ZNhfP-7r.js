import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import AppPage, { c as createLatestPlanApi } from './__federation_expose_AppPage-Dw3pzGGM.js';

const {unref:_unref,openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'StorageCleanup' },
},
  setup(__props) {

const props = __props;

const guardedApi = createLatestPlanApi({
  get: (...args) => props.api.get(...args),
  post: (...args) => props.api.post(...args),
});

return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(AppPage, {
    api: _unref(guardedApi),
    "plugin-id": __props.pluginId
  }, null, 8, ["api", "plugin-id"]))
}
}

};

export { _sfc_main as default };
