import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode} = await importShared('vue');


const _hoisted_1 = { class: "moe-config__section" };
const _hoisted_2 = { class: "moe-config__section" };
const _hoisted_3 = { class: "moe-config__section" };
const _hoisted_4 = { class: "moe-config__section" };
const _hoisted_5 = { class: "moe-config__section" };
const _hoisted_6 = { class: "moe-config__section" };
const _hoisted_7 = { class: "moe-config__section" };
const _hoisted_8 = { class: "moe-config__section" };
const _hoisted_9 = { class: "moe-config__actions" };

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
  episode_min_chars: 80,
  episode_target_chars: 160,
  episode_always_rewrite: false,
  skip_specials: true,
  mv_enabled: true,
  mv_libraries: ['mv'],
  mv_min_chars: 60,
  mv_target_chars: 110,
  mv_write_people: true,
  mv_people_role: '演唱',
  mv_member_enabled: true,
  mv_member_role: '成员',
  mv_member_name_mode: 'zh',
  mv_member_source: 'both',
  mv_write_nfo: true,
  mv_people_avatar: true,
  mv_split_collab: true,
  mv_self_heal: true,
  mv_nfo_root: 'movie',
  nfo_path_map: '/media/:/medias/media/',
  translate_foreign: true,
  ai_generate_when_missing: true,
  ai_when_source_short: false,
  tmdb_title_fallback: false,
  duplicate_detect: true,
  lock_overview: true,
  force_rewrite: false,
  quality_gate: true,
  quality_min_cjk_ratio: 0.25,
  llm_retries: 2,
  backup_days: 30,
  rollback_max: 200,
  concurrency: 2,
  max_items_per_run: 200,
  scan_days: 0,
  notify: true,
  notify_failure: true,
  notify_daily: false,
  notify_daily_time: '21:00',
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
const dailyStats = ref(null);

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
const memberNameModeItems = [
  { title: '中文译名（如 李彩琳）', value: 'zh' },
  { title: '原始名称（如 CL）', value: 'original' },
  { title: '中文 + 原名（如 李彩琳 (CL)）', value: 'both' },
];
const memberSourceItems = [
  { title: 'MusicBrainz + Wikidata（推荐）', value: 'both' },
  { title: '仅 MusicBrainz', value: 'musicbrainz' },
  { title: '仅 Wikidata（自带中文名）', value: 'wikidata' },
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

function normalizeHhmm(value) {
  const match = String(value || '').trim().match(/^(\d{1,2}):(\d{1,2})/);
  if (!match) return '21:00'
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (!Number.isFinite(hour) || !Number.isFinite(minute) || hour > 23 || minute > 59) return '21:00'
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
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

async function loadDailyStats() {
  try {
    const data = unwrap(await props.api.get(`${base.value}/status`));
    dailyStats.value = data?.daily || null;
  } catch (err) {
    dailyStats.value = null;
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
  payload.mv_people_role = textValue(payload.mv_people_role) || '演唱';
  payload.mv_member_role = textValue(payload.mv_member_role) || '成员';
  payload.concurrency = Number(payload.concurrency) || 2;
  payload.max_items_per_run = Number(payload.max_items_per_run) || 200;
  payload.notify_daily_time = normalizeHhmm(payload.notify_daily_time);
  payload.quality_min_cjk_ratio = Number(payload.quality_min_cjk_ratio) || 0.25;
  payload.llm_retries = Number(payload.llm_retries) || 0;
  payload.backup_days = Number(payload.backup_days) || 0;
  payload.rollback_max = Number(payload.rollback_max) || 200;
  payload.scan_days = Number(payload.scan_days) || 0;
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
  loadDailyStats();
});

return (_ctx, _cache) => {
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VForm = _resolveComponent("VForm");

  return (_openBlock(), _createBlock(_component_VForm, { class: "moe-config" }, {
    default: _withCtx(() => [
      _cache[72] || (_cache[72] = _createElementVNode("div", { class: "moe-config__toolbar text-subtitle-1" }, "影视简介增强设置", -1)),
      (dailyStats.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 0,
            type: "info",
            variant: "tonal",
            density: "compact",
            class: "mx-4 mb-2"
          }, {
            default: _withCtx(() => [
              _createTextVNode(" 今日处理：成功 " + _toDisplayString(dailyStats.value.updated || 0) + " 条 · 跳过 " + _toDisplayString(dailyStats.value.skipped || 0) + " 条 · 失败 " + _toDisplayString(dailyStats.value.failed || 0) + " 条（共 " + _toDisplayString(dailyStats.value.runs || 0) + " 轮） ", 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      _createElementVNode("section", _hoisted_1, [
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.enabled,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((localConfig.value.enabled) = $event)),
          label: "启用插件",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _cache[53] || (_cache[53] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 启用后才会在入库后自动补简介、执行定时补漏或手动批量任务。 ", -1)),
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
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VTextField, {
          modelValue: localConfig.value.scan_days,
          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((localConfig.value.scan_days) = $event)),
          type: "number",
          label: "增量扫描天数（0 表示全库；只处理最近 N 天入库的电影/剧集）",
          density: "comfortable",
          "persistent-hint": "",
          hint: "用于减少重复全库扫描；MV 的 NFO / 头像自检不受此限制"
        }, null, 8, ["modelValue"])
      ]),
      _createElementVNode("section", _hoisted_2, [
        _cache[54] || (_cache[54] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "媒体服务器范围", -1)),
        _createVNode(_component_VSelect, {
          modelValue: serversModel.value,
          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((serversModel).value = $event)),
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
          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((librariesText).value = $event)),
          label: "媒体库名称（逗号分隔，留空表示全部电影/剧集库）",
          density: "comfortable",
          "persistent-hint": "",
          hint: "例如：电影, 电视剧",
          class: "mt-2"
        }, null, 8, ["modelValue"])
      ]),
      _createElementVNode("section", _hoisted_3, [
        _cache[55] || (_cache[55] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "电影简介", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.movie_enabled,
          "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((localConfig.value.movie_enabled) = $event)),
          label: "处理电影",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSelect, {
          modelValue: localConfig.value.movie_mode,
          "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((localConfig.value.movie_mode) = $event)),
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
                  "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((localConfig.value.movie_min_chars) = $event)),
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
                  "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((localConfig.value.movie_target_chars) = $event)),
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
        _cache[56] || (_cache[56] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "剧集分集简介", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.episode_enabled,
          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((localConfig.value.episode_enabled) = $event)),
          label: "处理剧集分集",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSelect, {
          modelValue: localConfig.value.episode_mode,
          "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((localConfig.value.episode_mode) = $event)),
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
                  "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((localConfig.value.episode_min_chars) = $event)),
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
                  "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((localConfig.value.episode_target_chars) = $event)),
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
          "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((localConfig.value.episode_always_rewrite) = $event)),
          label: "已有简介也交给 AI 重写",
          color: "primary",
          "hide-details": "",
          class: "mt-2"
        }, null, 8, ["modelValue"]),
        _cache[57] || (_cache[57] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 关闭时只在简介缺失、过短或同季多集重复时才处理，可显著减少大模型用量。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.skip_specials,
          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((localConfig.value.skip_specials) = $event)),
          label: "跳过特别篇（第 0 季/S00）",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.duplicate_detect,
          "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((localConfig.value.duplicate_detect) = $event)),
          label: "检测同季重复简介并重写",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"])
      ]),
      _createElementVNode("section", _hoisted_5, [
        _cache[58] || (_cache[58] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "MV 简介（音乐视频）", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.mv_enabled,
          "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((localConfig.value.mv_enabled) = $event)),
          label: "处理 MV",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VTextField, {
          modelValue: mvLibrariesText.value,
          "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((mvLibrariesText).value = $event)),
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
                  "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((localConfig.value.mv_min_chars) = $event)),
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
                  "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((localConfig.value.mv_target_chars) = $event)),
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
          modelValue: localConfig.value.mv_write_people,
          "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((localConfig.value.mv_write_people) = $event)),
          label: "把解析出的艺人写入 Emby 演员",
          color: "primary",
          "hide-details": "",
          class: "mt-2"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VTextField, {
          modelValue: localConfig.value.mv_people_role,
          "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((localConfig.value.mv_people_role) = $event)),
          label: "演员角色名（默认「演唱」）",
          density: "comfortable",
          disabled: !localConfig.value.mv_write_people,
          "persistent-hint": "",
          hint: "写入 Emby 的 People 字段，显示在条目「演员」区域",
          class: "mt-2"
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.mv_member_enabled,
          "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((localConfig.value.mv_member_enabled) = $event)),
          label: "把团队成员也写入演员",
          color: "primary",
          "hide-details": "",
          disabled: !localConfig.value.mv_write_people,
          class: "mt-2"
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VTextField, {
          modelValue: localConfig.value.mv_member_role,
          "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((localConfig.value.mv_member_role) = $event)),
          label: "成员角色名（默认「成员」）",
          density: "comfortable",
          disabled: !localConfig.value.mv_write_people || !localConfig.value.mv_member_enabled,
          "persistent-hint": "",
          hint: "成员名单取自 MusicBrainz，团体与成员各占一个演员条目",
          class: "mt-2"
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VSelect, {
          modelValue: localConfig.value.mv_member_name_mode,
          "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((localConfig.value.mv_member_name_mode) = $event)),
          items: memberNameModeItems,
          label: "成员名显示方式",
          density: "comfortable",
          disabled: !localConfig.value.mv_write_people || !localConfig.value.mv_member_enabled,
          class: "mt-2"
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VSelect, {
          modelValue: localConfig.value.mv_member_source,
          "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((localConfig.value.mv_member_source) = $event)),
          items: memberSourceItems,
          label: "成员数据源",
          density: "comfortable",
          disabled: !localConfig.value.mv_write_people || !localConfig.value.mv_member_enabled,
          "persistent-hint": "",
          hint: "Wikidata 自带中文成员名，MusicBrainz 覆盖更广，两者取并集"
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.mv_write_nfo,
          "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((localConfig.value.mv_write_nfo) = $event)),
          label: "生成 NFO 元数据文件（供 Kodi / Jellyfin 等读取）",
          color: "primary",
          "hide-details": "",
          disabled: !localConfig.value.mv_write_people,
          class: "mt-2"
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.mv_people_avatar,
          "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((localConfig.value.mv_people_avatar) = $event)),
          label: "自动补演员头像（TMDB / Wikidata 取图）",
          color: "primary",
          "hide-details": "",
          disabled: !localConfig.value.mv_write_people
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.mv_split_collab,
          "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((localConfig.value.mv_split_collab) = $event)),
          label: "拆分合作艺人（A & B 各自署名并取头像）",
          color: "primary",
          "hide-details": "",
          "persistent-hint": "",
          hint: "合作署名不是自然人，查不到头像；拆开后每位艺人可单独补图",
          disabled: !localConfig.value.mv_write_people
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.mv_self_heal,
          "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((localConfig.value.mv_self_heal) = $event)),
          label: "自检并补全缺失 / 过期的 NFO 与演员头像",
          color: "primary",
          "hide-details": "",
          disabled: !localConfig.value.mv_write_people,
          class: "mt-2"
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VSelect, {
          modelValue: localConfig.value.mv_nfo_root,
          "onUpdate:modelValue": _cache[32] || (_cache[32] = $event => ((localConfig.value.mv_nfo_root) = $event)),
          items: [
          { title: 'movie（Emby / Kodi 视频库）', value: 'movie' },
          { title: 'musicvideo（Kodi 音乐视频库）', value: 'musicvideo' },
        ],
          label: "NFO 根元素",
          density: "comfortable",
          disabled: !localConfig.value.mv_write_nfo,
          class: "mt-2"
        }, null, 8, ["modelValue", "disabled"]),
        _createVNode(_component_VTextField, {
          modelValue: localConfig.value.nfo_path_map,
          "onUpdate:modelValue": _cache[33] || (_cache[33] = $event => ((localConfig.value.nfo_path_map) = $event)),
          label: "NFO 路径映射（服务器路径:本地路径）",
          density: "comfortable",
          disabled: !localConfig.value.mv_write_nfo,
          "persistent-hint": "",
          hint: "默认 /media/:/medias/media/；多组用分号分隔（如 /media/:/medias/media/;/mv2/:/medias/media/MV2/）"
        }, null, 8, ["modelValue", "disabled"]),
        _cache[59] || (_cache[59] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " MV 没有 TMDB/IMDb 条目，简介只能由 AI 依据条目名与文件名线索生成。运行面板里需单独选「仅 MV」， 「全部」不会带上 MV，避免一次性产生大量大模型调用；已达字数的条目默认跳过，勾「强制重写」才会重做。 ", -1))
      ]),
      _createElementVNode("section", _hoisted_6, [
        _cache[60] || (_cache[60] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "数据源与写入", -1)),
        _cache[61] || (_cache[61] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 电影与剧集优先用 TMDB 中文简介；MV 没有 TMDB/IMDb 条目，只能由 AI 依据条目名与文件名线索生成。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.translate_foreign,
          "onUpdate:modelValue": _cache[34] || (_cache[34] = $event => ((localConfig.value.translate_foreign) = $event)),
          label: "允许把英文简介翻译成中文",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.ai_generate_when_missing,
          "onUpdate:modelValue": _cache[35] || (_cache[35] = $event => ((localConfig.value.ai_generate_when_missing) = $event)),
          label: "允许在无简介时由 AI 生成",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _cache[62] || (_cache[62] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " AI 生成只依据影片/剧集上下文，尽量不编造细节，但仍可能与真实剧情有出入，建议先试跑。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.ai_when_source_short,
          "onUpdate:modelValue": _cache[36] || (_cache[36] = $event => ((localConfig.value.ai_when_source_short) = $event)),
          label: "素材不足或同季重复时改用 AI 生成",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _cache[63] || (_cache[63] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 开启后，TMDB 简介过短（翻译/扩写后仍不到上面的字数阈值）或同季多集简介雷同的条目， 会改由 AI 依据上下文生成更完整、彼此不同的简介；素材充足的条目不受影响。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.tmdb_title_fallback,
          "onUpdate:modelValue": _cache[37] || (_cache[37] = $event => ((localConfig.value.tmdb_title_fallback) = $event)),
          label: "剧集无 TMDB 标识时按标题搜索兜底",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _cache[64] || (_cache[64] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 仅对剧集生效：当 Emby 里的剧集没有 TMDB 标识（未刮削）时，按「标题 + 年份」严格匹配 TMDB （要求标题高度一致、年份相差不超过一年），匹配到的剧集与 TMDB ID 会写入插件日志便于核对。 关闭时这类剧集会被整体跳过。 ", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.lock_overview,
          "onUpdate:modelValue": _cache[38] || (_cache[38] = $event => ((localConfig.value.lock_overview) = $event)),
          label: "写入后锁定 Overview 字段（防止 Emby 刷新覆盖）",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.force_rewrite,
          "onUpdate:modelValue": _cache[39] || (_cache[39] = $event => ((localConfig.value.force_rewrite) = $event)),
          label: "默认强制重写（忽略字数阈值）",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VDivider, { class: "my-3" }),
        _cache[65] || (_cache[65] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "质量与安全", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.quality_gate,
          "onUpdate:modelValue": _cache[40] || (_cache[40] = $event => ((localConfig.value.quality_gate) = $event)),
          label: "质量闸门（中文占比 / 技术词 / 模板句）",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _cache[66] || (_cache[66] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 开启后，未翻译的外文简介、仍在描述画质/编码的文案、过于模板化的空泛简介会被判为失败并进入失败清单， 可一键重试，不会写进媒体库。 ", -1)),
        _createVNode(_component_VRow, { dense: "" }, {
          default: _withCtx(() => [
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.quality_min_cjk_ratio,
                  "onUpdate:modelValue": _cache[41] || (_cache[41] = $event => ((localConfig.value.quality_min_cjk_ratio) = $event)),
                  type: "number",
                  step: "0.05",
                  label: "中文占比下限（0-1，默认 0.25）",
                  density: "comfortable",
                  disabled: !localConfig.value.quality_gate
                }, null, 8, ["modelValue", "disabled"])
              ]),
              _: 1
            }),
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.llm_retries,
                  "onUpdate:modelValue": _cache[42] || (_cache[42] = $event => ((localConfig.value.llm_retries) = $event)),
                  type: "number",
                  label: "大模型失败重试次数（0-5）",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
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
                  modelValue: localConfig.value.backup_days,
                  "onUpdate:modelValue": _cache[43] || (_cache[43] = $event => ((localConfig.value.backup_days) = $event)),
                  type: "number",
                  label: "旧简介备份保留天数（0 表示不过期）",
                  density: "comfortable",
                  "persistent-hint": "",
                  hint: "写入前会保存旧简介，可在详情页回滚"
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
                  modelValue: localConfig.value.rollback_max,
                  "onUpdate:modelValue": _cache[44] || (_cache[44] = $event => ((localConfig.value.rollback_max) = $event)),
                  type: "number",
                  label: "最多保留备份条数",
                  density: "comfortable"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _createElementVNode("section", _hoisted_7, [
        _cache[67] || (_cache[67] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "运行控制", -1)),
        _createVNode(_component_VRow, { dense: "" }, {
          default: _withCtx(() => [
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.concurrency,
                  "onUpdate:modelValue": _cache[45] || (_cache[45] = $event => ((localConfig.value.concurrency) = $event)),
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
                  "onUpdate:modelValue": _cache[46] || (_cache[46] = $event => ((localConfig.value.max_items_per_run) = $event)),
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
          modelValue: localConfig.value.show_sidebar_nav,
          "onUpdate:modelValue": _cache[47] || (_cache[47] = $event => ((localConfig.value.show_sidebar_nav) = $event)),
          label: "在主界面侧栏显示入口",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"])
      ]),
      _createElementVNode("section", _hoisted_8, [
        _cache[68] || (_cache[68] = _createElementVNode("div", { class: "text-subtitle-2 mb-2" }, "通知推送", -1)),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.notify,
          "onUpdate:modelValue": _cache[48] || (_cache[48] = $event => ((localConfig.value.notify) = $event)),
          label: "任务完成通知（含成功 / 跳过 / 失败统计）",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.notify_failure,
          "onUpdate:modelValue": _cache[49] || (_cache[49] = $event => ((localConfig.value.notify_failure) = $event)),
          label: "有失败条目时额外提醒",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VDivider, { class: "my-2" }),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.notify_daily,
          "onUpdate:modelValue": _cache[50] || (_cache[50] = $event => ((localConfig.value.notify_daily) = $event)),
          label: "每日成功汇总通知",
          color: "primary",
          "hide-details": ""
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VRow, {
          dense: "",
          class: "mt-2"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCol, {
              cols: "12",
              md: "6"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTextField, {
                  modelValue: localConfig.value.notify_daily_time,
                  "onUpdate:modelValue": _cache[51] || (_cache[51] = $event => ((localConfig.value.notify_daily_time) = $event)),
                  type: "time",
                  label: "每天发送时间",
                  density: "comfortable",
                  disabled: !localConfig.value.notify_daily,
                  "persistent-hint": "",
                  hint: "例如 21:00，到点发送当天成功 / 跳过 / 失败条数"
                }, null, 8, ["modelValue", "disabled"])
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _cache[69] || (_cache[69] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, " 通知使用 MoviePilot 已配置的消息渠道；每日汇总统计当天 0 点起的处理结果。 ", -1))
      ]),
      (validationMessage.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 1,
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
      _createElementVNode("div", _hoisted_9, [
        _createVNode(_component_VBtn, {
          variant: "text",
          "min-width": "88",
          onClick: _cache[52] || (_cache[52] = $event => (emit('close')))
        }, {
          default: _withCtx(() => [...(_cache[70] || (_cache[70] = [
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
          default: _withCtx(() => [...(_cache[71] || (_cache[71] = [
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-41b20cbb"]]);

export { Config as default };
