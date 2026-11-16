import { d as _export_sfc, e as __mf_2, f as __mf_8, g as __mf_22, c as __mf_17, h as __mf_18, i as __mf_21, a as __mf_19, j as __mf_11, k as __mf_12, l as __mf_6, m as __mf_3, n as formatBytes, o as __mf_14, p as __mf_7, q as __mf_20, t as taskStateMeta, r as __mf_13, s as __mf_10, b as __mf_9, u as unwrapResponse } from './_plugin-vue_export-helper-C960cP-z.js';

const _hoisted_1 = { class: "brushflow-dashboard" };
const _hoisted_2 = { class: "brushflow-dashboard__metrics" };
const _hoisted_3 = { class: "brushflow-dashboard__tasks" };
const _hoisted_4 = {
  key: 0,
  class: "brushflow-dashboard__empty"
};


const _sfc_main = {
  __name: 'Dashboard',
  props: {
  api: { type: Object, default: () => ({}) },
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: true },
},
  setup(__props) {

const props = __props;

const loading = __mf_2(false);
const status = __mf_2({ summary: {}, tasks: [] });
let refreshTimer;

const runningTasks = __mf_8(() => (status.value.tasks || []).filter(item => item.enabled).slice(0, 3));

// 从插件接口加载仪表板聚合统计。
async function loadStatus() {
  if (!props.allowRefresh && status.value.tasks?.length) return
  loading.value = true;
  try {
    status.value = unwrapResponse(await props.api.get('plugin/BrushFlow/status')) || status.value;
  } finally {
    loading.value = false;
  }
}

__mf_22(
  () => props.allowRefresh,
  enabled => {
    if (enabled) loadStatus();
  },
);

__mf_17(() => {
  loadStatus();
  refreshTimer = window.setInterval(loadStatus, 30000);
});

__mf_18(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});

return (_ctx, _cache) => {
  const _component_VDivider = __mf_21("VDivider");
  const _component_VIcon = __mf_21("VIcon");
  const _component_VProgressLinear = __mf_21("VProgressLinear");

  return (__mf_19(), __mf_11("div", _hoisted_1, [
    __mf_12("div", _hoisted_2, [
      __mf_12("div", null, [
        _cache[0] || (_cache[0] = __mf_12("span", null, "运行任务", -1)),
        __mf_12("strong", null, __mf_6(status.value.summary.running_count ?? status.value.summary.enabled_count ?? 0) + " / " + __mf_6(status.value.summary.task_count || 0), 1)
      ]),
      __mf_12("div", null, [
        _cache[1] || (_cache[1] = __mf_12("span", null, "活跃种子", -1)),
        __mf_12("strong", null, __mf_6(status.value.summary.active_count || 0), 1)
      ]),
      __mf_12("div", null, [
        _cache[2] || (_cache[2] = __mf_12("span", null, "累计上传", -1)),
        __mf_12("strong", null, __mf_6(__mf_3(formatBytes)(status.value.summary.uploaded)), 1)
      ]),
      __mf_12("div", null, [
        _cache[3] || (_cache[3] = __mf_12("span", null, "当前做种", -1)),
        __mf_12("strong", null, __mf_6(__mf_3(formatBytes)(status.value.summary.seeding_size)), 1)
      ])
    ]),
    __mf_14(_component_VDivider),
    __mf_12("div", _hoisted_3, [
      (__mf_19(true), __mf_11(__mf_7, null, __mf_20(runningTasks.value, (task) => {
        return (__mf_19(), __mf_11("div", {
          key: task.id
        }, [
          __mf_14(_component_VIcon, {
            icon: __mf_3(taskStateMeta)(task.state).icon,
            color: __mf_3(taskStateMeta)(task.state).color,
            size: "18"
          }, null, 8, ["icon", "color"]),
          __mf_12("div", null, [
            __mf_12("strong", null, __mf_6(task.name), 1),
            __mf_12("span", null, __mf_6(task.site_name) + " · " + __mf_6(task.statistic.active || 0) + " 个种子", 1)
          ]),
          __mf_12("span", null, __mf_6(__mf_3(formatBytes)(task.statistic.uploaded)), 1)
        ]))
      }), 128)),
      (!runningTasks.value.length)
        ? (__mf_19(), __mf_11("div", _hoisted_4, [
            __mf_14(_component_VIcon, { icon: "mdi-sync-off" }),
            _cache[4] || (_cache[4] = __mf_13(" 暂无启用的刷流任务 ", -1))
          ]))
        : __mf_10("", true)
    ]),
    (loading.value)
      ? (__mf_19(), __mf_9(_component_VProgressLinear, {
          key: 0,
          indeterminate: "",
          color: "primary",
          height: "2"
        }))
      : __mf_10("", true)
  ]))
}
}

};
const Dashboard = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-ae31c45e"]]);

export { Dashboard as default };
