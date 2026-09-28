import { importShared } from '../../v1.0.3/assets/__federation_fn_import-JrT3xvdd.js';
import AppPage from '../../v1.0.3/assets/__federation_expose_AppPage-mb1zO2qt.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');

function createLatestPlanApi(api) {
  let generation = 0;
  let latestPlanResult = null;

  return {
    ...api,
    get(...args) {
      return api.get(...args);
    },
    post(path, body, ...args) {
      if (!String(path || '').endsWith('/plan')) {
        return api.post(path, body, ...args);
      }

      const requestGeneration = ++generation;
      let rawRequest;
      try {
        rawRequest = Promise.resolve(api.post(path, body, ...args));
      } catch (error) {
        rawRequest = Promise.reject(error);
      }

      const result = (async () => {
        try {
          const response = await rawRequest;
          if (requestGeneration !== generation && latestPlanResult) {
            return await latestPlanResult;
          }
          return response;
        } catch (error) {
          if (requestGeneration !== generation && latestPlanResult) {
            return await latestPlanResult;
          }
          throw error;
        }
      })();
      latestPlanResult = result;
      return result;
    },
  };
}

const _sfc_main = {
  __name: 'Page',
  props: {
    api: { type: Object, default: () => ({}) },
    pluginId: { type: String, default: 'StorageCleanup' },
  },
  setup(__props) {
    const guardedApi = createLatestPlanApi({
      get: (...args) => __props.api.get(...args),
      post: (...args) => __props.api.post(...args),
    });

    return (_ctx, _cache) => {
      return (_openBlock(), _createBlock(AppPage, {
        api: guardedApi,
        "plugin-id": __props.pluginId
      }, null, 8, ["plugin-id"]));
    };
  }
};

export { _sfc_main as default };
