import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { P as PhotosSlideshow, a as ShiftingTiles, R as RingGallery, D as DepthTunnel, S as SlidingPanels, F as Floating, V as VintagePrints, L as LightDance } from './DepthTunnel-Dx7GfZGR.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,Fragment:_Fragment,resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,createBlock:_createBlock,renderList:_renderList,normalizeClass:_normalizeClass,resolveDynamicComponent:_resolveDynamicComponent,Teleport:_Teleport} = await importShared('vue');


const _hoisted_1 = { class: "fspw-root" };
const _hoisted_2 = {
  key: 0,
  class: "fspw-header"
};
const _hoisted_3 = { class: "fspw-title" };
const _hoisted_4 = { class: "fspw-meta" };
const _hoisted_5 = {
  key: 0,
  class: "fspw-waiting"
};
const _hoisted_6 = { class: "fspw-header-actions" };
const _hoisted_7 = {
  key: 2,
  class: "fspw-body"
};
const _hoisted_8 = { class: "fspw-effects" };
const _hoisted_9 = { class: "fspw-effect-icon" };
const _hoisted_10 = { class: "fspw-effect-name" };
const _hoisted_11 = { class: "fspw-effect-desc" };
const _hoisted_12 = {
  key: 0,
  class: "fspw-effect-check"
};
const _hoisted_13 = { class: "fspw-summary" };
const _hoisted_14 = { class: "fspw-summary-row" };
const _hoisted_15 = { class: "v" };
const _hoisted_16 = { class: "fspw-summary-row" };
const _hoisted_17 = { class: "v" };
const _hoisted_18 = { class: "fspw-summary-row" };
const _hoisted_19 = { class: "v" };
const _hoisted_20 = { class: "fspw-summary-row" };
const _hoisted_21 = { class: "v" };
const _hoisted_22 = { class: "fspw-summary-row" };
const _hoisted_23 = { class: "v" };
const _hoisted_24 = { class: "fspw-hint" };
const _hoisted_25 = { class: "fspw-lan-row" };
const _hoisted_26 = { class: "fspw-lan-url" };

const {ref,computed,onMounted,onBeforeUnmount,nextTick} = await importShared('vue');

const API_BASE = 'plugin/FullScreenPosterWall';
const TMDB_DOMAIN = 'https://image.tmdb.org/t/p/original';

const _sfc_main = {
  __name: 'Page',
  emits: ['switch'],
  setup(__props, { emit: __emit }) {

/*
 * 全屏海报墙 — Page 详情组件（Vue 联邦 Page）。
 *
 * 设计要点（针对用户反馈的"设置不生效"问题）：
 *
 * 1) **stage key 包含全部相关字段** —— effect / interval / image_type /
 *    hide_text / shuffle 任一变化都会触发 Vue 卸载旧 effect 组件并
 *    重建新组件，确保子组件 onMounted 重新读 props.interval 启动 timer。
 *
 * 2) **shuffledItems 在父组件计算**：如果 config.shuffle=true，
 *    进入全屏时把 items 数组复制后用 Fisher-Yates 洗牌。这样子组件
 *    拿到的就是已经乱序的列表，不会出现"显示时按 trending 顺序，
 *    但 Page 概要说 shuffle=true"的语义不一致。
 *
 * 3) **shuffle 用 useMemo（computed）**：每次 playing 进入时重新洗牌，
 *    退出全屏再次进入时又是新顺序。
 *
 * 4) **config 三秒轮询**：见下方 loadConfig + setInterval polling，
 *    保证 Page 概要始终反映最新的 Config 保存结果。
 */
const emit = __emit;  // 通知宿主切到 Config 弹窗

function getApi() {
  return (typeof window !== 'undefined' ? window.MoviePilotAPI : null)
}

// ─── 状态 ─────────────────────────────────────────────────
const config = ref({
  enabled: false,
  sources: ['trending', 'tmdb_movies', 'tmdb_tvs'],
  effect: 'photos',
  image_type: 'backdrop',
  interval: 8,
  refresh_minutes: 60,
  autoplay: true,
  show_dashboard: true,
  shuffle: false,
  hide_text: false,
  tmdb_image_domain: TMDB_DOMAIN,
});
const items = ref([]);
const playing = ref(false);
const loaded = ref(false);
const loadError = ref('');
const stageRef = ref(null);
const copyText = ref('复制');

// 免登录全屏页地址：直接用当前浏览器访问 MoviePilot 的 host（随环境自动更新，
// localhost / 局域网 IP / 域名都适用；不再依赖后端 socket 探测——容器内探到的是网桥 IP）
const lanWallUrl = computed(() => {
  if (typeof window === 'undefined') return ''
  return `${window.location.protocol}//${window.location.host}/api/v1/plugin/FullScreenPosterWall/lan-wall`
});

let configPollTimer;

// ─── 动效元数据 ───────────────────────────────────────────
const effects = [
  { key: 'photos',       name: '照片',         icon: '📷', desc: '幻灯片 + Ken Burns', comp: PhotosSlideshow },
  { key: 'shiftingtiles', name: '流动拼贴', icon: '🧩', desc: '模块收缩补位', comp: ShiftingTiles },
  { key: 'ring3d',       name: '环形画廊',       icon: '🎡', desc: '3D 环廊聚焦',  comp: RingGallery },
  { key: 'depthtunnel',  name: '纵深穿梭',       icon: '🚀', desc: '照片飞来掠影', comp: DepthTunnel },
  { key: 'slidingpanels',name: '滑动面板',      icon: '📑', desc: '多列反向滑动',       comp: SlidingPanels },
  { key: 'floating',     name: '浮动',         icon: '🪟', desc: '多图漂浮碰撞',        comp: Floating },
  { key: 'vintage',      name: '怀旧冲印',     icon: '📜', desc: '复古胶片 + 噪点',     comp: VintagePrints },
  { key: 'lightdance',   name: '光舞',         icon: '✨', desc: '光束 + 浮动光球',     comp: LightDance },
];
const currentEffectComp = computed(() => {
  const e = effects.find(x => x.key === config.value.effect);
  return e ? e.comp : PhotosSlideshow
});
const effectName = computed(() => {
  const e = effects.find(x => x.key === config.value.effect);
  return e ? e.name : '照片'
});
const sourceChips = computed(() => {
  const map = {
    trending: '流行趋势',
    tmdb_movies: 'TMDB热门电影',
    tmdb_tvs: 'TMDB热门电视剧',
  };
  const list = config.value.sources || [];
  return list
    .filter(s => map[s])
    .map(s => ({ key: s, name: map[s] }))
});
const imageTypeName = computed(() => {
  const m = { poster: '海报 (poster)', backdrop: '背景大图 (backdrop)', both: '海报 + 背景' };
  return m[config.value.image_type] || config.value.image_type
});

// ─── stage key：任一字段变化都重新挂载 stage ─────────────
const stageKey = computed(() => [
  config.value.effect,
  config.value.interval,
  config.value.image_type,
  config.value.hide_text ? '1' : '0',
  config.value.shuffle ? '1' : '0',
].join('-'));

// ─── 乱序（进入全屏时洗牌） ────────────────────────────────
function shuffleArray(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a
}
const shuffledItems = computed(() => {
  if (!config.value.shuffle) return items.value
  return shuffleArray(items.value)
});

// ─── 数据加载 ─────────────────────────────────────────────
async function loadConfig(silent = false) {
  const api = getApi();
  if (!api?.get) return
  try {
    const raw = await api.get(`${API_BASE}/config`);
    // MoviePilot 主框架 axios 的 response interceptor 已经把响应解包：
    //   api.get() 返回的就是后端 {enabled, effect, interval, ...} 字段本体
    //   而不再是 axios 包装的 {data: {...}}
    const newCfg = raw?.data ?? raw;  // 兼容两种格式
    if (newCfg && typeof newCfg === 'object') {
      const merged = { ...config.value, ...newCfg };
      const changed = JSON.stringify(config.value) !== JSON.stringify(merged);
      if (changed) config.value = merged;
    }
  } catch (e) {
    if (!silent) console.warn('[FullScreenPosterWall] loadConfig failed', e);
  }
}

async function copyLanUrl() {
  const url = lanWallUrl.value;
  if (!url) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
    } else {
      const ta = document.createElement('textarea');
      ta.value = url;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    copyText.value = '已复制 ✓';
    setTimeout(() => { copyText.value = '复制'; }, 2000);
  } catch (e) {
    console.error('[FullScreenPosterWall] copy failed', e);
    copyText.value = '复制失败';
  }
}

function openLanUrl() {
  if (lanWallUrl.value) window.open(lanWallUrl.value, '_blank', 'noopener');
}

async function reloadItems(forceShuffle = false) {
  loadError.value = '';
  const api = getApi();
  if (!api?.get) return
  try {
    const url = (forceShuffle || config.value.shuffle)
      ? `${API_BASE}/recommend?shuffle=true`
      : `${API_BASE}/recommend`;
    const raw = await api.get(url);
    // raw 已经是后端字段本体 {success, count, data: [...]} 或直接 [...]
    let list = [];
    if (Array.isArray(raw)) list = raw;
    else if (Array.isArray(raw?.data)) list = raw.data;
    items.value = list;
    loaded.value = true;
  } catch (e) {
    loadError.value = String(e?.message || e);
    loaded.value = true;
  }
}

// ─── 用户交互 ─────────────────────────────────────────────
function openSettings() {
  emit('switch');  // 通知宿主切到 Config 弹窗（PluginConfigDialog 监听 @switch）
}

async function enterFullscreen() {
  if (!loaded.value) await reloadItems(true);
  playing.value = true;
  await nextTick();
  // 请求浏览器原生屏幕全屏（用户点击手势内调用，浏览器允许）
  const el = stageRef.value;
  if (el) {
    try {
      if (el.requestFullscreen) await el.requestFullscreen();
      else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    } catch (e) {
      // 浏览器拒绝时保留网页内全屏兜底
      console.warn('[FullScreenPosterWall] requestFullscreen denied, stay in-page fullscreen', e);
    }
  }
}

function exitFullscreen() {
  playing.value = false;
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
  }
}

// 用户按 Esc 退出屏幕全屏时，同步退出应用内播放状态
function onFsChange() {
  if (!document.fullscreenElement && playing.value) {
    playing.value = false;
  }
}

// 全局键盘：F 进 / Esc 出
function onKey(e) {
  if (playing.value && e.key === 'Escape') {
    exitFullscreen();
  } else if (!playing.value && (e.key === 'f' || e.key === 'F') && loaded.value) {
    enterFullscreen();
  }
}

// ─── 生命周期 ─────────────────────────────────────────────
onMounted(async () => {
  await loadConfig();
  await reloadItems(true);
  window.addEventListener('keydown', onKey);
  document.addEventListener('fullscreenchange', onFsChange);
  // 3 秒轮询同步 config：用户在 Config 保存后 Page 概要会自动更新
  configPollTimer = window.setInterval(() => {
    loadConfig(true);
  }, 3000);
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey);
  document.removeEventListener('fullscreenchange', onFsChange);
  if (configPollTimer) clearInterval(configPollTimer);
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
});

return (_ctx, _cache) => {
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_chip = _resolveComponent("v-chip");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (!playing.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, [
          _createElementVNode("div", _hoisted_3, [
            _cache[2] || (_cache[2] = _createElementVNode("div", { class: "fspw-icon" }, "🎬", -1)),
            _createElementVNode("div", null, [
              _cache[1] || (_cache[1] = _createElementVNode("h2", { class: "ma-0" }, "全屏海报墙", -1)),
              _createElementVNode("div", _hoisted_4, [
                (!items.value.length)
                  ? (_openBlock(), _createElementBlock("span", _hoisted_5, "请等候拉取图片…"))
                  : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                      _createTextVNode(_toDisplayString(items.value.length) + " 张海报已就绪 ·", 1)
                    ], 64)),
                _createElementVNode("strong", null, _toDisplayString(effectName.value), 1),
                _createTextVNode(" · " + _toDisplayString(config.value.interval) + " 秒切换 ", 1)
              ])
            ])
          ]),
          _createElementVNode("div", _hoisted_6, [
            _createVNode(_component_v_btn, {
              icon: "mdi-cog-outline",
              variant: "text",
              size: "small",
              onClick: openSettings,
              title: "插件设置"
            }),
            _createVNode(_component_v_btn, {
              color: "primary",
              variant: "tonal",
              "prepend-icon": "mdi-play-circle-outline",
              onClick: enterFullscreen,
              disabled: !loaded.value,
              class: "ml-2"
            }, {
              default: _withCtx(() => [...(_cache[3] || (_cache[3] = [
                _createTextVNode(" 进入全屏播放 ", -1)
              ]))]),
              _: 1
            }, 8, ["disabled"])
          ])
        ]))
      : _createCommentVNode("", true),
    (loadError.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 1,
          type: "warning",
          density: "compact",
          variant: "tonal",
          class: "my-3"
        }, {
          default: _withCtx(() => [
            _createTextVNode(" 数据加载失败：" + _toDisplayString(loadError.value) + " ", 1),
            _createVNode(_component_v_btn, {
              size: "small",
              variant: "text",
              onClick: _cache[0] || (_cache[0] = $event => (reloadItems(true))),
              class: "ml-2"
            }, {
              default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
                _createTextVNode("重试", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (!playing.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_7, [
          _cache[16] || (_cache[16] = _createElementVNode("div", { class: "fspw-section-title" }, [
            _createTextVNode(" 播放效果 "),
            _createElementVNode("span", { class: "fspw-section-hint" }, "当前生效的效果由「插件设置」决定（彩色=选中，灰色=未选中）。")
          ], -1)),
          _createElementVNode("div", _hoisted_8, [
            (_openBlock(), _createElementBlock(_Fragment, null, _renderList(effects, (e) => {
              return _createElementVNode("div", {
                key: e.key,
                class: _normalizeClass(["fspw-effect", { 'is-active': config.value.effect === e.key, 'is-inactive': config.value.effect !== e.key }])
              }, [
                _createElementVNode("div", _hoisted_9, _toDisplayString(e.icon), 1),
                _createElementVNode("div", _hoisted_10, _toDisplayString(e.name), 1),
                _createElementVNode("div", _hoisted_11, _toDisplayString(e.desc), 1),
                (config.value.effect === e.key)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_12, "✓"))
                  : _createCommentVNode("", true)
              ], 2)
            }), 64))
          ]),
          _cache[17] || (_cache[17] = _createElementVNode("div", { class: "fspw-section-title mt-5" }, "当前设置", -1)),
          _createElementVNode("div", _hoisted_13, [
            _createElementVNode("div", _hoisted_14, [
              _cache[5] || (_cache[5] = _createElementVNode("span", { class: "k" }, "推荐数据源", -1)),
              _createElementVNode("span", _hoisted_15, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(sourceChips.value, (s) => {
                  return (_openBlock(), _createBlock(_component_v_chip, {
                    key: s.key,
                    size: "x-small",
                    color: "primary",
                    variant: "tonal",
                    class: "mr-1"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(s.name), 1)
                    ]),
                    _: 2
                  }, 1024))
                }), 128))
              ])
            ]),
            _createElementVNode("div", _hoisted_16, [
              _cache[6] || (_cache[6] = _createElementVNode("span", { class: "k" }, "图片来源", -1)),
              _createElementVNode("span", _hoisted_17, _toDisplayString(imageTypeName.value), 1)
            ]),
            _createElementVNode("div", _hoisted_18, [
              _cache[7] || (_cache[7] = _createElementVNode("span", { class: "k" }, "切换间隔", -1)),
              _createElementVNode("span", _hoisted_19, _toDisplayString(config.value.interval) + " 秒切换", 1)
            ]),
            _createElementVNode("div", _hoisted_20, [
              _cache[8] || (_cache[8] = _createElementVNode("span", { class: "k" }, "随机乱序", -1)),
              _createElementVNode("span", _hoisted_21, _toDisplayString(config.value.shuffle ? '开' : '关'), 1)
            ]),
            _createElementVNode("div", _hoisted_22, [
              _cache[9] || (_cache[9] = _createElementVNode("span", { class: "k" }, "隐藏文字", -1)),
              _createElementVNode("span", _hoisted_23, _toDisplayString(config.value.hide_text ? '开' : '关'), 1)
            ])
          ]),
          _createElementVNode("div", _hoisted_24, [
            _cache[11] || (_cache[11] = _createTextVNode(" 💡 修改以上效果/间隔/数据源等：", -1)),
            _cache[12] || (_cache[12] = _createElementVNode("strong", null, "右上齿轮按钮", -1)),
            _cache[13] || (_cache[13] = _createTextVNode(" 打开插件设置保存。 ", -1)),
            _cache[14] || (_cache[14] = _createElementVNode("br", null, null, -1)),
            _cache[15] || (_cache[15] = _createTextVNode(" 💡 在同一 Wi-Fi 内的手机/电脑浏览器直接打开（无需登录）： ", -1)),
            _createElementVNode("span", _hoisted_25, [
              _createElementVNode("code", _hoisted_26, _toDisplayString(lanWallUrl.value), 1),
              _createVNode(_component_v_btn, {
                size: "x-small",
                variant: "tonal",
                color: "primary",
                class: "fspw-lan-btn",
                onClick: copyLanUrl
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(copyText.value), 1)
                ]),
                _: 1
              }),
              _createVNode(_component_v_btn, {
                size: "x-small",
                variant: "tonal",
                color: "primary",
                class: "fspw-lan-btn",
                "prepend-icon": "mdi-open-in-new",
                onClick: openLanUrl
              }, {
                default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                  _createTextVNode("打开", -1)
                ]))]),
                _: 1
              })
            ])
          ])
        ]))
      : _createCommentVNode("", true),
    (_openBlock(), _createBlock(_Teleport, { to: "body" }, [
      (playing.value)
        ? (_openBlock(), _createElementBlock("div", {
            key: `stage-${stageKey.value}`,
            ref_key: "stageRef",
            ref: stageRef,
            class: _normalizeClass(["fspw-stage", { 'fspw-no-text': config.value.hide_text }])
          }, [
            (_openBlock(), _createBlock(_resolveDynamicComponent(currentEffectComp.value), {
              items: shuffledItems.value,
              interval: config.value.interval,
              "image-type": config.value.image_type,
              autoplay: true,
              onExit: exitFullscreen
            }, null, 40, ["items", "interval", "image-type"])),
            _createElementVNode("button", {
              class: "fspw-exit",
              onClick: exitFullscreen,
              title: "退出 (Esc)"
            }, "✕")
          ], 2))
        : _createCommentVNode("", true)
    ]))
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-1c9a421d"]]);

export { Page as default };
