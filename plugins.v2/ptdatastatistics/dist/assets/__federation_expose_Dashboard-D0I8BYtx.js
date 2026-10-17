import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc, f as formatBytes, a as _sfc_main$1, u as unwrapResponse } from './SiteAvatar-DCSfizL-.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,normalizeStyle:_normalizeStyle,unref:_unref,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,withCtx:_withCtx} = await importShared('vue');


const _hoisted_1 = { class: "pt-dashboard__heading" };
const _hoisted_2 = { class: "pt-dashboard__title" };
const _hoisted_3 = {
  key: 1,
  class: "pt-dashboard__body"
};
const _hoisted_4 = { class: "donut-wrap" };
const _hoisted_5 = { class: "donut__hole" };
const _hoisted_6 = { class: "pt-dashboard__details" };
const _hoisted_7 = { class: "pt-dashboard__totals" };
const _hoisted_8 = { class: "total-pill" };
const _hoisted_9 = { class: "total-pill total-pill--upload" };
const _hoisted_10 = { class: "total-pill total-pill--download" };
const _hoisted_11 = {
  class: "site-list",
  tabindex: "0",
  "aria-label": "今日站点流量列表"
};
const _hoisted_12 = { class: "site-row__identity" };
const _hoisted_13 = { class: "site-row__metric site-row__metric--upload" };
const _hoisted_14 = { class: "site-row__metric site-row__metric--download" };
const _hoisted_15 = { class: "site-row__share" };
const _hoisted_16 = {
  key: 2,
  class: "pt-dashboard__empty"
};

const {computed,onMounted,onUnmounted,ref,watch} = await importShared('vue');


const _sfc_main = {
  __name: 'Dashboard',
  props: {
  api: { type: Object, default: () => ({}) },
  config: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'PTDataStatistics' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
  allowRefresh: { type: Boolean, default: true },
},
  setup(__props) {

const props = __props;

const loading = ref(false);
const overview = ref({
  server_date: '',
  summary: {},
  today_sites: [],
});
let refreshTimer;

const pluginBase = computed(() => `plugin/${props.pluginId || 'PTDataStatistics'}`);
const sites = computed(() => overview.value.today_sites || []);
const dashboardColors = [
  '#52d000', '#29a8e8', '#f59e0b', '#8b5cf6',
  '#22d3ee', '#fb7185', '#60a5fa', '#a78bfa',
  '#2dd4bf', '#f97316', '#e879f9', '#38bdf8',
];

const donutBackground = computed(() => {
  if (!sites.value.length) return 'conic-gradient(rgba(var(--v-theme-on-surface), .1) 0 100%)'
  let offset = 0;
  const stops = sites.value.map((site, index) => {
    const start = offset;
    offset += Number(site.contribution || 0);
    return `${dashboardColors[index % dashboardColors.length]} ${start}% ${Math.min(offset, 100)}%`
  });
  if (offset < 100) stops.push(`rgba(var(--v-theme-on-surface), .1) ${offset}% 100%`);
  return `conic-gradient(${stops.join(', ')})`
});

async function loadOverview() {
  if (!props.allowRefresh && overview.value.server_date) return
  loading.value = true;
  try {
    const data = await props.api.get(`${pluginBase.value}/overview`, { feedback: 'silent' });
    overview.value = unwrapResponse(data) || overview.value;
  } finally {
    loading.value = false;
  }
}

watch(() => props.allowRefresh, enabled => enabled && loadOverview());

onMounted(() => {
  loadOverview();
  refreshTimer = window.setInterval(loadOverview, 60000);
});

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VCard = _resolveComponent("VCard");

  return (_openBlock(), _createBlock(_component_VCard, { class: "pt-dashboard dashboard-grid-fill" }, {
    default: _withCtx(() => [
      _createElementVNode("header", _hoisted_1, [
        _createElementVNode("div", _hoisted_2, [
          _createVNode(_component_VIcon, {
            class: "pt-dashboard__title-icon",
            icon: "mdi-finance",
            size: "24",
            color: "warning"
          }),
          _cache[0] || (_cache[0] = _createElementVNode("strong", null, "今日流量", -1))
        ]),
        _cache[1] || (_cache[1] = _createElementVNode("span", null, "今天 00:00 起", -1))
      ]),
      (loading.value)
        ? (_openBlock(), _createBlock(_component_VProgressLinear, {
            key: 0,
            indeterminate: "",
            color: "primary",
            height: "2"
          }))
        : _createCommentVNode("", true),
      (sites.value.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_3, [
            _createElementVNode("div", _hoisted_4, [
              _createElementVNode("div", {
                class: "donut",
                style: _normalizeStyle({ background: donutBackground.value })
              }, [
                _createElementVNode("div", _hoisted_5, [
                  _createElementVNode("strong", null, _toDisplayString(sites.value.length), 1),
                  _cache[2] || (_cache[2] = _createElementVNode("span", null, "个站点", -1))
                ])
              ], 4)
            ]),
            _createElementVNode("div", _hoisted_6, [
              _createElementVNode("div", _hoisted_7, [
                _createElementVNode("div", _hoisted_8, [
                  _createVNode(_component_VIcon, {
                    class: "total-pill__icon",
                    icon: "mdi-calendar-blank-outline",
                    size: "20"
                  }),
                  _cache[3] || (_cache[3] = _createElementVNode("span", null, "统计时间", -1)),
                  _createElementVNode("strong", null, _toDisplayString(overview.value.server_date || '暂无'), 1)
                ]),
                _createElementVNode("div", _hoisted_9, [
                  _createVNode(_component_VIcon, {
                    class: "total-pill__icon",
                    icon: "mdi-arrow-up",
                    size: "20"
                  }),
                  _cache[4] || (_cache[4] = _createElementVNode("span", null, "上传增量", -1)),
                  _createElementVNode("strong", null, _toDisplayString(_unref(formatBytes)(overview.value.summary.today_upload)), 1)
                ]),
                _createElementVNode("div", _hoisted_10, [
                  _createVNode(_component_VIcon, {
                    class: "total-pill__icon",
                    icon: "mdi-arrow-down",
                    size: "20"
                  }),
                  _cache[5] || (_cache[5] = _createElementVNode("span", null, "下载增量", -1)),
                  _createElementVNode("strong", null, _toDisplayString(_unref(formatBytes)(overview.value.summary.today_download)), 1)
                ])
              ]),
              _createElementVNode("div", _hoisted_11, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(sites.value, (site, index) => {
                  return (_openBlock(), _createElementBlock("div", {
                    key: site.site_id || site.site_name,
                    class: "site-row"
                  }, [
                    _createElementVNode("div", _hoisted_12, [
                      _createVNode(_sfc_main$1, {
                        api: __props.api,
                        site: site,
                        size: 30
                      }, null, 8, ["api", "site"]),
                      _createElementVNode("strong", null, _toDisplayString(site.site_name), 1)
                    ]),
                    _createElementVNode("div", _hoisted_13, [
                      _createVNode(_component_VIcon, {
                        icon: "mdi-arrow-up",
                        size: "16"
                      }),
                      _createElementVNode("span", null, _toDisplayString(_unref(formatBytes)(site.daily_upload)), 1)
                    ]),
                    _createElementVNode("div", _hoisted_14, [
                      _createVNode(_component_VIcon, {
                        icon: "mdi-arrow-down",
                        size: "16"
                      }),
                      _createElementVNode("span", null, _toDisplayString(_unref(formatBytes)(site.daily_download)), 1)
                    ]),
                    _createElementVNode("div", _hoisted_15, [
                      _createElementVNode("i", {
                        style: _normalizeStyle({ backgroundColor: dashboardColors[index % dashboardColors.length] })
                      }, null, 4),
                      _createElementVNode("span", null, _toDisplayString(Number(site.contribution || 0).toFixed(1)) + "%", 1)
                    ])
                  ]))
                }), 128))
              ])
            ])
          ]))
        : (_openBlock(), _createElementBlock("div", _hoisted_16, [
            _createVNode(_component_VIcon, {
              icon: "mdi-chart-donut-variant",
              size: "48",
              color: "secondary"
            }),
            _cache[6] || (_cache[6] = _createElementVNode("strong", null, "今日暂无站点流量", -1)),
            _cache[7] || (_cache[7] = _createElementVNode("span", null, "仅显示今日上传或下载大于零、且基线有效的站点", -1))
          ]))
    ]),
    _: 1
  }))
}
}

};
const Dashboard = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-666df621"]]);

export { Dashboard as default };
