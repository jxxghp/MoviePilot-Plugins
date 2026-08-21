import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,createTextVNode:_createTextVNode,withModifiers:_withModifiers,openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const _hoisted_1 = { class: "course-config__actions" };

const {nextTick,ref,watch} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;

const localConfig = ref({});
const saving = ref(false);

const recognitionDefaults = {
  naming_sources: 'themoviedb,douban',
  naming_auto_threshold: 90,
  naming_min_margin: 12,
  naming_uncertain_policy: 'local',
  naming_append_tmdb_id: false,
  naming_ai_review: false,
  naming_clear_cache_once: false,
};

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

watch(
  () => props.initialConfig,
  value => { localConfig.value = { ...recognitionDefaults, ...clone(value) }; },
  { immediate: true, deep: true },
);

function saveConfig() {
  if (saving.value) return
  saving.value = true;
  try {
    emit('save', clone(localConfig.value));
  } finally {
    saving.value = false;
  }
}

async function openMoviePilotSettings() {
  emit('close');
  await nextTick();
  window.location.assign('#/setting');
}

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VExpansionPanelText = _resolveComponent("VExpansionPanelText");
  const _component_VExpansionPanel = _resolveComponent("VExpansionPanel");
  const _component_VExpansionPanels = _resolveComponent("VExpansionPanels");
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
          _cache[8] || (_cache[8] = _createElementVNode("div", { class: "text-h6" }, "整理识别设置", -1)),
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
            default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
              _createTextVNode(" 打开目录设置 ", -1)
            ]))]),
            _: 1
          })
        ]),
        default: _withCtx(() => [
          _cache[10] || (_cache[10] = _createTextVNode(" 目录和整理规则沿用 MoviePilot 系统设置，本插件只保留识别选项。 ", -1))
        ]),
        _: 1
      }),
      _createVNode(_component_VExpansionPanels, {
        class: "mx-3 mb-3",
        variant: "accordion"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VExpansionPanel, {
            title: "高级识别设置",
            value: "recognition"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VExpansionPanelText, null, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: localConfig.value.naming_sources,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((localConfig.value.naming_sources) = $event)),
                    label: "识别来源（逗号分隔）",
                    "aria-label": "识别来源（逗号分隔）",
                    variant: "outlined"
                  }, null, 8, ["modelValue"]),
                  _createVNode(_component_VTextField, {
                    modelValue: localConfig.value.naming_auto_threshold,
                    "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((localConfig.value.naming_auto_threshold) = $event)),
                    modelModifiers: { number: true },
                    label: "自动采用阈值（80~100）",
                    "aria-label": "自动采用阈值（80~100）",
                    type: "number",
                    min: "80",
                    max: "100",
                    variant: "outlined"
                  }, null, 8, ["modelValue"]),
                  _createVNode(_component_VTextField, {
                    modelValue: localConfig.value.naming_min_margin,
                    "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((localConfig.value.naming_min_margin) = $event)),
                    modelModifiers: { number: true },
                    label: "领先幅度（5~30）",
                    "aria-label": "领先幅度（5~30）",
                    type: "number",
                    min: "5",
                    max: "30",
                    variant: "outlined"
                  }, null, 8, ["modelValue"]),
                  _createVNode(_component_VSwitch, {
                    modelValue: localConfig.value.naming_append_tmdb_id,
                    "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((localConfig.value.naming_append_tmdb_id) = $event)),
                    label: "名称追加 TMDB ID",
                    "aria-label": "名称追加 TMDB ID",
                    color: "primary"
                  }, null, 8, ["modelValue"]),
                  _createVNode(_component_VSwitch, {
                    modelValue: localConfig.value.naming_ai_review,
                    "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((localConfig.value.naming_ai_review) = $event)),
                    label: "启用 AI 搜索与复核",
                    "aria-label": "启用 AI 搜索与复核",
                    hint: "复杂目录会先精简名称再搜索",
                    "persistent-hint": "",
                    color: "primary"
                  }, null, 8, ["modelValue"]),
                  _createVNode(_component_VSwitch, {
                    modelValue: localConfig.value.naming_clear_cache_once,
                    "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((localConfig.value.naming_clear_cache_once) = $event)),
                    label: "一次性清空识别缓存",
                    "aria-label": "一次性清空识别缓存",
                    hint: "下次运行时清除旧识别结果；执行后自动复位",
                    "persistent-hint": "",
                    color: "error"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createElementVNode("div", _hoisted_1, [
        _createVNode(_component_VBtn, {
          variant: "text",
          "min-width": "88",
          onClick: _cache[7] || (_cache[7] = $event => (emit('close')))
        }, {
          default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
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
          default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-6c47cfca"]]);

export { Config as default };
