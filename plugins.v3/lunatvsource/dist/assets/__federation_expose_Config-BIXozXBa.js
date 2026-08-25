import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "pa-4" };
const _hoisted_2 = { class: "d-flex justify-end mt-4" };

const {onMounted,reactive,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'LunaTVSource' },
  initialConfig: { type: Object, default: () => ({}) },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;
const saving = ref(false);
const message = reactive({ text: '', type: 'info' });
const defaults = {
  enabled: false,
  config_url: 'https://raw.githubusercontent.com/hafrey1/LunaTV-config/main/LunaTV-config.json',
  source_allowlist: '',
  mode: 'download',
  source_strategy: 'first',
  download_root: '/downloads/未整理',
  use_moviepilot_dirs: true,
  ffmpeg_path: 'ffmpeg',
  queue_minutes: 1,
  ai_enabled: true,
  tmdb_association: true,
  moviepilot_organize: true,
  native_recognize: true,
  mediaserver_name: '',
};
const config = reactive({ ...defaults });

function showMessage(text, type = 'info') {
  message.text = text;
  message.type = type;
  if (text) setTimeout(() => { if (message.text === text) message.text = ''; }, 3500);
}

async function saveConfig() {
  if (typeof props.api?.put !== 'function') {
    showMessage('当前 MoviePilot 未提供配置保存接口', 'error');
    return
  }
  if (!String(config.download_root || '').trim()) {
    showMessage('请填写下载目录', 'error');
    return
  }
  saving.value = true;
  try {
    const payload = {
      ...config,
      source_allowlist: '',
      source_strategy: 'first',
      download_root: String(config.download_root || '').trim(),
      ai_enabled: true,
      tmdb_association: true,
      use_moviepilot_dirs: true,
      moviepilot_organize: true,
      native_recognize: true,
      mode: 'download',
    };
    const response = await props.api.put(`plugin/${props.pluginId || 'LunaTVSource'}`, payload);
    const result = response?.data ?? response;
    if (result?.success === false) throw new Error(result.message || '保存配置失败')
    emit('save', payload);
    showMessage('配置已保存', 'success');
  } catch (error) {
    showMessage(error?.message || '保存配置失败', 'error');
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  Object.assign(config, defaults, props.initialConfig || {});
  if (!String(config.download_root || '').trim()) config.download_root = defaults.download_root;
});

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VRow = _resolveComponent("VRow");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VToolbar, {
      density: "comfortable",
      color: "transparent",
      class: "px-0"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VIcon, {
          icon: "mdi-play-network",
          color: "primary",
          class: "me-2"
        }),
        _cache[4] || (_cache[4] = _createElementVNode("div", { class: "text-h6" }, "LunaTV 原生桥接配置", -1)),
        _createVNode(_component_VSpacer),
        _createVNode(_component_VBtn, {
          icon: "mdi-content-save",
          variant: "text",
          color: "success",
          loading: saving.value,
          title: "保存配置",
          onClick: saveConfig
        }, null, 8, ["loading"]),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          title: "关闭",
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VDivider, { class: "mb-4" }),
    (message.text)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 0,
          type: message.type,
          variant: "tonal",
          density: "compact",
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(message.text), 1)
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    _createVNode(_component_VAlert, {
      type: "info",
      variant: "tonal",
      density: "compact",
      class: "mb-4"
    }, {
      default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
        _createTextVNode(" 保存后，LunaTV/苹果 CMS 将接入 MoviePilot 的原生搜索、订阅与下载入口。请直接使用 MoviePilot 的原生搜索、订阅和下载流程。 ", -1)
      ]))]),
      _: 1
    }),
    _createVNode(_component_VRow, { dense: "" }, {
      default: _withCtx(() => [
        _createVNode(_component_VCol, { cols: "12" }, {
          default: _withCtx(() => [
            _createVNode(_component_VSwitch, {
              modelValue: config.enabled,
              "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.enabled) = $event)),
              label: "启用原生桥接",
              color: "success",
              "hide-details": ""
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, { cols: "12" }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: config.config_url,
              "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.config_url) = $event)),
              label: "LunaTV 配置地址",
              variant: "outlined"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, { cols: "12" }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: config.download_root,
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.download_root) = $event)),
              label: "下载目录",
              placeholder: "/downloads/未整理",
              hint: "m3u8 下载先写入此目录，完成后继续复用 MoviePilot 的整理规则。",
              "persistent-hint": "",
              variant: "outlined"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VAlert, {
      type: "warning",
      variant: "tonal",
      density: "compact",
      class: "mt-3"
    }, {
      default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
        _createTextVNode(" 目录、DeepSeek、TMDB、整理规则、媒体服务器和链接权限均沿用 MoviePilot 设置；订阅地址内的资源站全部读取。任务始终串行执行。 ", -1)
      ]))]),
      _: 1
    }),
    _createElementVNode("div", _hoisted_2, [
      _createVNode(_component_VBtn, {
        color: "primary",
        loading: saving.value,
        onClick: saveConfig
      }, {
        default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
          _createTextVNode("保存配置", -1)
        ]))]),
        _: 1
      }, 8, ["loading"])
    ])
  ]))
}
}

};

export { _sfc_main as default };
