import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { A as AgentTokensManager } from './AgentTokensManager-ldQ2v6Va.js';
import { c as cloneConfig } from './_plugin-vue_export-helper-hPgBDeLJ.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "agenttokens-config" };

const {onMounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const localConfig = ref({ enabled: false, show_sidebar_nav: true, providers: [] });

// 重置本地配置中的单个供应商用量。
function resetUsage(providerId, index) {
  const providers = localConfig.value.providers || [];
  const providerIndex = providers.findIndex(provider => provider.id && provider.id === providerId);
  const targetIndex = providerIndex >= 0 ? providerIndex : index;
  if (!providers[targetIndex]) return
  providers[targetIndex].used_tokens = 0;
}

// 重置本地配置中的全部供应商用量。
function resetAllUsage() {
(localConfig.value.providers || []).forEach(provider => {
    provider.used_tokens = 0;
  });
}

// 通知宿主保存 Vue 配置。
function saveConfig() {
  emit('save', cloneConfig(localConfig.value));
}

onMounted(() => {
  localConfig.value = cloneConfig(props.initialConfig);
  if (localConfig.value.show_sidebar_nav === undefined) {
    localConfig.value.show_sidebar_nav = true;
  }
  if (!Array.isArray(localConfig.value.providers)) {
    localConfig.value.providers = [];
  }
});

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VToolbar, {
      density: "comfortable",
      color: "transparent"
    }, {
      default: _withCtx(() => [
        _cache[1] || (_cache[1] = _createElementVNode("div", { class: "text-h6 ms-3" }, "Agent Tokens 配置", -1)),
        _createVNode(_component_VSpacer),
        _createVNode(_component_VBtn, {
          icon: "mdi-content-save",
          variant: "text",
          color: "primary",
          onClick: saveConfig
        }),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VDivider),
    _createVNode(AgentTokensManager, {
      config: localConfig.value,
      "hide-title": "",
      onSave: saveConfig,
      onResetUsage: resetUsage,
      onResetAllUsage: resetAllUsage
    }, null, 8, ["config"])
  ]))
}
}

};

export { _sfc_main as default };
