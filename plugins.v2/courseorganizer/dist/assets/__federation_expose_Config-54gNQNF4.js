import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,createTextVNode:_createTextVNode,withModifiers:_withModifiers,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const _hoisted_1 = { class: "course-config__actions" };

const {nextTick,onMounted,ref,watch} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'CourseOrganizer' },
  initialConfig: { type: Object, default: () => ({}) },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;

const localConfig = ref({});
const saving = ref(false);
const monitoringBlocked = ref(true);
const monitoringMessage = ref('正在自动检测 MoviePilot 自动监控配置…');
const monitoringMessageType = ref('info');

const configDefaults = {
  auto_organize: false,
};

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function normalizeInitialConfig(value) {
  const config = clone(value);
  const rawAutoOrganize = Object.prototype.hasOwnProperty.call(config, 'auto_organize')
    ? config.auto_organize
    : String(config.naming_mode || '').trim().toLowerCase() === 'apply';
  const autoOrganize = typeof rawAutoOrganize === 'string'
    ? ['1', 'true', 'yes', 'on'].includes(rawAutoOrganize.trim().toLowerCase())
    : Boolean(rawAutoOrganize);

  return { ...configDefaults, ...config, auto_organize: autoOrganize }
}

watch(
  () => props.initialConfig,
  value => { localConfig.value = normalizeInitialConfig(value); },
  { immediate: true, deep: true },
);

function saveConfig() {
  if (saving.value) return
  if (localConfig.value.auto_organize && monitoringBlocked.value) return
  saving.value = true;
  try {
    emit('save', clone(localConfig.value));
  } finally {
    saving.value = false;
  }
}

async function loadMonitoringStatus() {
  if (typeof props.api?.get !== 'function') {
    monitoringMessage.value = '无法读取 MoviePilot 自动监控配置，自动整理暂不可开启。';
    monitoringMessageType.value = 'error';
    return
  }
  try {
    const response = await props.api.get(`plugin/${props.pluginId || 'CourseOrganizer'}/review`);
    const body = response?.data ?? response;
    const data = body?.data ?? body ?? {};
    if (data.monitoring_enabled) {
      const rules = Array.isArray(data.monitoring_rules) ? data.monitoring_rules.filter(Boolean) : [];
      const ruleText = rules.length ? `（${rules.join('、')}）` : '';
      const sourceText = data.incoming_path ? `来源目录 ${data.incoming_path}` : '当前来源目录';
      monitoringBlocked.value = true;
      monitoringMessageType.value = 'error';
      monitoringMessage.value = `已自动检测到 ${sourceText} 与 MoviePilot 自动监控规则${ruleText}重叠；自动整理已禁止，仅保留安全预览。`;
      localConfig.value = { ...localConfig.value, auto_organize: false };
      return
    }
    monitoringBlocked.value = false;
    monitoringMessageType.value = 'success';
    monitoringMessage.value = '已自动检测 MoviePilot 自动监控配置，当前来源目录未发现监控冲突。';
  } catch (error) {
    monitoringBlocked.value = true;
    monitoringMessageType.value = 'error';
    monitoringMessage.value = error?.message
      ? `无法读取 MoviePilot 自动监控配置：${error.message}`
      : '无法读取 MoviePilot 自动监控配置，自动整理暂不可开启。';
    localConfig.value = { ...localConfig.value, auto_organize: false };
  }
}

async function openMoviePilotSettings() {
  emit('close');
  await nextTick();
  window.location.assign('#/setting');
}

onMounted(loadMonitoringStatus);

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VForm = _resolveComponent("VForm");

  return (_openBlock(), _createBlock(_component_VForm, {
    class: "course-config",
    "aria-label": "整理识别设置",
    onSubmit: _withModifiers(saveConfig, ["prevent"])
  }, {
    default: _withCtx(() => [
      _createVNode(_component_VToolbar, {
        density: "comfortable",
        color: "transparent",
        class: "course-config__toolbar"
      }, {
        default: _withCtx(() => [
          _cache[3] || (_cache[3] = _createElementVNode("div", { class: "text-h6" }, "整理识别设置", -1)),
          _createVNode(_component_VSpacer),
          _createVNode(_component_VBtn, {
            icon: "mdi-close",
            variant: "text",
            "aria-label": "关闭设置",
            onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VDivider),
      _createVNode(_component_VAlert, {
        type: "info",
        variant: "tonal",
        class: "ma-3",
        role: "note"
      }, {
        append: _withCtx(() => [
          _createVNode(_component_VBtn, {
            variant: "tonal",
            color: "primary",
            "prepend-icon": "mdi-folder-cog",
            onClick: _withModifiers(openMoviePilotSettings, ["stop"])
          }, {
            default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
              _createTextVNode(" 打开目录设置 ", -1)
            ]))]),
            _: 1
          })
        ]),
        default: _withCtx(() => [
          _cache[5] || (_cache[5] = _createTextVNode(" 目录、媒体类型、分类规则、整理方式、重命名、刮削和智能助手均直接读取 MoviePilot 系统设置，不在插件内重复配置。 ", -1))
        ]),
        _: 1
      }),
      _createVNode(_component_VSwitch, {
        modelValue: localConfig.value.auto_organize,
        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((localConfig.value.auto_organize) = $event)),
        class: "mx-4 mb-2",
        label: "自动整理符合条件的项目",
        "aria-label": "自动整理符合条件的项目",
        hint: "开启后，仅自动整理识别结果可靠且目标媒体库明确的项目；不确定项目继续保留在待确认列表",
        "persistent-hint": "",
        color: "primary",
        disabled: monitoringBlocked.value
      }, null, 8, ["modelValue", "disabled"]),
      _createVNode(_component_VAlert, {
        type: monitoringMessageType.value,
        variant: "tonal",
        density: "compact",
        class: "mx-3 mb-3"
      }, {
        default: _withCtx(() => [
          _createTextVNode(_toDisplayString(monitoringMessage.value), 1)
        ]),
        _: 1
      }, 8, ["type"]),
      _createElementVNode("div", _hoisted_1, [
        _createVNode(_component_VBtn, {
          variant: "text",
          "min-width": "88",
          onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
        }, {
          default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
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
          default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-3d84b7a8"]]);

export { Config as default };
