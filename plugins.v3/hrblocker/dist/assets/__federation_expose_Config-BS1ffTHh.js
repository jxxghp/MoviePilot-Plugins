import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "hrb-config-root pa-4" };
const _hoisted_2 = { class: "d-flex justify-end gap-2" };

const {onMounted,reactive} = await importShared('vue');



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

// 与全屏海报墙同一约定：保存交给宿主前端（emit('save', cfg)），
// 宿主会用 api.put('plugin/{id}', cfg) 持久化，组件内不直接写 API。
const props = __props;

const emit = __emit;

const defaults = {
  enabled: false,
  block_marked: true,
  sync_assistant: true,
  block_manual: true,
  notify: false,
};

const local = reactive({ ...defaults });

onMounted(() => {
  const ic = props.initialConfig;
  if (ic && typeof ic === 'object') {
    Object.keys(defaults).forEach(k => {
      if (ic[k] !== undefined) local[k] = ic[k];
    });
  }
});

function onSave() {
  emit('save', JSON.parse(JSON.stringify(local)));
}

function onReset() {
  Object.assign(local, defaults);
}

return (_ctx, _cache) => {
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card = _resolveComponent("v-card");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, {
      variant: "outlined",
      class: "pa-4"
    }, {
      default: _withCtx(() => [
        _cache[8] || (_cache[8] = _createElementVNode("h3", { class: "mb-3" }, "H&R Blocker — 插件设置", -1)),
        _createVNode(_component_v_switch, {
          modelValue: local.enabled,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((local.enabled) = $event)),
          label: "启用插件",
          color: "primary",
          "hide-details": "",
          density: "comfortable",
          class: "mb-2"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_switch, {
          modelValue: local.block_marked,
          "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((local.block_marked) = $event)),
          label: "屏蔽H&R标记种子",
          hint: "屏蔽站点搜索结果中带有H&R标记的种子",
          "persistent-hint": "",
          color: "primary",
          density: "comfortable",
          class: "mb-2"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_switch, {
          modelValue: local.sync_assistant,
          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((local.sync_assistant) = $event)),
          label: "联动H&R助手",
          hint: "屏蔽H&R助手配置中已激活全站H&R的站点（该站所有种子均视为H&R）",
          "persistent-hint": "",
          color: "primary",
          density: "comfortable",
          class: "mb-2"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_switch, {
          modelValue: local.block_manual,
          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((local.block_manual) = $event)),
          label: "拦截手动下载",
          hint: "手动下载H&R种子时同样拦截（关闭则仅自动选择场景生效）",
          "persistent-hint": "",
          color: "primary",
          density: "comfortable",
          class: "mb-2"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_switch, {
          modelValue: local.notify,
          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((local.notify) = $event)),
          label: "拦截通知",
          hint: "拦截H&R种子时发送消息通知",
          "persistent-hint": "",
          color: "primary",
          density: "comfortable",
          class: "mb-4"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_v_alert, {
          type: "info",
          variant: "tonal",
          density: "compact",
          class: "mb-4"
        }, {
          default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
            _createTextVNode(" 工作方式：在「资源选择」阶段从候选列表中剔除H&R种子（订阅、搜索择优、豆瓣同步等自动场景均生效）， 并在「实际下载」前二次兜底拦截。H&R判定来源：①站点搜索结果中的H&R标记； ②H&R助手配置中 hr_active 已激活的全站H&R站点（需已安装并配置H&R助手）。 ", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_v_divider, { class: "my-3" }),
        _createElementVNode("div", _hoisted_2, [
          _createVNode(_component_v_btn, {
            variant: "text",
            onClick: onReset
          }, {
            default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
              _createTextVNode("重置默认", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_v_btn, {
            color: "primary",
            onClick: onSave
          }, {
            default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
              _createTextVNode("保存", -1)
            ]))]),
            _: 1
          })
        ])
      ]),
      _: 1
    })
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-b81a96eb"]]);

export { Config as default };
