import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode} = await importShared('vue');


const _hoisted_1 = { class: "moe-config__section" };
const _hoisted_2 = { class: "moe-config__section" };
const _hoisted_3 = { class: "moe-config__section" };
const _hoisted_4 = { class: "moe-config__section" };
const _hoisted_5 = { class: "moe-config__section" };
const _hoisted_6 = { class: "moe-config__section" };
const _hoisted_7 = { class: "moe-config__section" };
const _hoisted_8 = { class: "moe-config__actions" };

const {computed,onMounted,ref,watch} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'MediaOverviewEnhancer' },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const DEFAULTS = {
  enabled: false,
  servers: [],
  libraries: [],
  auto_on_transfer: true,
  post_transfer_delay: 120,
  schedule_hours: 0,
  movie_enabled: true,
  movie_mode: 'expand',
  movie_min_chars: 120,
  movie_target_chars: 320,
  episode_enabled: true,
  episode_mode: 'auto',
  episode_min_chars: 40,
  episode_target_chars: 160,
  episode_always_rewrite: false,
  skip_specials: true,
  mv_enabled: true,
  mv_libraries: ['mv'],
  mv_min_chars: 60,
  mv_target_chars: 110,
  translate_foreign: true,
  ai_generate_when_missing: true,
  ai_when_source_short: false,
  tmdb_title_fallback: false,
  duplicate_detect: true,
  lock_overview: true,
  force_rewrite: false,
  concurrency: 2,
  max_items_per_run: 200,
  notify: true,
  show_sidebar_nav: true,
};

const props = __props;

const emit = __emit;

const saving = ref(false);
const validationMessage = ref('');
const serverOptions = ref([]);
const librariesText = ref('');
const mvLibrariesText = ref('mv');
const serversModel = ref([]);
const localConfig = ref({ ...DEFAULTS });

const base = computed(() => `plugin/${props.pluginId || 'MediaOverviewEnhancer'}`);
const movieModeItems = [
  { title: '扩写现有简介（推荐）', value: 'expand' },
  { title: '翻译英文简介', value: 'translate' },
  { title: '完全由 AI 生成', value: 'ai' },
];
const episodeModeItems = [
  { title: '智能：TMDB 优先 + 缺失时 AI', value: 'auto' },
  { title: '仅使用 TMDB 简介', value: 'tmdb' },
  { title: '全部由 AI 重写', value: 'ai' },
];

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function textValue(value) {
  return String(value ?? '').trim()
}

function asList(value) {
  if (Array.isArray(value)) return value.map(item => textValue(item)).filter(Boolean)
  if (value === null || value === undefined) return []
  return textValue(value)
    .split(/[,，\n]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

function applyConfig(source) {
  const merged = { ...DEFAULTS, ...clone(source) };
  localConfig.value = merged;
  serversModel.value = asList(merged.servers);
  librariesText.value = asList(merged.libraries).join(', ');
  mvLibrariesText.value = asList(merged.mv_libraries).join(', ') || 'mv';
}

async function loadServerOptions() {
  try {
    const data = unwrap(await props.api.get(`${base.value}/servers`));
    serverOptions.value = (data?.servers || [])
      .filter(item => item.name && item.name !== '-')
      .map(item => ({
        title: `${item.name}${item.connected ? '' : `（未连接：${item.message || ''}）`}`,
        value: item.name,
      }));
  } catch (err) {
    serverOptions.value = [];
  }
}

async function loadDefaults() {
  if (Object.keys(props.initialConfig || {}).length) return
  try {
    const data = unwrap(await props.api.get(`${base.value}/config`));
    if (data && typeof data === 'object') {
      applyConfig(data);
    }
  } catch (err) {
    // 忽略：使用组件内置默认值
  }
}

function buildPayload() {
  const payload = { ...localConfig.value };
  payload.servers = serversModel.value;
  payload.libraries = asList(librariesText.value);
  payload.mv_libraries = asList(mvLibrariesText.value).length ? asList(mvLibrariesText.value) : ['mv'];
  payload.post_transfer_delay = Number(payload.post_transfer_delay) || 0;
  payload.schedule_hours = Number(payload.schedule_hours) || 0;
  payload.movie_min_chars = Number(payload.movie_min_chars) || 0;
  payload.movie_target_chars = Number(payload.movie_target_chars) || 320;
  payload.episode_min_chars = Number(payload.episode_min_chars) || 0;
  payload.episode_target_chars = Number(payload.episode_target_chars) || 160;
  payload.mv_min_chars = Number(payload.mv_min_chars) || 0;
  payload.mv_target_chars = Number(payload.mv_target_chars) || 110;
  payload.concurrency = Number(payload.concurrency) || 2;
  payload.max_items_per_run = Number(payload.max_items_per_run) || 200;
  return payload
}

function saveConfig() {
  const payload = buildPayload();
  if (payload.movie_target_chars < 80) {
    validationMessage.value = '电影简介目标字数建议不少于 80 字。';
    return
  }
  if (payload.episode_target_chars < 40) {
    validationMessage.value = '分集简介目标字数建议不少于 40 字。';
    return
  }
  if (payload.mv_target_chars < 40) {
    validationMessage.value = 'MV 简介目标字数建议不少于 40 字。';
    return
  }
  validationMessage.value = '';
  saving.value = true;
  emit('save', payload);
  window.setTimeout(() => {
    saving.value = false;
  }, 600);
}

watch(
  () => props.initialConfig,
  value => {
    if (value && Object.keys(value).length) {
      applyConfig(value);
    }
  },
  { immediate: true, deep: true },
);

onMounted(() => {
  loadDefaults();
  loadServerOptions();
});

return (_ctx, _cache) => {
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VForm = _resolveComponent("VForm");

  return (_openBlock(), _createBlock(_component_VForm, { class: "moe-config" }, {
    default: _withCtx(() => [
      _cache[47] || (_cache[47] = _createElementVNode("div", { class: "moe-config__toolbar text-subtitle-1" }, "影视简介增强设置", -1)),
      _createElementVNode("section", _hoisted_1, [
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.enabled,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((localConfig.value.enabled) = $event)),
          label: "启用插件",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _cache[32] || (_cache[32] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 启用后才会在入库后自动补简介、执行定时补漏或手动批量任务。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.auto_on_transfer,
          "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((localConfig.value.auto_on_transfer) = $event)),
          label: "整理入库后自动补全该媒体",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VTextField, {
          modelValue: localConfig.value.post_transfer_delay,
          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((localConfig.value.post_transfer_delay) = $event)),
          type: "number",
          label: "入库后等待秒数（等 Emby 刮削完成，建议 60-180）",
          density: "comfortable",
          class: "mt-2"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VTextField, {
          modelValue: localConfig.value.schedule_hours,
          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((localConfig.value.schedule_hours) = $event)),
          type: "number",
          label: "定时补漏间隔（小时，0 表示不启用）",
          density: "comfortable"
        }, null, 8, ["modelValue"])
      ]),
      _createElementVNode("section", _hoisted_2, [
        _cache[33] || (_cache[33] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "媒体服务器范围", -1)),
        _createVNode(_component_VSelect, {
          modelValue: serversModel.value,
          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((serversModel).value = $event)),
          items: serverOptions.value,
          "item-title": "title",
          "item-value": "value",
          label: "Emby 服务器（留空表示全部）",
          multiple: "",
          chips: "",
          clearable: "",
          density: "comfortable"
        }, null, 8, ["modelValue", "items"]),
        _createVNode(_component_VTextField, {
          modelValue: librariesText.value,
          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((librariesText).value = $event)),
          label: "媒体库名称（逗号分隔，留空表示全部电影/剧集库）",
          density: "comfortable",
          "persistent-hint": "",
          hint: "例如：电影, 电视剧",
          class: "mt-2"
        }, null, 8, ["modelValue"])
      ]),
      _createElementVNode("section", _hoisted_3, [
        _cache[34] || (_cache[34] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "电影简介", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.movie_enabled,
          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((localConfig.value.movie_enabled) = $event)),
          label: "处理电影",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSelect, {
          modelValue: localConfig.value.movie_mode,
          "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((localConfig.value.movie_mode) = $event)),
          items: movieModeItems,
          label: "处理方式",
          density: "comfortable",
          class: "mt-2"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VRow, {
          dense: "",
          class: "mt-1"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.movie_min_chars,
                  "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((localConfig.value.movie_min_chars) = $event)),
                  type: "number",
                  label: "低于该字数才处理",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            }),
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.movie_target_chars,
                  "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((localConfig.value.movie_target_chars) = $event)),
                  type: "number",
                  label: "目标字数",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _createElementVNode("section", _hoisted_4, [
        _cache[35] || (_cache[35] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "剧集分集简介", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.episode_enabled,
          "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((localConfig.value.episode_enabled) = $event)),
          label: "处理剧集分集",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSelect, {
          modelValue: localConfig.value.episode_mode,
          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((localConfig.value.episode_mode) = $event)),
          items: episodeModeItems,
          label: "分集处理方式",
          density: "comfortable",
          class: "mt-2"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VRow, {
          dense: "",
          class: "mt-1"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.episode_min_chars,
                  "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((localConfig.value.episode_min_chars) = $event)),
                  type: "number",
                  label: "低于该字数才处理",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            }),
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.episode_target_chars,
                  "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((localConfig.value.episode_target_chars) = $event)),
                  type: "number",
                  label: "目标字数",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.episode_always_rewrite,
          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((localConfig.value.episode_always_rewrite) = $event)),
          label: "已有简介也交给 AI 重写",
          color: "primary",
          "hide-details": "",
          class: "mt-2"
        }, null, 8, ["modelValue"]),
        _cache[36] || (_cache[36] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 关闭时只在简介缺失、过短或同季多集重复时才处理，可显著减少大模型用量。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.skip_specials,
          "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((localConfig.value.skip_specials) = $event)),
          label: "跳过特别篇（第 0 季/S00）",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.duplicate_detect,
          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((localConfig.value.duplicate_detect) = $event)),
          label: "检测同季重复简介并重写",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"])
      ]),
      _createElementVNode("section", _hoisted_5, [
        _cache[37] || (_cache[37] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "MV 简介（音乐视频）", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.mv_enabled,
          "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((localConfig.value.mv_enabled) = $event)),
          label: "处理 MV",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VTextField, {
          modelValue: mvLibrariesText.value,
          "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((mvLibrariesText).value = $event)),
          label: "MV 媒体库名称（逗号分隔）",
          density: "comfortable",
          "persistent-hint": "",
          hint: "默认 mv；留空时会回退为 mv",
          class: "mt-2"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VRow, {
          dense: "",
          class: "mt-1"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.mv_min_chars,
                  "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((localConfig.value.mv_min_chars) = $event)),
                  type: "number",
                  label: "低于该字数才处理",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            }),
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.mv_target_chars,
                  "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((localConfig.value.mv_target_chars) = $event)),
                  type: "number",
                  label: "目标字数",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _cache[38] || (_cache[38] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " MV 没有 TMDB/IMDb 条目，简介只能由 AI 依据条目名与文件名线索生成。运行面板里需单独选「仅 MV」， 「全部」不会带上 MV，避免一次性产生大量大模型调用；已达字数的条目默认跳过，勾「强制重写」才会重做。 ", -1))
      ]),
      _createElementVNode("section", _hoisted_6, [
        _cache[39] || (_cache[39] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "数据源与写入", -1)),
        _cache[40] || (_cache[40] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 电影与剧集优先用 TMDB 中文简介；MV 没有 TMDB/IMDb 条目，只能由 AI 依据条目名与文件名线索生成。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.translate_foreign,
          "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((localConfig.value.translate_foreign) = $event)),
          label: "允许把英文简介翻译成中文",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.ai_generate_when_missing,
          "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((localConfig.value.ai_generate_when_missing) = $event)),
          label: "允许在无简介时由 AI 生成",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _cache[41] || (_cache[41] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " AI 生成只依据影片/剧集上下文，尽量不编造细节，但仍可能与真实剧情有出入，建议先试跑。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.ai_when_source_short,
          "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((localConfig.value.ai_when_source_short) = $event)),
          label: "素材不足或同季重复时改用 AI 生成",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _cache[42] || (_cache[42] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 开启后，TMDB 简介过短（翻译/扩写后仍不到上面的字数阈值）或同季多集简介雷同的条目， 会改由 AI 依据上下文生成更完整、彼此不同的简介；素材充足的条目不受影响。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.tmdb_title_fallback,
          "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((localConfig.value.tmdb_title_fallback) = $event)),
          label: "剧集无 TMDB 标识时按标题搜索兜底",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _cache[43] || (_cache[43] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 仅对剧集生效：当 Emby 里的剧集没有 TMDB 标识（未刮削）时，按「标题 + 年份」严格匹配 TMDB （要求标题高度一致、年份相差不超过一年），匹配到的剧集与 TMDB ID 会写入插件日志便于核对。 关闭时这类剧集会被整体跳过。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.lock_overview,
          "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((localConfig.value.lock_overview) = $event)),
          label: "写入后锁定 Overview 字段（防止 Emby 刷新覆盖）",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.force_rewrite,
          "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((localConfig.value.force_rewrite) = $event)),
          label: "默认强制重写（忽略字数阈值）",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"])
      ]),
      _createElementVNode("section", _hoisted_7, [
        _cache[44] || (_cache[44] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "运行控制", -1)),
        _createVNode(_component_VRow, { dense: "" }, {
          default: _withCtx(() => [
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.concurrency,
                  "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((localConfig.value.concurrency) = $event)),
                  type: "number",
                  label: "并发数（1-8）",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            }),
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.max_items_per_run,
                  "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((localConfig.value.max_items_per_run) = $event)),
                  type: "number",
                  label: "单次最多处理条数",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.notify,
          "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((localConfig.value.notify) = $event)),
          label: "任务完成发送通知",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.show_sidebar_nav,
          "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((localConfig.value.show_sidebar_nav) = $event)),
          label: "在主界面侧栏显示入口",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"])
      ]),
      (validationMessage.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 0,
            type: "error",
            variant: "tonal",
            density: "compact",
            class: "mx-4 mb-2"
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(validationMessage.value), 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      _createElementVNode("div", _hoisted_8, [
        _createVNode(_component_VBtn, {
          variant: "text",
          "min-width": "88",
          onClick: _cache[31] || (_cache[31] = $event => (emit('close')))
        }, {
          default: _withCtx(() => [...(_cache[45] || (_cache[45] = [
            _createTextVNode("取消", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_VBtn, {
          color: "primary",
          "min-width": "108",
          loading: saving.value,
          onClick: saveConfig
        }, {
          default: _withCtx(() => [...(_cache[46] || (_cache[46] = [
            _createTextVNode("保存", -1)
          ]))]),
          _: 1
        }, 8, ["loading"])
      ])
    ]),
    _: 1
  }))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-31581fa4"]]);

export { Config as default };
