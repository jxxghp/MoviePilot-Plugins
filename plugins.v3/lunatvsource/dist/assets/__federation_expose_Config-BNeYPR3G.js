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
  source_allowlist: 'suonizy.net,suoniapi.com,kuaichezy.com,caiji.kuaichezy.org,www.hongniuzy.com,www.hongniuzy2.com,wujinzy.net,wujinzy.me,api.wujinapi.me,wujinapi.me,guangsuzy.com,api.guangsuapi.com,ukuzy0.com,api.ukuapi88.com,www.xinlangzy.com,xinlangapi.com,okzyw.cc',
  mode: 'download',
  source_strategy: 'first',
  download_root: '',
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
  saving.value = true;
  try {
    // 这些能力由 MoviePilot 原生设置统一管理；旧版保存过的 false 值也不能关闭宿主桥接。
    const payload = {
      ...config,
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

onMounted(() => Object.assign(config, defaults, props.initialConfig || {}));

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VTextarea = _resolveComponent("VTextarea");
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
        _cache[6] || (_cache[6] = _createElementVNode("div", { class: "text-h6" }, "LunaTV 原生桥接配置", -1)),
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
      default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
        _createTextVNode(" 保存后，LunaTV/苹果 CMS 会作为 MoviePilot 的原生探索与媒体源出现；请直接使用 MoviePilot 的搜索、订阅和下载流程。 ", -1)
      ]))]),
      _: 1
    }),
    _createVNode(_component_VRow, { dense: "" }, {
      default: _withCtx(() => [
        _createVNode(_component_VCol, {
          cols: "12",
          md: "6"
        }, {
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
        _createVNode(_component_VCol, {
          cols: "12",
          md: "6"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSelect, {
              modelValue: config.source_strategy,
              "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.source_strategy) = $event)),
              items: [{ title: '按配置顺序选一个（推荐）', value: 'first' }, { title: '所有匹配源都排队', value: 'all' }],
              label: "资源站策略",
              variant: "outlined",
              density: "comfortable",
              "hide-details": "auto"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, { cols: "12" }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: config.download_root,
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.download_root) = $event)),
              label: "下载目录（可留空，自动复用 MoviePilot）",
              placeholder: "/media/incoming/lunatv",
              hint: "留空按电影/电视剧读取 MoviePilot 的本地目录。",
              "persistent-hint": "",
              variant: "outlined"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, { cols: "12" }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: config.config_url,
              "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.config_url) = $event)),
              label: "LunaTV 配置地址",
              variant: "outlined"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, { cols: "12" }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextarea, {
              modelValue: config.source_allowlist,
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.source_allowlist) = $event)),
              label: "启用资源站（逗号分隔）",
              rows: "2",
              variant: "outlined",
              "hide-details": "auto"
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
      default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
        _createTextVNode(" 目录、DeepSeek、TMDB、整理规则和媒体服务器均沿用 MoviePilot 设置；这里仅保留 LunaTV 源地址、资源站策略和可选目录覆盖。任务始终串行执行。 ", -1)
      ]))]),
      _: 1
    }),
    _createElementVNode("div", _hoisted_2, [
      _createVNode(_component_VBtn, {
        color: "primary",
        loading: saving.value,
        onClick: saveConfig
      }, {
        default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
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
