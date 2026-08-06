import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,normalizeProps:_normalizeProps,guardReactiveProps:_guardReactiveProps,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "fspw-config-root pa-4" };
const _hoisted_2 = { class: "mb-3" };
const _hoisted_3 = { class: "d-flex align-center mb-1" };
const _hoisted_4 = { class: "source-name text-caption" };
const _hoisted_5 = {
  key: 1,
  class: "text-grey text-caption"
};
const _hoisted_6 = { class: "d-flex justify-end gap-2" };

const {reactive,ref,computed,onMounted} = await importShared('vue');


const API_BASE = 'plugin/FullScreenPosterWall';

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

// 参考 MoviePilot-Plugins 官方 agenttokens 的 Config.vue 写法：
// 保存完全交给宿主前端（emit('save', cfg)），宿主会用 api.put('plugin/{id}', cfg)
// 持久化。在 baseURL='api/v1/' 的 axios 下，绝对不能在组件里写 'api/v1/plugin/...'，
// 否则会变成 'api/v1/api/v1/plugin/...'（404 双前缀）。
const props = __props;

const emit = __emit;

// 与 Page.vue 相同：宿主把主框架 axios 挂在 window.MoviePilotAPI 上，
// baseURL 已是 api/v1/，插件内路径用 'plugin/FullScreenPosterWall/...'。
function getApi() {
  return (typeof window !== 'undefined' ? window.MoviePilotAPI : null)
}

const defaultSourceConfig = {
  'recommend/tmdb_trending': ['movie', 'tv'],
  'recommend/tmdb_movies': ['movie', 'tv'],
  'recommend/tmdb_tvs': ['movie', 'tv'],
};
const effectOptions = [
  { title: '照片 (Photos) — 幻灯片', value: 'photos' },
  { title: '流动拼贴 (Shifting Tiles)', value: 'shiftingtiles' },
  { title: '环形画廊 (Ring Gallery) — 3D 环廊', value: 'ring3d' },
  { title: '纵深穿梭 (Depth Tunnel)', value: 'depthtunnel' },
  { title: '滑动面板 (Sliding Panels)', value: 'slidingpanels' },
  { title: '浮动 (Floating) — 漂移', value: 'floating' },
  { title: '怀旧冲印 (Vintage Prints)', value: 'vintage' },
  { title: '光舞 (Light Dance)', value: 'lightdance' },
];
const posterCountOptions = [30, 60, 120, 180, 240];

const imageTypeOptions = [
  { title: '背景大图 (backdrop)', value: 'backdrop' },
  { title: '带Logo的背景大图 (logo)', value: 'logo' },
  { title: '海报 (poster)', value: 'poster' },
];

const defaults = {
  enabled: false,
  source_config: { ...defaultSourceConfig },
  effect: 'photos',
  image_type: 'backdrop',
  interval: 8,
  poster_count: 60,
  refresh_minutes: 60,
  autoplay: true,
  show_dashboard: true,
  shuffle: false,
  hide_text: false,
};

const local = reactive({ ...defaults });

// ─── 动态数据源列表 ───────────────────────────────────────
const sourceList = ref([]);
const sourcesLoading = ref(false);
const sourcesError = ref('');

function natLabel(nat) {
  return nat === 'movie' ? '电影源' : nat === 'tv' ? '剧集源' : '混合源'
}
function hasType(apiPath, type) {
  const t = local.source_config?.[apiPath];
  return Array.isArray(t) && t.includes(type)
}
// 下拉选中集 ↔ source_config 双向映射：
// 勾选时按天然类型给默认（混合源全开，单类型源只开对应侧）
const selectedPaths = computed({
  get: () => Object.entries(local.source_config || {})
    .filter(([, t]) => Array.isArray(t) && t.length)
    .map(([k]) => k),
  set: (paths) => {
    const cfg = {};
    for (const p of paths) {
      const s = sourceList.value.find(x => x.api_path === p);
      const prev = (local.source_config || {})[p];
      if (Array.isArray(prev) && prev.length) { cfg[p] = prev; continue }
      cfg[p] = !s ? ['movie', 'tv'] : s.nat === 'movie' ? ['movie'] : s.nat === 'tv' ? ['tv'] : ['movie', 'tv'];
    }
    local.source_config = cfg;
  },
});
// 只有已勾选的混合源才展开电影/电视剧行
const enabledMixedSources = computed(() =>
  sourceList.value.filter(s => s.nat === 'mixed' && selectedPaths.value.includes(s.api_path))
);
function toggleType(apiPath, type, on) {
  const cfg = { ...(local.source_config || {}) };
  const cur = new Set(Array.isArray(cfg[apiPath]) ? cfg[apiPath] : []);
  if (on) cur.add(type);
  else cur.delete(type);
  const arr = ['movie', 'tv'].filter(t => cur.has(t));
  if (arr.length) cfg[apiPath] = arr;
  else delete cfg[apiPath]; // 两侧都取消 = 停用该源
  local.source_config = cfg;
}

async function loadSources() {
  const api = getApi();
  if (!api) {
    sourcesError.value = '宿主 API 未就绪，数据源列表加载失败（保存不受影响）';
    return
  }
  sourcesLoading.value = true;
  sourcesError.value = '';
  try {
    const raw = await api.get(`${API_BASE}/sources`);
    // 主框架 axios 拦截器已解包：raw 通常就是后端 body {success, data}；
    // 少数版本可能仍套一层 axios response（raw.data 才是 body），两种都兼容。
    const payload = (raw && typeof raw === 'object' && 'success' in raw) ? raw : (raw?.data ?? raw);
    if (payload?.success) {
      sourceList.value = payload.data?.sources || [];
      // 后端返回的当前选择优先于 initialConfig（权威状态）
      const sel = payload.data?.selected;
      if (sel && Object.keys(sel).length) {
        local.source_config = sel;
      }
    } else {
      sourcesError.value = payload?.message || '数据源列表加载失败（保存不受影响）';
    }
  } catch (e) {
    sourcesError.value = '数据源列表加载失败（保存不受影响）';
  } finally {
    sourcesLoading.value = false;
  }
}

onMounted(() => {
  // 用宿主传入的 initialConfig 覆盖默认值
  const ic = props.initialConfig;
  if (ic && typeof ic === 'object') {
    Object.keys(defaults).forEach(k => {
      if (ic[k] !== undefined) local[k] = ic[k];
    });
  }
  loadSources();
});

function onSave() {
  // 通知宿主前端保存：MoviePilot 监听 @save 然后用 api.put('plugin/{id}', cfg) 持久化
  emit('save', JSON.parse(JSON.stringify(local)));
}

function onReset() {
  Object.assign(local, defaults);
}

return (_ctx, _cache) => {
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_progress_circular = _resolveComponent("v-progress-circular");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_list_item = _resolveComponent("v-list-item");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_checkbox = _resolveComponent("v-checkbox");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card = _resolveComponent("v-card");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, {
      variant: "outlined",
      class: "pa-4 mb-3"
    }, {
      default: _withCtx(() => [
        _cache[15] || (_cache[15] = _createElementVNode("h3", { class: "mb-3" }, "全屏海报墙 — 插件设置", -1)),
        _createVNode(_component_v_switch, {
          modelValue: local.enabled,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((local.enabled) = $event)),
          label: "启用插件",
          color: "primary",
          "hide-details": "",
          class: "mb-3"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_alert, {
          type: "info",
          variant: "tonal",
          class: "mb-4",
          density: "compact"
        }, {
          default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
            _createTextVNode(" 启用后，插件详情页（Page）会提供全屏海报墙入口。 ", -1)
          ]))]),
          _: 1
        }),
        _createElementVNode("div", _hoisted_2, [
          _createElementVNode("div", _hoisted_3, [
            _cache[12] || (_cache[12] = _createElementVNode("span", { class: "text-subtitle-2" }, "推荐数据源（下拉勾选，不占页面）", -1)),
            (sourcesLoading.value)
              ? (_openBlock(), _createBlock(_component_v_progress_circular, {
                  key: 0,
                  indeterminate: "",
                  size: "16",
                  width: "2",
                  class: "ml-2"
                }))
              : _createCommentVNode("", true)
          ]),
          (sourcesError.value)
            ? (_openBlock(), _createBlock(_component_v_alert, {
                key: 0,
                type: "warning",
                variant: "tonal",
                density: "compact",
                class: "mb-2"
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(sourcesError.value), 1)
                ]),
                _: 1
              }))
            : _createCommentVNode("", true),
          _createVNode(_component_v_select, {
            modelValue: selectedPaths.value,
            "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((selectedPaths).value = $event)),
            items: sourceList.value,
            "item-title": "name",
            "item-value": "api_path",
            label: "勾选数据源（可多选）",
            multiple: "",
            chips: "",
            "closable-chips": "",
            density: "comfortable",
            "menu-props": { maxHeight: 400 }
          }, {
            item: _withCtx(({ props: itemProps, item }) => [
              _createVNode(_component_v_list_item, _normalizeProps(_guardReactiveProps(itemProps)), {
                append: _withCtx(() => [
                  _createVNode(_component_v_chip, {
                    size: "x-small",
                    variant: "tonal",
                    class: "ml-1",
                    color: item.raw.builtin ? undefined : 'purple'
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(item.raw.builtin ? '' : '第三方·') + _toDisplayString(natLabel(item.raw.nat)), 1)
                    ]),
                    _: 2
                  }, 1032, ["color"])
                ]),
                _: 2
              }, 1040)
            ]),
            _: 1
          }, 8, ["modelValue", "items"]),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(enabledMixedSources.value, (s) => {
            return (_openBlock(), _createElementBlock("div", {
              key: s.api_path,
              class: "d-flex align-center mixed-row"
            }, [
              _createElementVNode("span", _hoisted_4, _toDisplayString(s.name) + "（混合源）", 1),
              _createVNode(_component_v_spacer),
              _createVNode(_component_v_checkbox, {
                label: "电影",
                "model-value": hasType(s.api_path, 'movie'),
                "hide-details": "",
                density: "compact",
                class: "type-check",
                "onUpdate:modelValue": v => toggleType(s.api_path, 'movie', v)
              }, null, 8, ["model-value", "onUpdate:modelValue"]),
              _createVNode(_component_v_checkbox, {
                label: "电视剧",
                "model-value": hasType(s.api_path, 'tv'),
                "hide-details": "",
                density: "compact",
                class: "type-check",
                "onUpdate:modelValue": v => toggleType(s.api_path, 'tv', v)
              }, null, 8, ["model-value", "onUpdate:modelValue"])
            ]))
          }), 128)),
          (!sourcesLoading.value && !sourceList.value.length && !sourcesError.value)
            ? (_openBlock(), _createElementBlock("div", _hoisted_5, " 未发现可用数据源 "))
            : _createCommentVNode("", true)
        ]),
        _createVNode(_component_v_select, {
          modelValue: local.effect,
          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((local.effect) = $event)),
          items: effectOptions,
          label: "播放方式",
          density: "comfortable",
          class: "mb-3"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_select, {
          modelValue: local.image_type,
          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((local.image_type) = $event)),
          items: imageTypeOptions,
          label: "图片来源",
          density: "comfortable",
          class: "mb-3"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_select, {
          modelValue: local.poster_count,
          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((local.poster_count) = $event)),
          modelModifiers: { number: true },
          items: posterCountOptions,
          label: "海报数量（每次拉取）",
          density: "comfortable",
          class: "mb-3"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_text_field, {
          modelValue: local.interval,
          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((local.interval) = $event)),
          modelModifiers: { number: true },
          label: "切换间隔（秒）",
          type: "number",
          min: 3,
          max: 30,
          density: "comfortable",
          class: "mb-3"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_text_field, {
          modelValue: local.refresh_minutes,
          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((local.refresh_minutes) = $event)),
          modelModifiers: { number: true },
          label: "数据刷新间隔（分钟）",
          type: "number",
          min: 5,
          max: 1440,
          density: "comfortable",
          class: "mb-3"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_switch, {
          modelValue: local.autoplay,
          "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((local.autoplay) = $event)),
          label: "进入页面后自动播放",
          color: "primary",
          "hide-details": "",
          density: "comfortable",
          class: "mb-3"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_switch, {
          modelValue: local.show_dashboard,
          "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((local.show_dashboard) = $event)),
          label: "在首页仪表板显示此小窗格",
          color: "primary",
          "hide-details": "",
          density: "comfortable",
          class: "mb-3"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_switch, {
          modelValue: local.shuffle,
          "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((local.shuffle) = $event)),
          label: "随机乱序（每次全屏顺序不同）",
          color: "primary",
          "hide-details": "",
          density: "comfortable",
          class: "mb-3"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_switch, {
          modelValue: local.hide_text,
          "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((local.hide_text) = $event)),
          label: "隐藏文字（只看海报不看标题/年份）",
          color: "primary",
          "hide-details": "",
          density: "comfortable",
          class: "mb-4"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_divider, { class: "my-3" }),
        _createElementVNode("div", _hoisted_6, [
          _createVNode(_component_v_btn, {
            variant: "text",
            onClick: onReset
          }, {
            default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
              _createTextVNode("重置默认", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_v_btn, {
            color: "primary",
            onClick: onSave
          }, {
            default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
              _createTextVNode("保存", -1)
            ]))]),
            _: 1
          })
        ])
      ]),
      _: 1
    }),
    _createVNode(_component_v_card, {
      variant: "outlined",
      class: "pa-4"
    }, {
      default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
        _createElementVNode("h4", { class: "mb-2" }, "使用说明", -1),
        _createElementVNode("ol", { style: {"line-height":"1.8","padding-left":"20px"} }, [
          _createElementVNode("li", null, "在此开启插件并选择推荐数据源 + 播放方式。"),
          _createElementVNode("li", null, "回到插件详情页，点击「进入全屏播放」按钮（或按 F 键）。"),
          _createElementVNode("li", null, "全屏状态下按 Esc 或点击右上角 ✕ 退出。")
        ], -1)
      ]))]),
      _: 1
    })
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-f6b45f02"]]);

export { Config as default };
