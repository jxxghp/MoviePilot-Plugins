import { d as _export_sfc, e as __mf_2, v as cloneTask, f as __mf_8, g as __mf_22, i as __mf_21, a as __mf_19, b as __mf_9, m as __mf_3, w as __mf_23, o as __mf_14, r as __mf_13, l as __mf_6, x as __mf_1, k as __mf_12, s as __mf_10, y as normalizeTask, z as __mf_15, t as taskStateMeta, c as __mf_17, h as __mf_18, j as __mf_11, A as __mf_4, B as __mf_16, p as __mf_7, q as __mf_20, C as formatDateTime, n as formatBytes, D as formatDuration, E as torrentProgress, F as __mf_5, u as unwrapResponse, G as normalizeSettings } from './_plugin-vue_export-helper-C960cP-z.js';

const __mfPromiseGlobalKey = "__mf_init__virtual:mf:__mfe_internal__BrushFlow__mf_owner__217245097701611__mf_v__runtimeInit__mf_v__.js__";
let __mfPromiseState = globalThis[__mfPromiseGlobalKey];
if (!__mfPromiseState) {
  let initResolve, initReject;
  const initPromise = new Promise((re, rj) => {
    initResolve = re;
    initReject = rj;
  });
  __mfPromiseState = globalThis[__mfPromiseGlobalKey] = {
    initPromise,
    initResolve,
    initReject,
  };
  
}
const initPromise = __mfPromiseState.initPromise;

    
const __mfCacheGlobalKey = "__mf_module_cache__";
globalThis[__mfCacheGlobalKey] ||= { share: {}, remote: {} };
globalThis[__mfCacheGlobalKey].share ||= {};
globalThis[__mfCacheGlobalKey].remote ||= {};
const __mfModuleCache = globalThis[__mfCacheGlobalKey];
const __mfTrackPendingShareLoad = (promise) => {
  const pendingShareLoads = (__mfModuleCache.pendingShareLoads ||= []);
  pendingShareLoads.push(promise);
  const cleanup = () => {
    const index = pendingShareLoads.indexOf(promise);
    if (index !== -1) pendingShareLoads.splice(index, 1);
  };
  void promise.then(cleanup, cleanup);
  return promise;
};
for (const __mfShareKey of Object.keys(__mfModuleCache.share)) {
  if (__mfShareKey.startsWith("default:")) {
    const __mfLegacyShareKey = __mfShareKey.slice("default:".length);
    if (__mfModuleCache.share[__mfLegacyShareKey] === undefined) {
      __mfModuleCache.share[__mfLegacyShareKey] = __mfModuleCache.share[__mfShareKey];
    }
  } else if (!__mfShareKey.includes(":")) {
    const __mfDefaultShareKey = "default:" + __mfShareKey;
    if (__mfModuleCache.share[__mfDefaultShareKey] === undefined) {
      __mfModuleCache.share[__mfDefaultShareKey] = __mfModuleCache.share[__mfShareKey];
    }
  }
}
          const __mfReadSharedCache = (cache, descriptor) => {
            const value = cache[descriptor.canonical];
            if (value !== undefined) return value;
            const aliases = descriptor.aliases || [];
            for (const alias of aliases) {
              if (!Object.prototype.hasOwnProperty.call(cache, alias)) continue;
              const aliasValue = cache[alias];
              if (aliasValue !== undefined) {
                cache[descriptor.canonical] = aliasValue;
                return aliasValue;
              }
            }
            return undefined;
          };
          const __mfSharedCacheListenersKey = Symbol.for("module-federation.shared-cache-listeners");
          const __mfGetSharedCacheListeners = (cache) => {
            let listeners = cache[__mfSharedCacheListenersKey];
            if (listeners === undefined) {
              listeners = Object.create(null);
              Object.defineProperty(cache, __mfSharedCacheListenersKey, {
                value: listeners,
                enumerable: false,
                configurable: false,
                writable: false
              });
            }
            return listeners;
          };
          const __mfSubscribeSharedCache = (cache, descriptor, listener) => {
            const listeners = __mfGetSharedCacheListeners(cache);
            (listeners[descriptor.canonical] ||= new Set()).add(listener);
          };
    let __mf_0;
    const __mfApplyHostProvidedExports = (exportModule) => {
      __mf_0 = exportModule["useDisplay"];
      exportModule.default ?? exportModule;
    };
    let exportModule = __mfReadSharedCache(__mfModuleCache.share, {"canonical":"default:vuetify","aliases":["vuetify"]});
    if (exportModule === undefined) {
      __mfSubscribeSharedCache(__mfModuleCache.share, {"canonical":"default:vuetify"}, (mod) => {
        exportModule = mod;
        __mfApplyHostProvidedExports(mod);
      });
      __mfTrackPendingShareLoad(initPromise.then(() => {
        exportModule = __mfReadSharedCache(__mfModuleCache.share, {"canonical":"default:vuetify","aliases":["vuetify"]});
        // A share init() left to its dynamic import is normally bridged before that import runs;
        // bridge it here when this wrapper is reached another way.
        if (exportModule === undefined && typeof __mfPromiseState.loadLazyShares === "function") {
          return __mfPromiseState.loadLazyShares(["vuetify"]).then(() => {
            exportModule = __mfReadSharedCache(__mfModuleCache.share, {"canonical":"default:vuetify","aliases":["vuetify"]});
          });
        }
      }).then(() => {
        if (exportModule === undefined) {
          throw new Error("[Module Federation] Shared module vuetify was imported before federation bootstrap finished.");
        }
        __mfApplyHostProvidedExports(exportModule);
      }));
    } else {
      __mfApplyHostProvidedExports(exportModule);
    }

const _hoisted_1$1 = { class: "editor-section" };
const _hoisted_2$1 = { class: "editor-section__head" };
const _hoisted_3$1 = { class: "editor-switches" };
const _hoisted_4$1 = { class: "editor-section" };
const _hoisted_5$1 = { class: "editor-section" };
const _hoisted_6$1 = { class: "editor-section" };
const _hoisted_7$1 = { class: "editor-switches" };
const _hoisted_8$1 = { class: "editor-section" };
const _hoisted_9$1 = { class: "editor-section" };
const _hoisted_10$1 = { class: "editor-section" };
const _hoisted_11$1 = { class: "editor-section" };
const _hoisted_12$1 = { class: "editor-section__head" };
const _hoisted_13$1 = { class: "text-subtitle-1 font-weight-medium" };
const _hoisted_14$1 = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_15$1 = { class: "editor-section" };
const _hoisted_16$1 = { class: "editor-section" };
const _hoisted_17$1 = { class: "editor-switches" };


const _sfc_main$1 = {
  __name: 'TaskEditorDialog',
  props: {
  modelValue: { type: Boolean, default: false },
  task: { type: Object, default: () => ({}) },
  sites: { type: Array, default: () => [] },
  downloaders: { type: Array, default: () => [] },
  globalDynamicDelete: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
},
  emits: ['update:modelValue', 'save'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;
const display = __mf_0();
const formRef = __mf_2(null);
const activeTab = __mf_2('base');
const localTask = __mf_2(cloneTask());

const dialogTitle = __mf_8(() => (localTask.value.id ? '编辑刷流任务' : '新建刷流任务'));
const siteName = __mf_8(() => props.sites.find(item => item.value === Number(localTask.value.site_id))?.title || '未选择');
const scheduleText = __mf_8(() => localTask.value.cron || `每 ${localTask.value.brush_interval || 10} 分钟`);

// 每次打开弹窗都从服务端任务快照重新创建本地草稿。
__mf_22(
  () => props.modelValue,
  visible => {
    if (!visible) return
    localTask.value = cloneTask(props.task);
    activeTab.value = 'base';
  },
);

// 关闭编辑器并丢弃尚未保存的草稿。
function closeDialog() {
  emit('update:modelValue', false);
}

// 校验必填项后提交标准化任务数据。
async function saveTask() {
  const result = await formRef.value?.validate();
  if (result && !result.valid) return
  emit('save', normalizeTask(localTask.value));
}

return (_ctx, _cache) => {
  const _component_VToolbarTitle = __mf_21("VToolbarTitle");
  const _component_VSpacer = __mf_21("VSpacer");
  const _component_VBtn = __mf_21("VBtn");
  const _component_VToolbar = __mf_21("VToolbar");
  const _component_VDivider = __mf_21("VDivider");
  const _component_VTab = __mf_21("VTab");
  const _component_VTabs = __mf_21("VTabs");
  const _component_VChip = __mf_21("VChip");
  const _component_VTextField = __mf_21("VTextField");
  const _component_VCol = __mf_21("VCol");
  const _component_VSelect = __mf_21("VSelect");
  const _component_VRow = __mf_21("VRow");
  const _component_VSwitch = __mf_21("VSwitch");
  const _component_VWindowItem = __mf_21("VWindowItem");
  const _component_VBtnToggle = __mf_21("VBtnToggle");
  const _component_VWindow = __mf_21("VWindow");
  const _component_VSheet = __mf_21("VSheet");
  const _component_VForm = __mf_21("VForm");
  const _component_VCardText = __mf_21("VCardText");
  const _component_VCard = __mf_21("VCard");
  const _component_VDialog = __mf_21("VDialog");

  return (__mf_19(), __mf_9(_component_VDialog, {
    "model-value": __props.modelValue,
    scrollable: "",
    fullscreen: __mf_3(display).smAndDown.value,
    "max-width": "74rem",
    "onUpdate:modelValue": _cache[45] || (_cache[45] = value => emit('update:modelValue', value))
  }, {
    default: __mf_23(() => [
      __mf_14(_component_VCard, { class: "brushflow-editor" }, {
        default: __mf_23(() => [
          __mf_14(_component_VToolbar, {
            color: "transparent",
            density: "comfortable",
            class: "brushflow-editor__toolbar"
          }, {
            default: __mf_23(() => [
              __mf_14(_component_VToolbarTitle, null, {
                default: __mf_23(() => [
                  __mf_13(__mf_6(dialogTitle.value), 1)
                ]),
                _: 1
              }),
              __mf_14(_component_VSpacer),
              __mf_14(_component_VBtn, {
                color: "primary",
                variant: "flat",
                "prepend-icon": "mdi-content-save",
                loading: __props.saving,
                onClick: saveTask
              }, {
                default: __mf_23(() => [...(_cache[46] || (_cache[46] = [
                  __mf_13(" 保存任务 ", -1)
                ]))]),
                _: 1
              }, 8, ["loading"]),
              __mf_14(_component_VBtn, {
                icon: "mdi-close",
                variant: "text",
                "aria-label": "关闭",
                onClick: closeDialog
              })
            ]),
            _: 1
          }),
          __mf_14(_component_VDivider),
          __mf_14(_component_VCardText, { class: "brushflow-editor__body" }, {
            default: __mf_23(() => [
              __mf_14(_component_VForm, {
                ref_key: "formRef",
                ref: formRef,
                class: "brushflow-editor__form",
                onSubmit: __mf_1(saveTask, ["prevent"])
              }, {
                default: __mf_23(() => [
                  __mf_14(_component_VTabs, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((activeTab).value = $event)),
                    direction: __mf_3(display).mdAndUp.value ? 'vertical' : 'horizontal',
                    color: "primary",
                    class: "brushflow-editor__tabs"
                  }, {
                    default: __mf_23(() => [
                      __mf_14(_component_VTab, {
                        value: "base",
                        "prepend-icon": "mdi-calendar-clock"
                      }, {
                        default: __mf_23(() => [...(_cache[47] || (_cache[47] = [
                          __mf_13("基础与调度", -1)
                        ]))]),
                        _: 1
                      }),
                      __mf_14(_component_VTab, {
                        value: "selection",
                        "prepend-icon": "mdi-filter-cog-outline"
                      }, {
                        default: __mf_23(() => [...(_cache[48] || (_cache[48] = [
                          __mf_13("选种规则", -1)
                        ]))]),
                        _: 1
                      }),
                      __mf_14(_component_VTab, {
                        value: "limits",
                        "prepend-icon": "mdi-gauge"
                      }, {
                        default: __mf_23(() => [...(_cache[49] || (_cache[49] = [
                          __mf_13("运行限额", -1)
                        ]))]),
                        _: 1
                      }),
                      __mf_14(_component_VTab, {
                        value: "delete",
                        "prepend-icon": "mdi-delete-clock-outline"
                      }, {
                        default: __mf_23(() => [...(_cache[50] || (_cache[50] = [
                          __mf_13("删种规则", -1)
                        ]))]),
                        _: 1
                      }),
                      __mf_14(_component_VTab, {
                        value: "advanced",
                        "prepend-icon": "mdi-tune-variant"
                      }, {
                        default: __mf_23(() => [...(_cache[51] || (_cache[51] = [
                          __mf_13("高级", -1)
                        ]))]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["modelValue", "direction"]),
                  __mf_14(_component_VDivider, {
                    vertical: __mf_3(display).mdAndUp.value
                  }, null, 8, ["vertical"]),
                  __mf_14(_component_VWindow, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[44] || (_cache[44] = $event => ((activeTab).value = $event)),
                    touch: false,
                    class: "brushflow-editor__window"
                  }, {
                    default: __mf_23(() => [
                      __mf_14(_component_VWindowItem, { value: "base" }, {
                        default: __mf_23(() => [
                          __mf_12("section", _hoisted_1$1, [
                            __mf_12("header", _hoisted_2$1, [
                              _cache[53] || (_cache[53] = __mf_12("div", null, [
                                __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "任务身份"),
                                __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "每个任务绑定一个站点和下载器")
                              ], -1)),
                              __mf_14(_component_VChip, {
                                size: "small",
                                color: "primary",
                                variant: "tonal"
                              }, {
                                default: __mf_23(() => [...(_cache[52] || (_cache[52] = [
                                  __mf_13("必填", -1)
                                ]))]),
                                _: 1
                              })
                            ]),
                            __mf_14(_component_VRow, null, {
                              default: __mf_23(() => [
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.name,
                                      "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((localTask.value.name) = $event)),
                                      label: "任务名称",
                                      rules: [value => !!String(value || '').trim() || '请输入任务名称']
                                    }, null, 8, ["modelValue", "rules"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VSelect, {
                                      modelValue: localTask.value.site_id,
                                      "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((localTask.value.site_id) = $event)),
                                      items: __props.sites,
                                      label: "站点",
                                      rules: [value => !!value || '请选择站点']
                                    }, null, 8, ["modelValue", "items", "rules"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VSelect, {
                                      modelValue: localTask.value.downloader,
                                      "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((localTask.value.downloader) = $event)),
                                      items: __props.downloaders,
                                      label: "下载器",
                                      rules: [value => !!value || '请选择下载器']
                                    }, null, 8, ["modelValue", "items", "rules"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.save_path,
                                      "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((localTask.value.save_path) = $event)),
                                      label: "保存目录",
                                      placeholder: "留空使用下载器默认目录"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            }),
                            __mf_12("div", _hoisted_3$1, [
                              __mf_14(_component_VSwitch, {
                                modelValue: localTask.value.enabled,
                                "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((localTask.value.enabled) = $event)),
                                label: "启用任务",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"]),
                              __mf_14(_component_VSwitch, {
                                modelValue: localTask.value.notify,
                                "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((localTask.value.notify) = $event)),
                                label: "发送通知",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"])
                            ])
                          ]),
                          __mf_12("section", _hoisted_4$1, [
                            _cache[54] || (_cache[54] = __mf_12("header", { class: "editor-section__head" }, [
                              __mf_12("div", null, [
                                __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "刷新计划"),
                                __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "刷流刷新和下载状态检查分别调度")
                              ])
                            ], -1)),
                            __mf_14(_component_VRow, null, {
                              default: __mf_23(() => [
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.brush_interval,
                                      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((localTask.value.brush_interval) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "1",
                                      max: "1440",
                                      label: "刷流刷新周期（分钟）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.check_interval,
                                      "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((localTask.value.check_interval) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "1",
                                      max: "1440",
                                      label: "状态检查周期（分钟）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.cron,
                                      "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((localTask.value.cron) = $event)),
                                      label: "CRON 表达式",
                                      placeholder: "留空使用固定刷新周期"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.active_time_range,
                                      "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((localTask.value.active_time_range) = $event)),
                                      label: "开启时间段",
                                      placeholder: "如 00:00-08:00"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          __mf_12("section", _hoisted_5$1, [
                            _cache[55] || (_cache[55] = __mf_12("header", { class: "editor-section__head" }, [
                              __mf_12("div", null, [
                                __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "站点分享率控制"),
                                __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "根据最新站点统计自动等待或恢复刷流")
                              ])
                            ], -1)),
                            __mf_14(_component_VSwitch, {
                              modelValue: localTask.value.site_ratio_control,
                              "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((localTask.value.site_ratio_control) = $event)),
                              label: "启用站点分享率控制",
                              color: "primary",
                              "hide-details": "",
                              inset: ""
                            }, null, 8, ["modelValue"]),
                            (localTask.value.site_ratio_control)
                              ? (__mf_19(), __mf_9(_component_VRow, { key: 0 }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VCol, {
                                      cols: "12",
                                      md: "6"
                                    }, {
                                      default: __mf_23(() => [
                                        __mf_14(_component_VTextField, {
                                          modelValue: localTask.value.site_ratio_target,
                                          "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((localTask.value.site_ratio_target) = $event)),
                                          modelModifiers: { number: true },
                                          type: "number",
                                          min: "0.01",
                                          step: "0.01",
                                          label: "目标分享率",
                                          rules: [value => Number(value) > 0 || '请输入大于 0 的目标分享率']
                                        }, null, 8, ["modelValue", "rules"])
                                      ]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                }))
                              : __mf_10("", true)
                          ])
                        ]),
                        _: 1
                      }),
                      __mf_14(_component_VWindowItem, { value: "selection" }, {
                        default: __mf_23(() => [
                          __mf_12("section", _hoisted_6$1, [
                            _cache[56] || (_cache[56] = __mf_12("header", { class: "editor-section__head" }, [
                              __mf_12("div", null, [
                                __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "来源与促销"),
                                __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "沿用站点列表页或 RSS 获取链路")
                              ])
                            ], -1)),
                            __mf_14(_component_VRow, null, {
                              default: __mf_23(() => [
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VSelect, {
                                      modelValue: localTask.value.freeleech,
                                      "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((localTask.value.freeleech) = $event)),
                                      label: "促销",
                                      items: [
                        { title: '全部（包括普通）', value: '' },
                        { title: '免费', value: 'free' },
                        { title: '2X 免费', value: '2xfree' },
                      ]
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VSelect, {
                                      modelValue: localTask.value.hr,
                                      "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((localTask.value.hr) = $event)),
                                      label: "排除 H&R",
                                      items: [
                        { title: '是', value: 'yes' },
                        { title: '否', value: 'no' },
                      ]
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            }),
                            __mf_12("div", _hoisted_7$1, [
                              __mf_14(_component_VSwitch, {
                                modelValue: localTask.value.rss_support,
                                "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((localTask.value.rss_support) = $event)),
                                label: "使用 RSS",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"]),
                              __mf_14(_component_VSwitch, {
                                modelValue: localTask.value.except_subscribe,
                                "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((localTask.value.except_subscribe) = $event)),
                                label: "排除订阅",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"]),
                              __mf_14(_component_VSwitch, {
                                modelValue: localTask.value.site_hr_active,
                                "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((localTask.value.site_hr_active) = $event)),
                                label: "全站 H&R",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"])
                            ])
                          ]),
                          __mf_12("section", _hoisted_8$1, [
                            _cache[57] || (_cache[57] = __mf_12("header", { class: "editor-section__head" }, [
                              __mf_12("div", null, [
                                __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "候选过滤"),
                                __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "范围字段支持单值或“最小值-最大值”")
                              ])
                            ], -1)),
                            __mf_14(_component_VRow, null, {
                              default: __mf_23(() => [
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.size,
                                      "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((localTask.value.size) = $event)),
                                      label: "种子大小（GB）",
                                      placeholder: "10-80"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.seeder,
                                      "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((localTask.value.seeder) = $event)),
                                      label: "做种人数",
                                      placeholder: "1-10"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.pubtime,
                                      "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((localTask.value.pubtime) = $event)),
                                      label: "发布时间（分钟）",
                                      placeholder: "5-120"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.timezone_offset,
                                      "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((localTask.value.timezone_offset) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      label: "站点时区偏移（小时）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "8"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.include,
                                      "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((localTask.value.include) = $event)),
                                      label: "包含规则",
                                      placeholder: "支持正则表达式"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, { cols: "12" }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.exclude,
                                      "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((localTask.value.exclude) = $event)),
                                      label: "排除规则",
                                      placeholder: "支持正则表达式"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ])
                        ]),
                        _: 1
                      }),
                      __mf_14(_component_VWindowItem, { value: "limits" }, {
                        default: __mf_23(() => [
                          __mf_12("section", _hoisted_9$1, [
                            _cache[58] || (_cache[58] = __mf_12("header", { class: "editor-section__head" }, [
                              __mf_12("div", null, [
                                __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "新增任务上限"),
                                __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "达到任一上限后停止为当前任务新增种子")
                              ])
                            ], -1)),
                            __mf_14(_component_VRow, null, {
                              default: __mf_23(() => [
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.disksize,
                                      "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((localTask.value.disksize) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "保种体积（GB）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.maxdlcount,
                                      "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((localTask.value.maxdlcount) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "同时下载任务数"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.maxupspeed,
                                      "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((localTask.value.maxupspeed) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "总上传带宽（KB/s）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.maxdlspeed,
                                      "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((localTask.value.maxdlspeed) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "总下载带宽（KB/s）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          __mf_12("section", _hoisted_10$1, [
                            _cache[59] || (_cache[59] = __mf_12("header", { class: "editor-section__head" }, [
                              __mf_12("div", null, [
                                __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "单种限速"),
                                __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "只作用于当前任务新添加的种子")
                              ])
                            ], -1)),
                            __mf_14(_component_VRow, null, {
                              default: __mf_23(() => [
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.up_speed,
                                      "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((localTask.value.up_speed) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "上传限速（KB/s）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.dl_speed,
                                      "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((localTask.value.dl_speed) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "下载限速（KB/s）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ])
                        ]),
                        _: 1
                      }),
                      __mf_14(_component_VWindowItem, { value: "delete" }, {
                        default: __mf_23(() => [
                          __mf_12("section", _hoisted_11$1, [
                            __mf_12("header", _hoisted_12$1, [
                              __mf_12("div", null, [
                                __mf_12("div", _hoisted_13$1, __mf_6(__props.globalDynamicDelete ? '全局删种托管' : '删除模式'), 1),
                                __mf_12("div", _hoisted_14$1, __mf_6(__props.globalDynamicDelete ? '选择此任务是否参加全局阈值兜底淘汰' : '动态模式会在超过体积阈值后按现有算法托管删种'), 1)
                              ])
                            ]),
                            __mf_14(_component_VBtnToggle, {
                              modelValue: localTask.value.proxy_delete,
                              "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((localTask.value.proxy_delete) = $event)),
                              mandatory: "",
                              color: "primary",
                              divided: ""
                            }, {
                              default: __mf_23(() => [
                                __mf_14(_component_VBtn, { value: false }, {
                                  default: __mf_23(() => [
                                    __mf_13(__mf_6(__props.globalDynamicDelete ? '不参与托管' : '按条件删除'), 1)
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VBtn, { value: true }, {
                                  default: __mf_23(() => [
                                    __mf_13(__mf_6(__props.globalDynamicDelete ? '参与全局托管' : '动态删种'), 1)
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            }, 8, ["modelValue"]),
                            (localTask.value.proxy_delete && !__props.globalDynamicDelete)
                              ? (__mf_19(), __mf_9(_component_VRow, { key: 0 }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VCol, { cols: "12" }, {
                                      default: __mf_23(() => [
                                        __mf_14(_component_VTextField, {
                                          modelValue: localTask.value.delete_size_range,
                                          "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((localTask.value.delete_size_range) = $event)),
                                          label: "动态删种阈值（GB）",
                                          placeholder: "如 350-500"
                                        }, null, 8, ["modelValue"])
                                      ]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                }))
                              : __mf_10("", true)
                          ]),
                          __mf_12("section", _hoisted_15$1, [
                            _cache[60] || (_cache[60] = __mf_12("header", { class: "editor-section__head" }, [
                              __mf_12("div", null, [
                                __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "触发条件"),
                                __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "普通模式满足任一条件即删除")
                              ])
                            ], -1)),
                            __mf_14(_component_VRow, null, {
                              default: __mf_23(() => [
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.seed_time,
                                      "onUpdate:modelValue": _cache[32] || (_cache[32] = $event => ((localTask.value.seed_time) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "做种时间（小时）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.hr_seed_time,
                                      "onUpdate:modelValue": _cache[33] || (_cache[33] = $event => ((localTask.value.hr_seed_time) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "H&R 做种时间（小时）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.seed_ratio,
                                      "onUpdate:modelValue": _cache[34] || (_cache[34] = $event => ((localTask.value.seed_ratio) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "分享率"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.seed_size,
                                      "onUpdate:modelValue": _cache[35] || (_cache[35] = $event => ((localTask.value.seed_size) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "上传量（GB）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.download_time,
                                      "onUpdate:modelValue": _cache[36] || (_cache[36] = $event => ((localTask.value.download_time) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "下载超时（小时）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.seed_inactivetime,
                                      "onUpdate:modelValue": _cache[37] || (_cache[37] = $event => ((localTask.value.seed_inactivetime) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "未活动时间（分钟）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.seed_avgspeed,
                                      "onUpdate:modelValue": _cache[38] || (_cache[38] = $event => ((localTask.value.seed_avgspeed) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "平均上传速度（KB/s）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "8"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.delete_except_tags,
                                      "onUpdate:modelValue": _cache[39] || (_cache[39] = $event => ((localTask.value.delete_except_tags) = $event)),
                                      label: "删除排除标签"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            }),
                            __mf_14(_component_VSwitch, {
                              modelValue: localTask.value.del_no_free,
                              "onUpdate:modelValue": _cache[40] || (_cache[40] = $event => ((localTask.value.del_no_free) = $event)),
                              label: "删除促销过期的未完成下载",
                              color: "primary",
                              "hide-details": "",
                              inset: ""
                            }, null, 8, ["modelValue"])
                          ])
                        ]),
                        _: 1
                      }),
                      __mf_14(_component_VWindowItem, { value: "advanced" }, {
                        default: __mf_23(() => [
                          __mf_12("section", _hoisted_16$1, [
                            _cache[61] || (_cache[61] = __mf_12("header", { class: "editor-section__head" }, [
                              __mf_12("div", null, [
                                __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "下载器适配"),
                                __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "保留原有分类、提示跳过和自动归档能力")
                              ])
                            ], -1)),
                            __mf_14(_component_VRow, null, {
                              default: __mf_23(() => [
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.qb_category,
                                      "onUpdate:modelValue": _cache[41] || (_cache[41] = $event => ((localTask.value.qb_category) = $event)),
                                      label: "qBittorrent 分类"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                __mf_14(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: __mf_23(() => [
                                    __mf_14(_component_VTextField, {
                                      modelValue: localTask.value.auto_archive_days,
                                      "onUpdate:modelValue": _cache[42] || (_cache[42] = $event => ((localTask.value.auto_archive_days) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "自动归档天数"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            }),
                            __mf_12("div", _hoisted_17$1, [
                              __mf_14(_component_VSwitch, {
                                modelValue: localTask.value.site_skip_tips,
                                "onUpdate:modelValue": _cache[43] || (_cache[43] = $event => ((localTask.value.site_skip_tips) = $event)),
                                label: "自动跳过下载提示",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"])
                            ])
                          ])
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["modelValue"]),
                  __mf_14(_component_VSheet, {
                    tag: "aside",
                    class: "brushflow-editor__summary"
                  }, {
                    default: __mf_23(() => [
                      _cache[71] || (_cache[71] = __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "配置摘要", -1)),
                      __mf_12("dl", null, [
                        __mf_12("div", null, [
                          _cache[62] || (_cache[62] = __mf_12("dt", null, "站点", -1)),
                          __mf_12("dd", null, __mf_6(siteName.value), 1)
                        ]),
                        __mf_12("div", null, [
                          _cache[63] || (_cache[63] = __mf_12("dt", null, "下载器", -1)),
                          __mf_12("dd", null, __mf_6(localTask.value.downloader || '未选择'), 1)
                        ]),
                        __mf_12("div", null, [
                          _cache[64] || (_cache[64] = __mf_12("dt", null, "刷新", -1)),
                          __mf_12("dd", null, __mf_6(scheduleText.value), 1)
                        ]),
                        __mf_12("div", null, [
                          _cache[65] || (_cache[65] = __mf_12("dt", null, "检查", -1)),
                          __mf_12("dd", null, "每 " + __mf_6(localTask.value.check_interval || 5) + " 分钟", 1)
                        ]),
                        __mf_12("div", null, [
                          _cache[66] || (_cache[66] = __mf_12("dt", null, "时段", -1)),
                          __mf_12("dd", null, __mf_6(localTask.value.active_time_range || '全天'), 1)
                        ]),
                        __mf_12("div", null, [
                          _cache[67] || (_cache[67] = __mf_12("dt", null, "目标分享率", -1)),
                          __mf_12("dd", null, __mf_6(localTask.value.site_ratio_control ? localTask.value.site_ratio_target || '未设置' : '关闭'), 1)
                        ]),
                        __mf_12("div", null, [
                          _cache[68] || (_cache[68] = __mf_12("dt", null, "促销", -1)),
                          __mf_12("dd", null, __mf_6(localTask.value.freeleech === '2xfree' ? '2X 免费' : localTask.value.freeleech === 'free' ? '免费' : '全部'), 1)
                        ]),
                        __mf_12("div", null, [
                          _cache[69] || (_cache[69] = __mf_12("dt", null, "保种上限", -1)),
                          __mf_12("dd", null, __mf_6(localTask.value.disksize ? `${localTask.value.disksize} GB` : '不限'), 1)
                        ]),
                        __mf_12("div", null, [
                          _cache[70] || (_cache[70] = __mf_12("dt", null, "删除", -1)),
                          __mf_12("dd", null, __mf_6(localTask.value.proxy_delete ? '动态删种' : '按条件删除'), 1)
                        ])
                      ])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }, 512)
            ]),
            _: 1
          })
        ]),
        _: 1
      })
    ]),
    _: 1
  }, 8, ["model-value", "fullscreen"]))
}
}

};
const TaskEditorDialog = /*#__PURE__*/_export_sfc(_sfc_main$1, [['__scopeId',"data-v-7869d33a"]]);

const _hoisted_1 = { class: "brushflow-page__header" };
const _hoisted_2 = { class: "brushflow-page__identity" };
const _hoisted_3 = { class: "brushflow-page__actions" };
const _hoisted_4 = {
  key: 2,
  class: "brushflow-loading"
};
const _hoisted_5 = {
  key: 3,
  class: "brushflow-empty"
};
const _hoisted_6 = { class: "brushflow-layout" };
const _hoisted_7 = { class: "brushflow-task-rail__head" };
const _hoisted_8 = { class: "brushflow-task-list" };
const _hoisted_9 = ["aria-pressed", "onClick"];
const _hoisted_10 = { class: "brushflow-task-item__title" };
const _hoisted_11 = { class: "brushflow-task-item__meta" };
const _hoisted_12 = {
  key: 0,
  class: "brushflow-workspace"
};
const _hoisted_13 = { class: "brushflow-task-head" };
const _hoisted_14 = { class: "brushflow-task-head__identity" };
const _hoisted_15 = { class: "brushflow-task-head__title" };
const _hoisted_16 = { class: "brushflow-task-head__actions" };
const _hoisted_17 = { class: "brushflow-stat-grid" };
const _hoisted_18 = { key: 0 };
const _hoisted_19 = { key: 1 };
const _hoisted_20 = { class: "brushflow-overview-grid" };
const _hoisted_21 = { class: "brushflow-panel__head" };
const _hoisted_22 = { class: "brushflow-facts" };
const _hoisted_23 = { key: 0 };
const _hoisted_24 = { class: "brushflow-panel__head" };
const _hoisted_25 = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_26 = { class: "brushflow-run-summary" };
const _hoisted_27 = { class: "brushflow-panel__head" };
const _hoisted_28 = { class: "brushflow-panel__title-row" };
const _hoisted_29 = { class: "torrent-title-cell" };
const _hoisted_30 = { class: "brushflow-mobile-torrents" };
const _hoisted_31 = { class: "brushflow-mobile-torrent__head" };
const _hoisted_32 = { class: "brushflow-mobile-torrent__meta" };
const _hoisted_33 = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_34 = {
  key: 0,
  class: "brushflow-table-empty"
};
const _hoisted_35 = { class: "brushflow-diagnostic-head" };
const _hoisted_36 = { class: "text-subtitle-1 font-weight-medium" };
const _hoisted_37 = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_38 = { class: "brushflow-diagnostic-grid" };
const _hoisted_39 = { class: "brushflow-pipeline" };
const _hoisted_40 = { class: "brushflow-pipeline__index" };
const _hoisted_41 = {
  key: 0,
  class: "brushflow-reasons"
};
const _hoisted_42 = { class: "brushflow-reason__track" };
const _hoisted_43 = {
  key: 1,
  class: "brushflow-table-empty"
};
const _hoisted_44 = { class: "brushflow-events" };
const _hoisted_45 = {
  key: 0,
  class: "text-error"
};
const _hoisted_46 = {
  key: 0,
  class: "brushflow-table-empty"
};
const _hoisted_47 = { class: "brushflow-config-grid" };
const _hoisted_48 = { class: "brushflow-facts brushflow-facts--two" };
const _hoisted_49 = { class: "brushflow-config-actions" };


const _sfc_main = {
  __name: 'BrushFlowWorkbench',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'BrushFlow' },
  initialTab: { type: String, default: 'overview' },
  showClose: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
},
  emits: ['close', 'action'],
  setup(__props, { expose: __expose, emit: __emit }) {

const props = __props;

const emit = __emit;
const loading = __mf_2(false);
const taskLoading = __mf_2(false);
const saving = __mf_2(false);
const error = __mf_2('');
const status = __mf_2({
  enabled: false,
  show_sidebar_nav: true,
  summary: {},
  tasks: [],
  options: { sites: [], downloaders: [] },
});
const taskDetail = __mf_2(null);
const selectedTaskId = __mf_2('');
const activeTab = __mf_2(props.initialTab);
const torrentState = __mf_2('active');
const torrentPage = __mf_2(1);
const editorOpen = __mf_2(false);
const editorTask = __mf_2(cloneTask());
const deleteDialog = __mf_2(false);
const clearDialog = __mf_2(false);
const settingsMenu = __mf_2(false);
const settingsDraft = __mf_2({
  enabled: false,
  show_sidebar_nav: true,
  global_disksize: null,
  global_maxdlcount: null,
  global_maxupspeed: null,
  global_maxdlspeed: null,
  global_proxy_delete: false,
  global_delete_size_range: null,
});
const hostToast = __mf_15('moviepilot:toast', null);
let refreshTimer;

const pluginBase = __mf_8(() => `plugin/${props.pluginId || 'BrushFlow'}`);
const tasks = __mf_8(() => status.value.tasks || []);
const selectedTask = __mf_8(() => tasks.value.find(item => item.id === selectedTaskId.value) || null);
const selectedState = __mf_8(() => taskStateMeta(selectedTask.value?.state));
const taskConfig = __mf_8(() => taskDetail.value?.task || {});
const taskRuns = __mf_8(() => taskDetail.value?.runs || []);
const latestBrushRun = __mf_8(() => taskRuns.value.find(item => item.kind === 'brush') || null);
const torrentData = __mf_8(() => taskDetail.value?.torrents || { items: [], total: 0, page: 1, page_size: 50 });
const totalTorrentPages = __mf_8(() => Math.max(Math.ceil(torrentData.value.total / torrentData.value.page_size), 1));
const seedingPercent = __mf_8(() => {
  const limit = Number(taskConfig.value.disksize || 0) * 1024 ** 3;
  if (!limit) return 0
  return Math.min(Math.round((Number(selectedTask.value?.seeding_size || 0) * 100) / limit), 100)
});
const reasonEntries = __mf_8(() => {
  const reasons = latestBrushRun.value?.reason_counts || {};
  return Object.entries(reasons)
    .map(([label, count]) => ({ label, count: Number(count || 0) }))
    .sort((left, right) => right.count - left.count)
});
const maxReasonCount = __mf_8(() => Math.max(1, ...reasonEntries.value.map(item => item.count)));
const pipelineStages = __mf_8(() => {
  const run = latestBrushRun.value || {};
  const sourceCount = Number(run.source_count || 0);
  const candidateCount = Number(run.candidate_count || 0);
  const addedCount = Number(run.added_count || 0);
  return [
    { title: '获取站点种子', detail: taskConfig.value.rss_support ? 'RSS' : '站点列表页', count: sourceCount },
    { title: '排除订阅内容', detail: `排除 ${Number(run.subscription_excluded || 0)} 个`, count: candidateCount },
    { title: '选种条件过滤', detail: `过滤 ${Number(run.filtered_count || 0)} 个`, count: addedCount },
    { title: '添加下载任务', detail: run.success === false ? '执行失败' : '下载器已确认', count: addedCount },
  ]
});

const torrentHeaders = [
  { title: '种子', key: 'title', sortable: false },
  { title: '状态', key: 'status', sortable: false },
  { title: '大小', key: 'size', align: 'end', sortable: false },
  { title: '上传', key: 'uploaded', align: 'end', sortable: false },
  { title: '分享率', key: 'ratio', align: 'end', sortable: false },
  { title: '处理条件', key: 'policy', sortable: false },
];

// 通过宿主注入的 Toast 显示操作结果，不在插件内创建第二套通知层。
function notify(text, color = 'success') {
  const method = ['error', 'info', 'warning', 'success'].includes(color) ? color : 'success';
  if (typeof hostToast?.[method] === 'function') {
    hostToast[method](text);
  } else if (method === 'error') {
    error.value = text;
  }
}

// 从插件状态接口加载全局设置和任务摘要。
async function loadStatus({ preserveSelection = true, loadDetail = true } = {}) {
  loading.value = true;
  error.value = '';
  try {
    const data = unwrapResponse(await props.api.get(`${pluginBase.value}/status`));
    status.value = data || status.value;
    settingsDraft.value = {
      enabled: Boolean(status.value.enabled),
      show_sidebar_nav: status.value.show_sidebar_nav !== false,
      global_disksize: status.value.global_disksize ?? null,
      global_maxdlcount: status.value.global_maxdlcount ?? null,
      global_maxupspeed: status.value.global_maxupspeed ?? null,
      global_maxdlspeed: status.value.global_maxdlspeed ?? null,
      global_proxy_delete: Boolean(status.value.global_proxy_delete),
      global_delete_size_range: status.value.global_delete_size_range ?? null,
    };
    const selectedStillExists = tasks.value.some(item => item.id === selectedTaskId.value);
    if (!preserveSelection || !selectedStillExists) selectedTaskId.value = tasks.value[0]?.id || '';
    if (loadDetail && selectedTaskId.value) await loadTaskDetail();
  } catch (err) {
    error.value = err?.message || '加载刷流任务失败';
  } finally {
    loading.value = false;
  }
}

// 加载选中任务的配置、诊断记录和当前分页种子。
async function loadTaskDetail() {
  if (!selectedTaskId.value) {
    taskDetail.value = null;
    return
  }
  taskLoading.value = true;
  try {
    const query = `state=${torrentState.value}&page=${torrentPage.value}&page_size=50`;
    taskDetail.value = unwrapResponse(
      await props.api.get(`${pluginBase.value}/tasks/${selectedTaskId.value}?${query}`),
    );
  } catch (err) {
    error.value = err?.message || '加载任务详情失败';
  } finally {
    taskLoading.value = false;
  }
}

// 切换左侧任务并从第一页加载对应明细。
async function selectTask(taskId) {
  if (!taskId || taskId === selectedTaskId.value) return
  selectedTaskId.value = taskId;
  torrentState.value = 'active';
  torrentPage.value = 1;
  await loadTaskDetail();
}

// 同时刷新任务摘要和当前任务详情。
async function refreshAll(showMessage = false) {
  await loadStatus();
  if (showMessage) notify('刷流任务数据已刷新');
  emit('action');
}

// 打开一个空白任务草稿。
function openCreateTask() {
  editorTask.value = cloneTask();
  editorOpen.value = true;
}

// 打开当前任务的服务端配置快照。
function openEditTask() {
  if (!taskConfig.value.id) return
  editorTask.value = cloneTask(taskConfig.value);
  editorOpen.value = true;
}

// 通过任务 API 创建或更新任务并刷新调度状态。
async function saveTask(task) {
  saving.value = true;
  try {
    const response = task.id
      ? await props.api.put(`${pluginBase.value}/tasks/${task.id}`, task)
      : await props.api.post(`${pluginBase.value}/tasks`, task);
    const detail = unwrapResponse(response);
    editorOpen.value = false;
    selectedTaskId.value = detail?.task?.id || task.id || selectedTaskId.value;
    await loadStatus();
    notify(task.id ? '刷流任务已更新' : '刷流任务已创建');
  } catch (err) {
    notify(err?.message || '保存刷流任务失败', 'error');
  } finally {
    saving.value = false;
  }
}

// 切换当前任务启停状态并立即重建宿主调度。
async function toggleSelectedTask() {
  if (!selectedTask.value) return
  saving.value = true;
  try {
    unwrapResponse(
      await props.api.post(`${pluginBase.value}/tasks/${selectedTaskId.value}/state`, {
        enabled: !selectedTask.value.enabled,
      }),
    );
    await loadStatus();
    notify(selectedTask.value?.enabled ? '刷流任务已启用' : '刷流任务已暂停');
  } catch (err) {
    notify(err?.message || '更新任务状态失败', 'error');
  } finally {
    saving.value = false;
  }
}

// 提交一次刷流刷新或种子检查操作。
async function runOperation(operation) {
  if (!selectedTaskId.value) return
  saving.value = true;
  try {
    const path = operation === 'brush' ? 'run' : 'check';
    unwrapResponse(await props.api.post(`${pluginBase.value}/tasks/${selectedTaskId.value}/${path}`, {}));
    await loadStatus();
    notify(operation === 'brush' ? '刷流刷新已提交' : '种子检查已提交');
  } catch (err) {
    notify(err?.message || '提交任务失败', 'error');
  } finally {
    saving.value = false;
  }
}

// 保存全局插件与侧栏入口开关。
async function saveSettings() {
  saving.value = true;
  try {
    const payload = normalizeSettings(settingsDraft.value);
    status.value = unwrapResponse(await props.api.post(`${pluginBase.value}/settings`, payload));
    settingsMenu.value = false;
    await loadStatus();
    notify('全局设置已保存');
  } catch (err) {
    notify(err?.message || '保存全局设置失败', 'error');
  } finally {
    saving.value = false;
  }
}

// 删除当前没有活跃种子的任务。
async function confirmDeleteTask() {
  saving.value = true;
  try {
    unwrapResponse(await props.api.delete(`${pluginBase.value}/tasks/${selectedTaskId.value}`));
    deleteDialog.value = false;
    selectedTaskId.value = '';
    await loadStatus({ preserveSelection: false });
    notify('刷流任务已删除');
  } catch (err) {
    notify(err?.message || '删除刷流任务失败', 'error');
  } finally {
    saving.value = false;
  }
}

// 清空当前任务的统计、诊断与种子记录。
async function confirmClearTask() {
  saving.value = true;
  try {
    taskDetail.value = unwrapResponse(
      await props.api.post(`${pluginBase.value}/tasks/${selectedTaskId.value}/clear`, {}),
    );
    clearDialog.value = false;
    await loadStatus();
    notify('任务数据已清除');
  } catch (err) {
    notify(err?.message || '清除任务数据失败', 'error');
  } finally {
    saving.value = false;
  }
}

// 切换活跃或已删除种子分页视图。
async function changeTorrentState(value) {
  torrentState.value = value;
  torrentPage.value = 1;
  await loadTaskDetail();
}

// 加载指定页的种子记录。
async function changeTorrentPage(value) {
  torrentPage.value = value;
  await loadTaskDetail();
}

// 根据配置生成当前种子的下一项处理条件摘要。
function torrentPolicy(item) {
  if (item.deleted) return '已删除'
  if (item.hit_and_run && taskConfig.value.hr_seed_time) return `H&R ${taskConfig.value.hr_seed_time} 小时`
  if (taskConfig.value.seed_time) return `${taskConfig.value.seed_time} 小时后检查`
  if (taskConfig.value.seed_ratio) return `分享率 ${taskConfig.value.seed_ratio}`
  return taskConfig.value.proxy_delete ? '动态删种托管' : '等待删除条件'
}

// 返回种子当前下载或做种状态文本。
function torrentStateText(item) {
  const progress = torrentProgress(item);
  if (item.deleted) return '已删除'
  return progress >= 100 ? '做种' : `下载 ${progress}%`
}

// 将站点分享率状态格式化为当前值、无限或暂无数据。
function formatSiteRatio(siteRatio) {
  if (!siteRatio?.available) return '-'
  if (siteRatio.unlimited) return '∞'
  return Number(siteRatio.current || 0).toFixed(2)
}

__mf_22(
  () => props.initialTab,
  value => {
    if (value) activeTab.value = value;
  },
);

__mf_17(async () => {
  await loadStatus({ preserveSelection: false });
  refreshTimer = window.setInterval(() => {
    if (!editorOpen.value && document.visibilityState === 'visible') loadStatus();
  }, 30000);
});

__mf_18(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});

__expose({ loadStatus, refreshAll, loading, saving });

return (_ctx, _cache) => {
  const _component_VIcon = __mf_21("VIcon");
  const _component_VChip = __mf_21("VChip");
  const _component_VBtn = __mf_21("VBtn");
  const _component_VSwitch = __mf_21("VSwitch");
  const _component_VDivider = __mf_21("VDivider");
  const _component_VTextField = __mf_21("VTextField");
  const _component_VCardText = __mf_21("VCardText");
  const _component_VSpacer = __mf_21("VSpacer");
  const _component_VCardActions = __mf_21("VCardActions");
  const _component_VCard = __mf_21("VCard");
  const _component_VMenu = __mf_21("VMenu");
  const _component_VAlert = __mf_21("VAlert");
  const _component_VSkeletonLoader = __mf_21("VSkeletonLoader");
  const _component_VListItem = __mf_21("VListItem");
  const _component_VSelect = __mf_21("VSelect");
  const _component_VSheet = __mf_21("VSheet");
  const _component_VAvatar = __mf_21("VAvatar");
  const _component_VTooltip = __mf_21("VTooltip");
  const _component_VTab = __mf_21("VTab");
  const _component_VTabs = __mf_21("VTabs");
  const _component_VProgressLinear = __mf_21("VProgressLinear");
  const _component_VBtnToggle = __mf_21("VBtnToggle");
  const _component_VDataTable = __mf_21("VDataTable");
  const _component_VPagination = __mf_21("VPagination");
  const _component_VWindowItem = __mf_21("VWindowItem");
  const _component_VWindow = __mf_21("VWindow");
  const _component_VDialog = __mf_21("VDialog");

  return (__mf_19(), __mf_11("div", {
    class: __mf_4(["brushflow-page", { 'brushflow-page--compact': __props.compact }])
  }, [
    __mf_12("header", _hoisted_1, [
      __mf_12("div", _hoisted_2, [
        __mf_14(_component_VIcon, {
          icon: "mdi-sync",
          color: "primary",
          size: "28"
        }),
        _cache[23] || (_cache[23] = __mf_12("div", null, [
          __mf_12("h1", null, "站点刷流"),
          __mf_12("p", null, "多站点任务独立调度与托管")
        ], -1))
      ]),
      __mf_12("div", _hoisted_3, [
        (status.value.summary.task_count)
          ? (__mf_19(), __mf_9(_component_VChip, {
              key: 0,
              size: "small",
              variant: "tonal"
            }, {
              default: __mf_23(() => [
                __mf_13(__mf_6(status.value.summary.running_count ?? status.value.summary.enabled_count ?? 0) + " / " + __mf_6(status.value.summary.task_count) + " 运行 ", 1)
              ]),
              _: 1
            }))
          : __mf_10("", true),
        __mf_14(_component_VMenu, {
          modelValue: settingsMenu.value,
          "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((settingsMenu).value = $event)),
          "close-on-content-click": false,
          location: "bottom end"
        }, {
          activator: __mf_23(({ props: menuProps }) => [
            __mf_14(_component_VBtn, __mf_16(menuProps, {
              icon: "mdi-tune-variant",
              variant: "text",
              "aria-label": "全局设置"
            }), null, 16)
          ]),
          default: __mf_23(() => [
            __mf_14(_component_VCard, {
              class: "brushflow-settings-menu",
              title: "全局设置"
            }, {
              default: __mf_23(() => [
                __mf_14(_component_VCardText, { class: "settings-menu__body" }, {
                  default: __mf_23(() => [
                    __mf_14(_component_VSwitch, {
                      modelValue: settingsDraft.value.enabled,
                      "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((settingsDraft.value.enabled) = $event)),
                      label: "启用插件",
                      color: "primary",
                      "hide-details": "",
                      inset: ""
                    }, null, 8, ["modelValue"]),
                    __mf_14(_component_VSwitch, {
                      modelValue: settingsDraft.value.show_sidebar_nav,
                      "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((settingsDraft.value.show_sidebar_nav) = $event)),
                      label: "显示侧栏入口",
                      color: "primary",
                      "hide-details": "",
                      inset: ""
                    }, null, 8, ["modelValue"]),
                    __mf_14(_component_VDivider),
                    __mf_14(_component_VSwitch, {
                      modelValue: settingsDraft.value.global_proxy_delete,
                      "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((settingsDraft.value.global_proxy_delete) = $event)),
                      label: "全局动态删种",
                      color: "primary",
                      "hide-details": "",
                      inset: ""
                    }, null, 8, ["modelValue"]),
                    (settingsDraft.value.global_proxy_delete)
                      ? (__mf_19(), __mf_9(_component_VTextField, {
                          key: 0,
                          modelValue: settingsDraft.value.global_delete_size_range,
                          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((settingsDraft.value.global_delete_size_range) = $event)),
                          label: "全局动态删种阈值（GB）",
                          placeholder: "50-100",
                          clearable: "",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]))
                      : __mf_10("", true),
                    __mf_14(_component_VDivider),
                    __mf_14(_component_VTextField, {
                      modelValue: settingsDraft.value.global_disksize,
                      "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((settingsDraft.value.global_disksize) = $event)),
                      modelModifiers: { number: true },
                      type: "number",
                      min: "0",
                      label: "全局保种体积（GB）",
                      clearable: "",
                      "hide-details": ""
                    }, null, 8, ["modelValue"]),
                    __mf_14(_component_VTextField, {
                      modelValue: settingsDraft.value.global_maxdlcount,
                      "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((settingsDraft.value.global_maxdlcount) = $event)),
                      modelModifiers: { number: true },
                      type: "number",
                      min: "0",
                      label: "全局同时下载任务数",
                      clearable: "",
                      "hide-details": ""
                    }, null, 8, ["modelValue"]),
                    __mf_14(_component_VTextField, {
                      modelValue: settingsDraft.value.global_maxupspeed,
                      "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((settingsDraft.value.global_maxupspeed) = $event)),
                      modelModifiers: { number: true },
                      type: "number",
                      min: "0",
                      label: "全局总上传带宽（KB/s）",
                      clearable: "",
                      "hide-details": ""
                    }, null, 8, ["modelValue"]),
                    __mf_14(_component_VTextField, {
                      modelValue: settingsDraft.value.global_maxdlspeed,
                      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((settingsDraft.value.global_maxdlspeed) = $event)),
                      modelModifiers: { number: true },
                      type: "number",
                      min: "0",
                      label: "全局总下载带宽（KB/s）",
                      clearable: "",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                __mf_14(_component_VCardActions, null, {
                  default: __mf_23(() => [
                    __mf_14(_component_VSpacer),
                    __mf_14(_component_VBtn, {
                      color: "primary",
                      variant: "flat",
                      loading: saving.value,
                      onClick: saveSettings
                    }, {
                      default: __mf_23(() => [...(_cache[24] || (_cache[24] = [
                        __mf_13("保存", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }, 8, ["modelValue"]),
        (__props.showClose)
          ? (__mf_19(), __mf_9(_component_VBtn, {
              key: 1,
              icon: "mdi-close",
              variant: "text",
              "aria-label": "关闭",
              onClick: _cache[9] || (_cache[9] = $event => (emit('close')))
            }))
          : __mf_10("", true)
      ])
    ]),
    (error.value)
      ? (__mf_19(), __mf_9(_component_VAlert, {
          key: 0,
          type: "error",
          variant: "tonal",
          closable: "",
          "onClick:close": _cache[10] || (_cache[10] = $event => (error.value = ''))
        }, {
          default: __mf_23(() => [
            __mf_13(__mf_6(error.value), 1)
          ]),
          _: 1
        }))
      : __mf_10("", true),
    (!status.value.enabled)
      ? (__mf_19(), __mf_9(_component_VAlert, {
          key: 1,
          type: "warning",
          variant: "tonal"
        }, {
          default: __mf_23(() => [...(_cache[25] || (_cache[25] = [
            __mf_13(" 插件当前未启用，任务配置与历史仍可查看，启用后才会注册刷新和检查服务。 ", -1)
          ]))]),
          _: 1
        }))
      : __mf_10("", true),
    (loading.value && !tasks.value.length)
      ? (__mf_19(), __mf_11("div", _hoisted_4, [
          __mf_14(_component_VSkeletonLoader, { type: "list-item-three-line, list-item-three-line, article" })
        ]))
      : (!tasks.value.length)
        ? (__mf_19(), __mf_11("div", _hoisted_5, [
            __mf_14(_component_VIcon, {
              icon: "mdi-sync-off",
              size: "52",
              color: "medium-emphasis"
            }),
            _cache[27] || (_cache[27] = __mf_12("div", { class: "text-h6" }, "还没有刷流任务", -1)),
            _cache[28] || (_cache[28] = __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "创建任务后可为每个站点分别设置刷新、筛选和删种规则", -1)),
            __mf_14(_component_VBtn, {
              color: "primary",
              variant: "flat",
              "prepend-icon": "mdi-plus",
              onClick: openCreateTask
            }, {
              default: __mf_23(() => [...(_cache[26] || (_cache[26] = [
                __mf_13("创建第一个任务", -1)
              ]))]),
              _: 1
            })
          ]))
        : (__mf_19(), __mf_11(__mf_7, { key: 4 }, [
            __mf_14(_component_VSelect, {
              class: "brushflow-mobile-select",
              "model-value": selectedTaskId.value,
              items: tasks.value,
              "item-title": "name",
              "item-value": "id",
              label: "当前任务",
              "hide-details": "",
              "onUpdate:modelValue": selectTask
            }, {
              item: __mf_23(({ props: itemProps, item }) => [
                __mf_14(_component_VListItem, __mf_16(itemProps, {
                  subtitle: item.raw.site_name
                }), {
                  prepend: __mf_23(() => [
                    __mf_14(_component_VIcon, {
                      icon: __mf_3(taskStateMeta)(item.raw.state).icon,
                      color: __mf_3(taskStateMeta)(item.raw.state).color
                    }, null, 8, ["icon", "color"])
                  ]),
                  _: 2
                }, 1040, ["subtitle"])
              ]),
              _: 1
            }, 8, ["model-value", "items"]),
            __mf_12("div", _hoisted_6, [
              __mf_14(_component_VSheet, {
                tag: "aside",
                class: "brushflow-task-rail app-surface-static"
              }, {
                default: __mf_23(() => [
                  __mf_12("div", _hoisted_7, [
                    _cache[29] || (_cache[29] = __mf_12("span", { class: "text-subtitle-2" }, "刷流任务", -1)),
                    __mf_14(_component_VChip, {
                      size: "x-small",
                      variant: "tonal"
                    }, {
                      default: __mf_23(() => [
                        __mf_13(__mf_6(tasks.value.length), 1)
                      ]),
                      _: 1
                    })
                  ]),
                  __mf_12("div", _hoisted_8, [
                    (__mf_19(true), __mf_11(__mf_7, null, __mf_20(tasks.value, (task) => {
                      return (__mf_19(), __mf_11("button", {
                        key: task.id,
                        type: "button",
                        class: __mf_4(["brushflow-task-item", { 'brushflow-task-item--selected': task.id === selectedTaskId.value }]),
                        "aria-pressed": task.id === selectedTaskId.value,
                        onClick: $event => (selectTask(task.id))
                      }, [
                        __mf_12("span", _hoisted_10, [
                          __mf_12("strong", null, __mf_6(task.name), 1),
                          __mf_12("span", {
                            class: __mf_4(["brushflow-status-dot", `brushflow-status-dot--${__mf_3(taskStateMeta)(task.state).color}`])
                          }, null, 2)
                        ]),
                        __mf_12("span", null, __mf_6(task.site_name) + " · " + __mf_6(task.downloader), 1),
                        __mf_12("span", _hoisted_11, [
                          __mf_12("span", null, __mf_6(task.statistic.active || 0) + " 个种子", 1),
                          __mf_12("span", null, __mf_6(task.next_run_at ? __mf_3(formatDateTime)(task.next_run_at) : '暂无计划'), 1)
                        ])
                      ], 10, _hoisted_9))
                    }), 128))
                  ]),
                  __mf_14(_component_VBtn, {
                    class: "brushflow-create-task",
                    block: "",
                    variant: "tonal",
                    "prepend-icon": "mdi-plus",
                    onClick: openCreateTask
                  }, {
                    default: __mf_23(() => [...(_cache[30] || (_cache[30] = [
                      __mf_13(" 新建任务 ", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              (selectedTask.value)
                ? (__mf_19(), __mf_11("main", _hoisted_12, [
                    __mf_12("section", _hoisted_13, [
                      __mf_12("div", _hoisted_14, [
                        __mf_14(_component_VAvatar, {
                          color: "primary",
                          variant: "tonal",
                          rounded: "",
                          size: "42"
                        }, {
                          default: __mf_23(() => [
                            __mf_14(_component_VIcon, { icon: "mdi-web" })
                          ]),
                          _: 1
                        }),
                        __mf_12("div", null, [
                          __mf_12("div", _hoisted_15, [
                            __mf_12("h2", null, __mf_6(selectedTask.value.name), 1),
                            __mf_14(_component_VChip, {
                              color: selectedState.value.color,
                              size: "small",
                              variant: "tonal",
                              "prepend-icon": selectedState.value.icon
                            }, {
                              default: __mf_23(() => [
                                __mf_13(__mf_6(selectedState.value.text), 1)
                              ]),
                              _: 1
                            }, 8, ["color", "prepend-icon"])
                          ]),
                          __mf_12("p", null, __mf_6(selectedTask.value.site_name) + " · 最近 " + __mf_6(selectedTask.value.last_run ? __mf_3(formatDateTime)(selectedTask.value.last_run.started_at) : '尚未运行') + " · 下次 " + __mf_6(selectedTask.value.next_run_at ? __mf_3(formatDateTime)(selectedTask.value.next_run_at) : '暂无计划'), 1)
                        ])
                      ]),
                      __mf_12("div", _hoisted_16, [
                        __mf_14(_component_VTooltip, { text: "立即刷新" }, {
                          activator: __mf_23(({ props: tipProps }) => [
                            __mf_14(_component_VBtn, __mf_16(tipProps, {
                              icon: "mdi-sync",
                              variant: "text",
                              loading: selectedTask.value.operation === 'brush',
                              onClick: _cache[11] || (_cache[11] = $event => (runOperation('brush')))
                            }), null, 16, ["loading"])
                          ]),
                          _: 1
                        }),
                        __mf_14(_component_VTooltip, { text: "检查种子" }, {
                          activator: __mf_23(({ props: tipProps }) => [
                            __mf_14(_component_VBtn, __mf_16(tipProps, {
                              icon: "mdi-progress-check",
                              variant: "text",
                              loading: selectedTask.value.operation === 'check',
                              onClick: _cache[12] || (_cache[12] = $event => (runOperation('check')))
                            }), null, 16, ["loading"])
                          ]),
                          _: 1
                        }),
                        __mf_14(_component_VTooltip, {
                          text: selectedTask.value.enabled ? '暂停任务' : '启用任务'
                        }, {
                          activator: __mf_23(({ props: tipProps }) => [
                            __mf_14(_component_VBtn, __mf_16(tipProps, {
                              icon: selectedTask.value.enabled ? 'mdi-pause' : 'mdi-play',
                              variant: "text",
                              onClick: toggleSelectedTask
                            }), null, 16, ["icon"])
                          ]),
                          _: 1
                        }, 8, ["text"]),
                        __mf_14(_component_VTooltip, { text: "编辑任务" }, {
                          activator: __mf_23(({ props: tipProps }) => [
                            __mf_14(_component_VBtn, __mf_16(tipProps, {
                              icon: "mdi-pencil-outline",
                              variant: "text",
                              onClick: openEditTask
                            }), null, 16)
                          ]),
                          _: 1
                        })
                      ])
                    ]),
                    __mf_14(_component_VTabs, {
                      modelValue: activeTab.value,
                      "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((activeTab).value = $event)),
                      color: "primary",
                      class: "brushflow-tabs"
                    }, {
                      default: __mf_23(() => [
                        __mf_14(_component_VTab, { value: "overview" }, {
                          default: __mf_23(() => [...(_cache[31] || (_cache[31] = [
                            __mf_13("任务概览", -1)
                          ]))]),
                          _: 1
                        }),
                        __mf_14(_component_VTab, { value: "diagnostics" }, {
                          default: __mf_23(() => [...(_cache[32] || (_cache[32] = [
                            __mf_13("运行诊断", -1)
                          ]))]),
                          _: 1
                        }),
                        __mf_14(_component_VTab, { value: "config" }, {
                          default: __mf_23(() => [...(_cache[33] || (_cache[33] = [
                            __mf_13("任务配置", -1)
                          ]))]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }, 8, ["modelValue"]),
                    __mf_14(_component_VDivider),
                    __mf_14(_component_VWindow, {
                      modelValue: activeTab.value,
                      "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((activeTab).value = $event)),
                      touch: false,
                      class: "brushflow-window"
                    }, {
                      default: __mf_23(() => [
                        __mf_14(_component_VWindowItem, { value: "overview" }, {
                          default: __mf_23(() => [
                            __mf_12("div", _hoisted_17, [
                              __mf_14(_component_VSheet, { class: "brushflow-stat app-surface-static" }, {
                                default: __mf_23(() => [
                                  _cache[34] || (_cache[34] = __mf_12("span", null, "活跃种子", -1)),
                                  __mf_12("strong", null, __mf_6(selectedTask.value.statistic.active || 0), 1),
                                  __mf_12("small", null, __mf_6(selectedTask.value.statistic.unarchived || 0) + " 个待归档", 1)
                                ]),
                                _: 1
                              }),
                              __mf_14(_component_VSheet, { class: "brushflow-stat app-surface-static" }, {
                                default: __mf_23(() => [
                                  _cache[35] || (_cache[35] = __mf_12("span", null, "累计上传 / 下载", -1)),
                                  __mf_12("strong", null, __mf_6(__mf_3(formatBytes)(selectedTask.value.statistic.uploaded)) + " / " + __mf_6(__mf_3(formatBytes)(selectedTask.value.statistic.downloaded)), 1),
                                  _cache[36] || (_cache[36] = __mf_12("small", null, "当前任务累计", -1))
                                ]),
                                _: 1
                              }),
                              __mf_14(_component_VSheet, { class: "brushflow-stat app-surface-static" }, {
                                default: __mf_23(() => [
                                  _cache[37] || (_cache[37] = __mf_12("span", null, "当前做种", -1)),
                                  __mf_12("strong", null, __mf_6(__mf_3(formatBytes)(selectedTask.value.seeding_size)), 1),
                                  __mf_12("small", null, __mf_6(taskConfig.value.disksize ? `上限 ${taskConfig.value.disksize} GB` : '未设置体积上限'), 1),
                                  (taskConfig.value.disksize)
                                    ? (__mf_19(), __mf_9(_component_VProgressLinear, {
                                        key: 0,
                                        "model-value": seedingPercent.value,
                                        height: "4",
                                        color: "primary"
                                      }, null, 8, ["model-value"]))
                                    : __mf_10("", true)
                                ]),
                                _: 1
                              }),
                              __mf_14(_component_VSheet, { class: "brushflow-stat app-surface-static" }, {
                                default: __mf_23(() => [
                                  __mf_12("span", null, __mf_6(taskConfig.value.site_ratio_control ? '站点分享率' : '最近刷新'), 1),
                                  __mf_12("strong", null, __mf_6(taskConfig.value.site_ratio_control ? formatSiteRatio(selectedTask.value.site_ratio) : latestBrushRun.value ? `${latestBrushRun.value.added_count || 0} / ${latestBrushRun.value.source_count || 0}` : '-'), 1),
                                  (taskConfig.value.site_ratio_control)
                                    ? (__mf_19(), __mf_11("small", _hoisted_18, __mf_6(selectedTask.value.site_ratio?.available ? `目标 ${Number(taskConfig.value.site_ratio_target || 0).toFixed(2)}` : '暂无站点统计数据'), 1))
                                    : (__mf_19(), __mf_11("small", _hoisted_19, "新增 / 候选"))
                                ]),
                                _: 1
                              })
                            ]),
                            __mf_12("div", _hoisted_20, [
                              __mf_14(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: __mf_23(() => [
                                  __mf_12("header", _hoisted_21, [
                                    _cache[38] || (_cache[38] = __mf_12("div", null, [
                                      __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "运行状态"),
                                      __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "当前任务调度与核心策略")
                                    ], -1)),
                                    __mf_14(_component_VChip, {
                                      color: selectedState.value.color,
                                      size: "small",
                                      variant: "tonal"
                                    }, {
                                      default: __mf_23(() => [
                                        __mf_13(__mf_6(selectedState.value.text), 1)
                                      ]),
                                      _: 1
                                    }, 8, ["color"])
                                  ]),
                                  __mf_12("dl", _hoisted_22, [
                                    __mf_12("div", null, [
                                      _cache[39] || (_cache[39] = __mf_12("dt", null, "刷新周期", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.cron || `每 ${selectedTask.value.brush_interval} 分钟`), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[40] || (_cache[40] = __mf_12("dt", null, "检查周期", -1)),
                                      __mf_12("dd", null, "每 " + __mf_6(selectedTask.value.check_interval) + " 分钟", 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[41] || (_cache[41] = __mf_12("dt", null, "开启时段", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.active_time_range || '全天'), 1)
                                    ]),
                                    (taskConfig.value.site_ratio_control)
                                      ? (__mf_19(), __mf_11("div", _hoisted_23, [
                                          _cache[42] || (_cache[42] = __mf_12("dt", null, "站点分享率", -1)),
                                          __mf_12("dd", null, __mf_6(formatSiteRatio(selectedTask.value.site_ratio)) + " / " + __mf_6(Number(taskConfig.value.site_ratio_target || 0).toFixed(2)), 1)
                                        ]))
                                      : __mf_10("", true),
                                    __mf_12("div", null, [
                                      _cache[43] || (_cache[43] = __mf_12("dt", null, "选种来源", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.rss_support ? 'RSS' : '站点列表页'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[44] || (_cache[44] = __mf_12("dt", null, "促销要求", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.freeleech === '2xfree' ? '2X 免费' : taskConfig.value.freeleech === 'free' ? '免费' : '全部'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[45] || (_cache[45] = __mf_12("dt", null, "删种策略", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.proxy_delete ? `动态 ${taskConfig.value.delete_size_range || '-' } GB` : '满足任一条件'), 1)
                                    ])
                                  ])
                                ]),
                                _: 1
                              }),
                              __mf_14(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: __mf_23(() => [
                                  __mf_12("header", _hoisted_24, [
                                    __mf_12("div", null, [
                                      _cache[46] || (_cache[46] = __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "最近一次刷新", -1)),
                                      __mf_12("div", _hoisted_25, __mf_6(latestBrushRun.value ? `${__mf_3(formatDateTime)(latestBrushRun.value.started_at)} · ${__mf_3(formatDuration)(latestBrushRun.value.started_at, latestBrushRun.value.finished_at)}` : '暂无运行记录'), 1)
                                    ]),
                                    (latestBrushRun.value)
                                      ? (__mf_19(), __mf_9(_component_VChip, {
                                          key: 0,
                                          color: latestBrushRun.value.success === false ? 'error' : 'success',
                                          size: "small",
                                          variant: "tonal"
                                        }, {
                                          default: __mf_23(() => [
                                            __mf_13(__mf_6(latestBrushRun.value.success === false ? '失败' : '完成'), 1)
                                          ]),
                                          _: 1
                                        }, 8, ["color"]))
                                      : __mf_10("", true)
                                  ]),
                                  __mf_12("div", _hoisted_26, [
                                    __mf_12("div", null, [
                                      _cache[47] || (_cache[47] = __mf_12("span", null, "站点候选", -1)),
                                      __mf_12("strong", null, __mf_6(latestBrushRun.value?.source_count || 0), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[48] || (_cache[48] = __mf_12("span", null, "规则过滤", -1)),
                                      __mf_12("strong", null, __mf_6(latestBrushRun.value?.filtered_count || 0), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[49] || (_cache[49] = __mf_12("span", null, "新增下载", -1)),
                                      __mf_12("strong", null, __mf_6(latestBrushRun.value?.added_count || 0), 1)
                                    ])
                                  ]),
                                  (latestBrushRun.value?.error)
                                    ? (__mf_19(), __mf_9(_component_VAlert, {
                                        key: 0,
                                        type: "error",
                                        variant: "tonal",
                                        density: "compact"
                                      }, {
                                        default: __mf_23(() => [
                                          __mf_13(__mf_6(latestBrushRun.value.error), 1)
                                        ]),
                                        _: 1
                                      }))
                                    : __mf_10("", true),
                                  __mf_14(_component_VBtn, {
                                    variant: "text",
                                    color: "primary",
                                    "append-icon": "mdi-arrow-right",
                                    onClick: _cache[14] || (_cache[14] = $event => (activeTab.value = 'diagnostics'))
                                  }, {
                                    default: __mf_23(() => [...(_cache[50] || (_cache[50] = [
                                      __mf_13(" 查看运行诊断 ", -1)
                                    ]))]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              })
                            ]),
                            __mf_14(_component_VSheet, {
                              tag: "section",
                              class: "brushflow-panel brushflow-torrents app-surface-static"
                            }, {
                              default: __mf_23(() => [
                                __mf_12("header", _hoisted_27, [
                                  __mf_12("div", null, [
                                    __mf_12("div", _hoisted_28, [
                                      _cache[51] || (_cache[51] = __mf_12("span", { class: "text-subtitle-1 font-weight-medium" }, "托管种子", -1)),
                                      __mf_14(_component_VChip, {
                                        size: "x-small",
                                        variant: "tonal"
                                      }, {
                                        default: __mf_23(() => [
                                          __mf_13(__mf_6(torrentData.value.total), 1)
                                        ]),
                                        _: 1
                                      })
                                    ]),
                                    _cache[52] || (_cache[52] = __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "当前任务独立记录", -1))
                                  ]),
                                  __mf_14(_component_VBtnToggle, {
                                    "model-value": torrentState.value,
                                    mandatory: "",
                                    color: "primary",
                                    density: "compact",
                                    "onUpdate:modelValue": changeTorrentState
                                  }, {
                                    default: __mf_23(() => [
                                      __mf_14(_component_VBtn, { value: "active" }, {
                                        default: __mf_23(() => [...(_cache[53] || (_cache[53] = [
                                          __mf_13("活跃", -1)
                                        ]))]),
                                        _: 1
                                      }),
                                      __mf_14(_component_VBtn, { value: "deleted" }, {
                                        default: __mf_23(() => [...(_cache[54] || (_cache[54] = [
                                          __mf_13("已删除", -1)
                                        ]))]),
                                        _: 1
                                      }),
                                      __mf_14(_component_VBtn, { value: "all" }, {
                                        default: __mf_23(() => [...(_cache[55] || (_cache[55] = [
                                          __mf_13("全部", -1)
                                        ]))]),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  }, 8, ["model-value"])
                                ]),
                                __mf_14(_component_VDataTable, {
                                  class: "brushflow-torrent-table",
                                  headers: torrentHeaders,
                                  items: torrentData.value.items,
                                  loading: taskLoading.value,
                                  "items-per-page": -1,
                                  "hide-default-footer": "",
                                  density: "comfortable"
                                }, {
                                  "item.title": __mf_23(({ item }) => [
                                    __mf_12("div", _hoisted_29, [
                                      __mf_12("strong", null, __mf_6(item.title || '未知种子'), 1),
                                      __mf_12("span", null, __mf_6(item.site_name) + " · " + __mf_6(__mf_3(formatDateTime)((item.time || 0) * 1000)), 1)
                                    ])
                                  ]),
                                  "item.status": __mf_23(({ item }) => [
                                    __mf_14(_component_VChip, {
                                      size: "small",
                                      color: item.deleted ? 'secondary' : __mf_3(torrentProgress)(item) >= 100 ? 'success' : 'info',
                                      variant: "tonal"
                                    }, {
                                      default: __mf_23(() => [
                                        __mf_13(__mf_6(torrentStateText(item)), 1)
                                      ]),
                                      _: 2
                                    }, 1032, ["color"])
                                  ]),
                                  "item.size": __mf_23(({ item }) => [
                                    __mf_13(__mf_6(__mf_3(formatBytes)(item.size)), 1)
                                  ]),
                                  "item.uploaded": __mf_23(({ item }) => [
                                    __mf_13(__mf_6(__mf_3(formatBytes)(item.uploaded)), 1)
                                  ]),
                                  "item.ratio": __mf_23(({ item }) => [
                                    __mf_13(__mf_6(Number(item.ratio || 0).toFixed(2)), 1)
                                  ]),
                                  "item.policy": __mf_23(({ item }) => [
                                    __mf_13(__mf_6(torrentPolicy(item)), 1)
                                  ]),
                                  "no-data": __mf_23(() => [...(_cache[56] || (_cache[56] = [
                                    __mf_12("div", { class: "brushflow-table-empty" }, "当前筛选下没有种子记录", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["items", "loading"]),
                                __mf_12("div", _hoisted_30, [
                                  (__mf_19(true), __mf_11(__mf_7, null, __mf_20(torrentData.value.items, (item) => {
                                    return (__mf_19(), __mf_11("article", {
                                      key: `${item.task_id}-${item.title}-${item.time}`,
                                      class: "brushflow-mobile-torrent"
                                    }, [
                                      __mf_12("div", _hoisted_31, [
                                        __mf_12("strong", null, __mf_6(item.title || '未知种子'), 1),
                                        __mf_14(_component_VChip, {
                                          size: "x-small",
                                          variant: "tonal"
                                        }, {
                                          default: __mf_23(() => [
                                            __mf_13(__mf_6(torrentStateText(item)), 1)
                                          ]),
                                          _: 2
                                        }, 1024)
                                      ]),
                                      __mf_12("div", _hoisted_32, [
                                        __mf_12("span", null, __mf_6(__mf_3(formatBytes)(item.size)), 1),
                                        __mf_12("span", null, "上传 " + __mf_6(__mf_3(formatBytes)(item.uploaded)), 1),
                                        __mf_12("span", null, "分享率 " + __mf_6(Number(item.ratio || 0).toFixed(2)), 1)
                                      ]),
                                      __mf_12("div", _hoisted_33, __mf_6(torrentPolicy(item)), 1)
                                    ]))
                                  }), 128)),
                                  (!torrentData.value.items.length)
                                    ? (__mf_19(), __mf_11("div", _hoisted_34, "当前筛选下没有种子记录"))
                                    : __mf_10("", true)
                                ]),
                                (totalTorrentPages.value > 1)
                                  ? (__mf_19(), __mf_9(_component_VPagination, {
                                      key: 0,
                                      "model-value": torrentPage.value,
                                      length: totalTorrentPages.value,
                                      "total-visible": 5,
                                      density: "comfortable",
                                      "onUpdate:modelValue": changeTorrentPage
                                    }, null, 8, ["model-value", "length"]))
                                  : __mf_10("", true)
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }),
                        __mf_14(_component_VWindowItem, { value: "diagnostics" }, {
                          default: __mf_23(() => [
                            __mf_12("div", _hoisted_35, [
                              __mf_12("div", null, [
                                __mf_12("div", _hoisted_36, __mf_6(latestBrushRun.value ? `刷流刷新 #${latestBrushRun.value.id.slice(0, 8)}` : '暂无刷流刷新记录'), 1),
                                __mf_12("div", _hoisted_37, __mf_6(latestBrushRun.value ? `${__mf_3(formatDateTime)(latestBrushRun.value.started_at)} · ${__mf_3(formatDuration)(latestBrushRun.value.started_at, latestBrushRun.value.finished_at)}` : '执行一次任务后将显示筛选流水线和过滤原因'), 1)
                              ]),
                              (latestBrushRun.value)
                                ? (__mf_19(), __mf_9(_component_VChip, {
                                    key: 0,
                                    color: latestBrushRun.value.success === false ? 'error' : 'success',
                                    variant: "tonal"
                                  }, {
                                    default: __mf_23(() => [
                                      __mf_13(__mf_6(latestBrushRun.value.success === false ? '失败' : '完成'), 1)
                                    ]),
                                    _: 1
                                  }, 8, ["color"]))
                                : __mf_10("", true)
                            ]),
                            __mf_12("div", _hoisted_38, [
                              __mf_14(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: __mf_23(() => [
                                  _cache[57] || (_cache[57] = __mf_12("header", { class: "brushflow-panel__head" }, [
                                    __mf_12("div", null, [
                                      __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "选种流水线"),
                                      __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "本轮候选在各阶段的剩余数量")
                                    ])
                                  ], -1)),
                                  __mf_12("ol", _hoisted_39, [
                                    (__mf_19(true), __mf_11(__mf_7, null, __mf_20(pipelineStages.value, (stage, index) => {
                                      return (__mf_19(), __mf_11("li", {
                                        key: stage.title
                                      }, [
                                        __mf_12("span", _hoisted_40, __mf_6(index + 1), 1),
                                        __mf_12("div", null, [
                                          __mf_12("strong", null, __mf_6(stage.title), 1),
                                          __mf_12("span", null, __mf_6(stage.detail), 1)
                                        ]),
                                        __mf_14(_component_VChip, {
                                          size: "small",
                                          variant: "tonal"
                                        }, {
                                          default: __mf_23(() => [
                                            __mf_13(__mf_6(stage.count), 1)
                                          ]),
                                          _: 2
                                        }, 1024)
                                      ]))
                                    }), 128))
                                  ])
                                ]),
                                _: 1
                              }),
                              __mf_14(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: __mf_23(() => [
                                  _cache[58] || (_cache[58] = __mf_12("header", { class: "brushflow-panel__head" }, [
                                    __mf_12("div", null, [
                                      __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "过滤原因"),
                                      __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "本轮未进入下载器的候选分布")
                                    ])
                                  ], -1)),
                                  (reasonEntries.value.length)
                                    ? (__mf_19(), __mf_11("div", _hoisted_41, [
                                        (__mf_19(true), __mf_11(__mf_7, null, __mf_20(reasonEntries.value, (item) => {
                                          return (__mf_19(), __mf_11("div", {
                                            key: item.label,
                                            class: "brushflow-reason"
                                          }, [
                                            __mf_12("div", null, [
                                              __mf_12("span", null, __mf_6(item.label), 1),
                                              __mf_12("strong", null, __mf_6(item.count), 1)
                                            ]),
                                            __mf_12("span", _hoisted_42, [
                                              __mf_12("i", {
                                                style: __mf_5({ width: `${(item.count / maxReasonCount.value) * 100}%` })
                                              }, null, 4)
                                            ])
                                          ]))
                                        }), 128))
                                      ]))
                                    : (__mf_19(), __mf_11("div", _hoisted_43, "本轮没有记录过滤原因"))
                                ]),
                                _: 1
                              })
                            ]),
                            __mf_14(_component_VSheet, {
                              tag: "section",
                              class: "brushflow-panel app-surface-static"
                            }, {
                              default: __mf_23(() => [
                                _cache[59] || (_cache[59] = __mf_12("header", { class: "brushflow-panel__head" }, [
                                  __mf_12("div", null, [
                                    __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "最近事件"),
                                    __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "刷流刷新与种子检查独立记录")
                                  ])
                                ], -1)),
                                __mf_12("div", _hoisted_44, [
                                  (__mf_19(true), __mf_11(__mf_7, null, __mf_20(taskRuns.value, (run) => {
                                    return (__mf_19(), __mf_11("article", {
                                      key: run.id
                                    }, [
                                      __mf_14(_component_VIcon, {
                                        icon: run.success === false ? 'mdi-alert-circle-outline' : run.kind === 'brush' ? 'mdi-sync' : 'mdi-progress-check',
                                        color: run.success === false ? 'error' : run.kind === 'brush' ? 'primary' : 'info'
                                      }, null, 8, ["icon", "color"]),
                                      __mf_12("div", null, [
                                        __mf_12("strong", null, __mf_6(run.kind === 'brush' ? '刷流刷新' : '种子检查'), 1),
                                        __mf_12("span", null, __mf_6(__mf_3(formatDateTime)(run.started_at)) + " · " + __mf_6(__mf_3(formatDuration)(run.started_at, run.finished_at)) + " · " + __mf_6(run.kind === 'brush' ? `新增 ${run.added_count || 0}，过滤 ${run.filtered_count || 0}` : `活跃 ${run.active_count || 0}，删除 ${run.deleted_count || 0}`), 1),
                                        (run.error)
                                          ? (__mf_19(), __mf_11("span", _hoisted_45, __mf_6(run.error), 1))
                                          : __mf_10("", true)
                                      ])
                                    ]))
                                  }), 128)),
                                  (!taskRuns.value.length)
                                    ? (__mf_19(), __mf_11("div", _hoisted_46, "暂无运行事件"))
                                    : __mf_10("", true)
                                ])
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }),
                        __mf_14(_component_VWindowItem, { value: "config" }, {
                          default: __mf_23(() => [
                            __mf_12("div", _hoisted_47, [
                              __mf_14(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: __mf_23(() => [
                                  _cache[73] || (_cache[73] = __mf_12("header", { class: "brushflow-panel__head" }, [
                                    __mf_12("div", null, [
                                      __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "任务规则"),
                                      __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "当前服务端生效配置")
                                    ])
                                  ], -1)),
                                  __mf_12("dl", _hoisted_48, [
                                    __mf_12("div", null, [
                                      _cache[60] || (_cache[60] = __mf_12("dt", null, "任务状态", -1)),
                                      __mf_12("dd", null, __mf_6(selectedTask.value.enabled ? '启用' : '暂停'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[61] || (_cache[61] = __mf_12("dt", null, "通知", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.notify ? '发送' : '关闭'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[62] || (_cache[62] = __mf_12("dt", null, "站点", -1)),
                                      __mf_12("dd", null, __mf_6(selectedTask.value.site_name), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[63] || (_cache[63] = __mf_12("dt", null, "下载器", -1)),
                                      __mf_12("dd", null, __mf_6(selectedTask.value.downloader), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[64] || (_cache[64] = __mf_12("dt", null, "种子大小", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.size || '不限'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[65] || (_cache[65] = __mf_12("dt", null, "做种人数", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.seeder || '不限'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[66] || (_cache[66] = __mf_12("dt", null, "发布时间", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.pubtime ? `${taskConfig.value.pubtime} 分钟` : '不限'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[67] || (_cache[67] = __mf_12("dt", null, "排除 H&R", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.hr === 'yes' ? '是' : '否'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[68] || (_cache[68] = __mf_12("dt", null, "包含规则", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.include || '无'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[69] || (_cache[69] = __mf_12("dt", null, "排除规则", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.exclude || '无'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[70] || (_cache[70] = __mf_12("dt", null, "保种上限", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.disksize ? `${taskConfig.value.disksize} GB` : '不限'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[71] || (_cache[71] = __mf_12("dt", null, "目标分享率", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.site_ratio_control ? Number(taskConfig.value.site_ratio_target || 0).toFixed(2) : '关闭'), 1)
                                    ]),
                                    __mf_12("div", null, [
                                      _cache[72] || (_cache[72] = __mf_12("dt", null, "归档天数", -1)),
                                      __mf_12("dd", null, __mf_6(taskConfig.value.auto_archive_days || '不自动归档'), 1)
                                    ])
                                  ])
                                ]),
                                _: 1
                              }),
                              __mf_14(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: __mf_23(() => [
                                  _cache[80] || (_cache[80] = __mf_12("header", { class: "brushflow-panel__head" }, [
                                    __mf_12("div", null, [
                                      __mf_12("div", { class: "text-subtitle-1 font-weight-medium" }, "任务数据"),
                                      __mf_12("div", { class: "text-body-2 text-medium-emphasis" }, "以下操作只影响当前任务")
                                    ])
                                  ], -1)),
                                  __mf_12("div", _hoisted_49, [
                                    __mf_12("div", null, [
                                      _cache[75] || (_cache[75] = __mf_12("strong", null, "清除统计与记录", -1)),
                                      _cache[76] || (_cache[76] = __mf_12("span", null, "下载器中的任务标签种子会在下次检查时重新纳入", -1)),
                                      __mf_14(_component_VBtn, {
                                        color: "warning",
                                        variant: "tonal",
                                        "prepend-icon": "mdi-eraser",
                                        onClick: _cache[15] || (_cache[15] = $event => (clearDialog.value = true))
                                      }, {
                                        default: __mf_23(() => [...(_cache[74] || (_cache[74] = [
                                          __mf_13("清除数据", -1)
                                        ]))]),
                                        _: 1
                                      })
                                    ]),
                                    __mf_14(_component_VDivider),
                                    __mf_12("div", null, [
                                      _cache[78] || (_cache[78] = __mf_12("strong", null, "删除任务", -1)),
                                      _cache[79] || (_cache[79] = __mf_12("span", null, "存在活跃种子时后端会拒绝删除，避免留下失管任务", -1)),
                                      __mf_14(_component_VBtn, {
                                        color: "error",
                                        variant: "tonal",
                                        "prepend-icon": "mdi-delete-outline",
                                        onClick: _cache[16] || (_cache[16] = $event => (deleteDialog.value = true))
                                      }, {
                                        default: __mf_23(() => [...(_cache[77] || (_cache[77] = [
                                          __mf_13("删除任务", -1)
                                        ]))]),
                                        _: 1
                                      })
                                    ])
                                  ])
                                ]),
                                _: 1
                              })
                            ])
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }, 8, ["modelValue"])
                  ]))
                : __mf_10("", true)
            ])
          ], 64)),
    __mf_14(TaskEditorDialog, {
      modelValue: editorOpen.value,
      "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((editorOpen).value = $event)),
      task: editorTask.value,
      sites: status.value.options.sites,
      downloaders: status.value.options.downloaders,
      "global-dynamic-delete": Boolean(status.value.global_proxy_delete),
      saving: saving.value,
      onSave: saveTask
    }, null, 8, ["modelValue", "task", "sites", "downloaders", "global-dynamic-delete", "saving"]),
    __mf_14(_component_VDialog, {
      modelValue: deleteDialog.value,
      "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((deleteDialog).value = $event)),
      "max-width": "28rem"
    }, {
      default: __mf_23(() => [
        __mf_14(_component_VCard, { title: "删除刷流任务" }, {
          default: __mf_23(() => [
            __mf_14(_component_VCardText, null, {
              default: __mf_23(() => [
                __mf_13("确认删除“" + __mf_6(selectedTask.value?.name) + "”？存在活跃种子时不会执行删除。", 1)
              ]),
              _: 1
            }),
            __mf_14(_component_VCardActions, null, {
              default: __mf_23(() => [
                __mf_14(_component_VSpacer),
                __mf_14(_component_VBtn, {
                  variant: "text",
                  onClick: _cache[19] || (_cache[19] = $event => (deleteDialog.value = false))
                }, {
                  default: __mf_23(() => [...(_cache[81] || (_cache[81] = [
                    __mf_13("取消", -1)
                  ]))]),
                  _: 1
                }),
                __mf_14(_component_VBtn, {
                  color: "error",
                  variant: "flat",
                  loading: saving.value,
                  onClick: confirmDeleteTask
                }, {
                  default: __mf_23(() => [...(_cache[82] || (_cache[82] = [
                    __mf_13("删除", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    __mf_14(_component_VDialog, {
      modelValue: clearDialog.value,
      "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((clearDialog).value = $event)),
      "max-width": "28rem"
    }, {
      default: __mf_23(() => [
        __mf_14(_component_VCard, { title: "清除任务数据" }, {
          default: __mf_23(() => [
            __mf_14(_component_VCardText, null, {
              default: __mf_23(() => [...(_cache[83] || (_cache[83] = [
                __mf_13("将清除当前任务的统计、运行诊断、托管和归档记录，下载器内的种子与文件不会删除。", -1)
              ]))]),
              _: 1
            }),
            __mf_14(_component_VCardActions, null, {
              default: __mf_23(() => [
                __mf_14(_component_VSpacer),
                __mf_14(_component_VBtn, {
                  variant: "text",
                  onClick: _cache[21] || (_cache[21] = $event => (clearDialog.value = false))
                }, {
                  default: __mf_23(() => [...(_cache[84] || (_cache[84] = [
                    __mf_13("取消", -1)
                  ]))]),
                  _: 1
                }),
                __mf_14(_component_VBtn, {
                  color: "warning",
                  variant: "flat",
                  loading: saving.value,
                  onClick: confirmClearTask
                }, {
                  default: __mf_23(() => [...(_cache[85] || (_cache[85] = [
                    __mf_13("清除", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"])
  ], 2))
}
}

};
const BrushFlowWorkbench = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-19d98e0f"]]);

export { BrushFlowWorkbench as B };
