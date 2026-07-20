import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc, c as cloneTask, n as normalizeTask, t as taskStateMeta, a as formatDateTime, f as formatBytes, b as formatDuration, d as torrentProgress, u as unwrapResponse } from './_plugin-vue_export-helper-DCw9fEh_.js';

const {unref:_unref$1,toDisplayString:_toDisplayString$1,createTextVNode:_createTextVNode$1,resolveComponent:_resolveComponent$1,withCtx:_withCtx$1,createVNode:_createVNode$1,createElementVNode:_createElementVNode$1,openBlock:_openBlock$1,createBlock:_createBlock$1,createCommentVNode:_createCommentVNode$1,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1$1 = { class: "editor-section" };
const _hoisted_2$1 = { class: "editor-section__head" };
const _hoisted_3$1 = { class: "editor-switches" };
const _hoisted_4$1 = { class: "editor-section" };
const _hoisted_5$1 = { class: "editor-section" };
const _hoisted_6$1 = { class: "editor-switches" };
const _hoisted_7$1 = { class: "editor-section" };
const _hoisted_8$1 = { class: "editor-section" };
const _hoisted_9$1 = { class: "editor-section" };
const _hoisted_10$1 = { class: "editor-section" };
const _hoisted_11$1 = { class: "editor-section" };
const _hoisted_12$1 = { class: "editor-section" };
const _hoisted_13$1 = { class: "editor-switches" };

const {computed: computed$1,ref: ref$1,watch: watch$1} = await importShared('vue');

const {useDisplay} = await importShared('vuetify');


const _sfc_main$1 = {
  __name: 'TaskEditorDialog',
  props: {
  modelValue: { type: Boolean, default: false },
  task: { type: Object, default: () => ({}) },
  sites: { type: Array, default: () => [] },
  downloaders: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
},
  emits: ['update:modelValue', 'save'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;
const display = useDisplay();
const formRef = ref$1(null);
const activeTab = ref$1('base');
const localTask = ref$1(cloneTask());

const dialogTitle = computed$1(() => (localTask.value.id ? '编辑刷流任务' : '新建刷流任务'));
const siteName = computed$1(() => props.sites.find(item => item.value === Number(localTask.value.site_id))?.title || '未选择');
const scheduleText = computed$1(() => localTask.value.cron || `每 ${localTask.value.brush_interval || 10} 分钟`);

// 每次打开弹窗都从服务端任务快照重新创建本地草稿。
watch$1(
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
  const _component_VToolbarTitle = _resolveComponent$1("VToolbarTitle");
  const _component_VSpacer = _resolveComponent$1("VSpacer");
  const _component_VBtn = _resolveComponent$1("VBtn");
  const _component_VToolbar = _resolveComponent$1("VToolbar");
  const _component_VDivider = _resolveComponent$1("VDivider");
  const _component_VTab = _resolveComponent$1("VTab");
  const _component_VTabs = _resolveComponent$1("VTabs");
  const _component_VChip = _resolveComponent$1("VChip");
  const _component_VTextField = _resolveComponent$1("VTextField");
  const _component_VCol = _resolveComponent$1("VCol");
  const _component_VSelect = _resolveComponent$1("VSelect");
  const _component_VRow = _resolveComponent$1("VRow");
  const _component_VSwitch = _resolveComponent$1("VSwitch");
  const _component_VWindowItem = _resolveComponent$1("VWindowItem");
  const _component_VBtnToggle = _resolveComponent$1("VBtnToggle");
  const _component_VWindow = _resolveComponent$1("VWindow");
  const _component_VSheet = _resolveComponent$1("VSheet");
  const _component_VForm = _resolveComponent$1("VForm");
  const _component_VCardText = _resolveComponent$1("VCardText");
  const _component_VCard = _resolveComponent$1("VCard");
  const _component_VDialog = _resolveComponent$1("VDialog");

  return (_openBlock$1(), _createBlock$1(_component_VDialog, {
    "model-value": __props.modelValue,
    scrollable: "",
    fullscreen: _unref$1(display).smAndDown.value,
    "max-width": "74rem",
    "onUpdate:modelValue": _cache[43] || (_cache[43] = value => emit('update:modelValue', value))
  }, {
    default: _withCtx$1(() => [
      _createVNode$1(_component_VCard, { class: "brushflow-editor" }, {
        default: _withCtx$1(() => [
          _createVNode$1(_component_VToolbar, {
            color: "transparent",
            density: "comfortable",
            class: "brushflow-editor__toolbar"
          }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_VToolbarTitle, null, {
                default: _withCtx$1(() => [
                  _createTextVNode$1(_toDisplayString$1(dialogTitle.value), 1)
                ]),
                _: 1
              }),
              _createVNode$1(_component_VSpacer),
              _createVNode$1(_component_VBtn, {
                color: "primary",
                variant: "flat",
                "prepend-icon": "mdi-content-save",
                loading: __props.saving,
                onClick: saveTask
              }, {
                default: _withCtx$1(() => _cache[44] || (_cache[44] = [
                  _createTextVNode$1(" 保存任务 ")
                ])),
                _: 1
              }, 8, ["loading"]),
              _createVNode$1(_component_VBtn, {
                icon: "mdi-close",
                variant: "text",
                "aria-label": "关闭",
                onClick: closeDialog
              })
            ]),
            _: 1
          }),
          _createVNode$1(_component_VDivider),
          _createVNode$1(_component_VCardText, { class: "brushflow-editor__body" }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_VForm, {
                ref_key: "formRef",
                ref: formRef,
                class: "brushflow-editor__form",
                onSubmit: _withModifiers(saveTask, ["prevent"])
              }, {
                default: _withCtx$1(() => [
                  _createVNode$1(_component_VTabs, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((activeTab).value = $event)),
                    direction: _unref$1(display).mdAndUp.value ? 'vertical' : 'horizontal',
                    color: "primary",
                    class: "brushflow-editor__tabs"
                  }, {
                    default: _withCtx$1(() => [
                      _createVNode$1(_component_VTab, {
                        value: "base",
                        "prepend-icon": "mdi-calendar-clock"
                      }, {
                        default: _withCtx$1(() => _cache[45] || (_cache[45] = [
                          _createTextVNode$1("基础与调度")
                        ])),
                        _: 1
                      }),
                      _createVNode$1(_component_VTab, {
                        value: "selection",
                        "prepend-icon": "mdi-filter-cog-outline"
                      }, {
                        default: _withCtx$1(() => _cache[46] || (_cache[46] = [
                          _createTextVNode$1("选种规则")
                        ])),
                        _: 1
                      }),
                      _createVNode$1(_component_VTab, {
                        value: "limits",
                        "prepend-icon": "mdi-gauge"
                      }, {
                        default: _withCtx$1(() => _cache[47] || (_cache[47] = [
                          _createTextVNode$1("运行限额")
                        ])),
                        _: 1
                      }),
                      _createVNode$1(_component_VTab, {
                        value: "delete",
                        "prepend-icon": "mdi-delete-clock-outline"
                      }, {
                        default: _withCtx$1(() => _cache[48] || (_cache[48] = [
                          _createTextVNode$1("删种规则")
                        ])),
                        _: 1
                      }),
                      _createVNode$1(_component_VTab, {
                        value: "advanced",
                        "prepend-icon": "mdi-tune-variant"
                      }, {
                        default: _withCtx$1(() => _cache[49] || (_cache[49] = [
                          _createTextVNode$1("高级")
                        ])),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["modelValue", "direction"]),
                  _createVNode$1(_component_VDivider, {
                    vertical: _unref$1(display).mdAndUp.value
                  }, null, 8, ["vertical"]),
                  _createVNode$1(_component_VWindow, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[42] || (_cache[42] = $event => ((activeTab).value = $event)),
                    touch: false,
                    class: "brushflow-editor__window"
                  }, {
                    default: _withCtx$1(() => [
                      _createVNode$1(_component_VWindowItem, { value: "base" }, {
                        default: _withCtx$1(() => [
                          _createElementVNode$1("section", _hoisted_1$1, [
                            _createElementVNode$1("header", _hoisted_2$1, [
                              _cache[51] || (_cache[51] = _createElementVNode$1("div", null, [
                                _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "任务身份"),
                                _createElementVNode$1("div", { class: "text-body-2 text-medium-emphasis" }, "每个任务绑定一个站点和下载器")
                              ], -1)),
                              _createVNode$1(_component_VChip, {
                                size: "small",
                                color: "primary",
                                variant: "tonal"
                              }, {
                                default: _withCtx$1(() => _cache[50] || (_cache[50] = [
                                  _createTextVNode$1("必填")
                                ])),
                                _: 1
                              })
                            ]),
                            _createVNode$1(_component_VRow, null, {
                              default: _withCtx$1(() => [
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.name,
                                      "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((localTask.value.name) = $event)),
                                      label: "任务名称",
                                      rules: [value => !!String(value || '').trim() || '请输入任务名称']
                                    }, null, 8, ["modelValue", "rules"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VSelect, {
                                      modelValue: localTask.value.site_id,
                                      "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((localTask.value.site_id) = $event)),
                                      items: __props.sites,
                                      label: "站点",
                                      rules: [value => !!value || '请选择站点']
                                    }, null, 8, ["modelValue", "items", "rules"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VSelect, {
                                      modelValue: localTask.value.downloader,
                                      "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((localTask.value.downloader) = $event)),
                                      items: __props.downloaders,
                                      label: "下载器",
                                      rules: [value => !!value || '请选择下载器']
                                    }, null, 8, ["modelValue", "items", "rules"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
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
                            _createElementVNode$1("div", _hoisted_3$1, [
                              _createVNode$1(_component_VSwitch, {
                                modelValue: localTask.value.enabled,
                                "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((localTask.value.enabled) = $event)),
                                label: "启用任务",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"]),
                              _createVNode$1(_component_VSwitch, {
                                modelValue: localTask.value.notify,
                                "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((localTask.value.notify) = $event)),
                                label: "发送通知",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"])
                            ])
                          ]),
                          _createElementVNode$1("section", _hoisted_4$1, [
                            _cache[52] || (_cache[52] = _createElementVNode$1("header", { class: "editor-section__head" }, [
                              _createElementVNode$1("div", null, [
                                _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "刷新计划"),
                                _createElementVNode$1("div", { class: "text-body-2 text-medium-emphasis" }, "刷流刷新和下载状态检查分别调度")
                              ])
                            ], -1)),
                            _createVNode$1(_component_VRow, null, {
                              default: _withCtx$1(() => [
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
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
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
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
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.cron,
                                      "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((localTask.value.cron) = $event)),
                                      label: "CRON 表达式",
                                      placeholder: "留空使用固定刷新周期"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
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
                          ])
                        ]),
                        _: 1
                      }),
                      _createVNode$1(_component_VWindowItem, { value: "selection" }, {
                        default: _withCtx$1(() => [
                          _createElementVNode$1("section", _hoisted_5$1, [
                            _cache[53] || (_cache[53] = _createElementVNode$1("header", { class: "editor-section__head" }, [
                              _createElementVNode$1("div", null, [
                                _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "来源与促销"),
                                _createElementVNode$1("div", { class: "text-body-2 text-medium-emphasis" }, "沿用站点列表页或 RSS 获取链路")
                              ])
                            ], -1)),
                            _createVNode$1(_component_VRow, null, {
                              default: _withCtx$1(() => [
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VSelect, {
                                      modelValue: localTask.value.freeleech,
                                      "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((localTask.value.freeleech) = $event)),
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
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VSelect, {
                                      modelValue: localTask.value.hr,
                                      "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((localTask.value.hr) = $event)),
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
                            _createElementVNode$1("div", _hoisted_6$1, [
                              _createVNode$1(_component_VSwitch, {
                                modelValue: localTask.value.rss_support,
                                "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((localTask.value.rss_support) = $event)),
                                label: "使用 RSS",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"]),
                              _createVNode$1(_component_VSwitch, {
                                modelValue: localTask.value.except_subscribe,
                                "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((localTask.value.except_subscribe) = $event)),
                                label: "排除订阅",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"]),
                              _createVNode$1(_component_VSwitch, {
                                modelValue: localTask.value.site_hr_active,
                                "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((localTask.value.site_hr_active) = $event)),
                                label: "全站 H&R",
                                color: "primary",
                                "hide-details": "",
                                inset: ""
                              }, null, 8, ["modelValue"])
                            ])
                          ]),
                          _createElementVNode$1("section", _hoisted_7$1, [
                            _cache[54] || (_cache[54] = _createElementVNode$1("header", { class: "editor-section__head" }, [
                              _createElementVNode$1("div", null, [
                                _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "候选过滤"),
                                _createElementVNode$1("div", { class: "text-body-2 text-medium-emphasis" }, "范围字段支持单值或“最小值-最大值”")
                              ])
                            ], -1)),
                            _createVNode$1(_component_VRow, null, {
                              default: _withCtx$1(() => [
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.size,
                                      "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((localTask.value.size) = $event)),
                                      label: "种子大小（GB）",
                                      placeholder: "10-80"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.seeder,
                                      "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((localTask.value.seeder) = $event)),
                                      label: "做种人数",
                                      placeholder: "1-10"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.pubtime,
                                      "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((localTask.value.pubtime) = $event)),
                                      label: "发布时间（分钟）",
                                      placeholder: "5-120"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.timezone_offset,
                                      "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((localTask.value.timezone_offset) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      label: "站点时区偏移（小时）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "8"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.include,
                                      "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((localTask.value.include) = $event)),
                                      label: "包含规则",
                                      placeholder: "支持正则表达式"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, { cols: "12" }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.exclude,
                                      "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((localTask.value.exclude) = $event)),
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
                      _createVNode$1(_component_VWindowItem, { value: "limits" }, {
                        default: _withCtx$1(() => [
                          _createElementVNode$1("section", _hoisted_8$1, [
                            _cache[55] || (_cache[55] = _createElementVNode$1("header", { class: "editor-section__head" }, [
                              _createElementVNode$1("div", null, [
                                _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "新增任务上限"),
                                _createElementVNode$1("div", { class: "text-body-2 text-medium-emphasis" }, "达到任一上限后停止为当前任务新增种子")
                              ])
                            ], -1)),
                            _createVNode$1(_component_VRow, null, {
                              default: _withCtx$1(() => [
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.disksize,
                                      "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((localTask.value.disksize) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "保种体积（GB）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.maxdlcount,
                                      "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((localTask.value.maxdlcount) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "同时下载任务数"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.maxupspeed,
                                      "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((localTask.value.maxupspeed) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "总上传带宽（KB/s）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.maxdlspeed,
                                      "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((localTask.value.maxdlspeed) = $event)),
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
                          _createElementVNode$1("section", _hoisted_9$1, [
                            _cache[56] || (_cache[56] = _createElementVNode$1("header", { class: "editor-section__head" }, [
                              _createElementVNode$1("div", null, [
                                _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "单种限速"),
                                _createElementVNode$1("div", { class: "text-body-2 text-medium-emphasis" }, "只作用于当前任务新添加的种子")
                              ])
                            ], -1)),
                            _createVNode$1(_component_VRow, null, {
                              default: _withCtx$1(() => [
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.up_speed,
                                      "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((localTask.value.up_speed) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "上传限速（KB/s）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.dl_speed,
                                      "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((localTask.value.dl_speed) = $event)),
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
                      _createVNode$1(_component_VWindowItem, { value: "delete" }, {
                        default: _withCtx$1(() => [
                          _createElementVNode$1("section", _hoisted_10$1, [
                            _cache[59] || (_cache[59] = _createElementVNode$1("header", { class: "editor-section__head" }, [
                              _createElementVNode$1("div", null, [
                                _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "删除模式"),
                                _createElementVNode$1("div", { class: "text-body-2 text-medium-emphasis" }, "动态模式会在超过体积阈值后按现有算法托管删种")
                              ])
                            ], -1)),
                            _createVNode$1(_component_VBtnToggle, {
                              modelValue: localTask.value.proxy_delete,
                              "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((localTask.value.proxy_delete) = $event)),
                              mandatory: "",
                              color: "primary",
                              divided: ""
                            }, {
                              default: _withCtx$1(() => [
                                _createVNode$1(_component_VBtn, { value: false }, {
                                  default: _withCtx$1(() => _cache[57] || (_cache[57] = [
                                    _createTextVNode$1("按条件删除")
                                  ])),
                                  _: 1
                                }),
                                _createVNode$1(_component_VBtn, { value: true }, {
                                  default: _withCtx$1(() => _cache[58] || (_cache[58] = [
                                    _createTextVNode$1("动态删种")
                                  ])),
                                  _: 1
                                })
                              ]),
                              _: 1
                            }, 8, ["modelValue"]),
                            (localTask.value.proxy_delete)
                              ? (_openBlock$1(), _createBlock$1(_component_VRow, { key: 0 }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VCol, { cols: "12" }, {
                                      default: _withCtx$1(() => [
                                        _createVNode$1(_component_VTextField, {
                                          modelValue: localTask.value.delete_size_range,
                                          "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((localTask.value.delete_size_range) = $event)),
                                          label: "动态删种阈值（GB）",
                                          placeholder: "如 350-500"
                                        }, null, 8, ["modelValue"])
                                      ]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                }))
                              : _createCommentVNode$1("", true)
                          ]),
                          _createElementVNode$1("section", _hoisted_11$1, [
                            _cache[60] || (_cache[60] = _createElementVNode$1("header", { class: "editor-section__head" }, [
                              _createElementVNode$1("div", null, [
                                _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "触发条件"),
                                _createElementVNode$1("div", { class: "text-body-2 text-medium-emphasis" }, "普通模式满足任一条件即删除")
                              ])
                            ], -1)),
                            _createVNode$1(_component_VRow, null, {
                              default: _withCtx$1(() => [
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.seed_time,
                                      "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((localTask.value.seed_time) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "做种时间（小时）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.hr_seed_time,
                                      "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((localTask.value.hr_seed_time) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "H&R 做种时间（小时）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.seed_ratio,
                                      "onUpdate:modelValue": _cache[32] || (_cache[32] = $event => ((localTask.value.seed_ratio) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "分享率"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.seed_size,
                                      "onUpdate:modelValue": _cache[33] || (_cache[33] = $event => ((localTask.value.seed_size) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "上传量（GB）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.download_time,
                                      "onUpdate:modelValue": _cache[34] || (_cache[34] = $event => ((localTask.value.download_time) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "下载超时（小时）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.seed_inactivetime,
                                      "onUpdate:modelValue": _cache[35] || (_cache[35] = $event => ((localTask.value.seed_inactivetime) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "未活动时间（分钟）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "4"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.seed_avgspeed,
                                      "onUpdate:modelValue": _cache[36] || (_cache[36] = $event => ((localTask.value.seed_avgspeed) = $event)),
                                      modelModifiers: { number: true },
                                      type: "number",
                                      min: "0",
                                      label: "平均上传速度（KB/s）"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "8"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.delete_except_tags,
                                      "onUpdate:modelValue": _cache[37] || (_cache[37] = $event => ((localTask.value.delete_except_tags) = $event)),
                                      label: "删除排除标签"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            }),
                            _createVNode$1(_component_VSwitch, {
                              modelValue: localTask.value.del_no_free,
                              "onUpdate:modelValue": _cache[38] || (_cache[38] = $event => ((localTask.value.del_no_free) = $event)),
                              label: "删除促销过期的未完成下载",
                              color: "primary",
                              "hide-details": "",
                              inset: ""
                            }, null, 8, ["modelValue"])
                          ])
                        ]),
                        _: 1
                      }),
                      _createVNode$1(_component_VWindowItem, { value: "advanced" }, {
                        default: _withCtx$1(() => [
                          _createElementVNode$1("section", _hoisted_12$1, [
                            _cache[61] || (_cache[61] = _createElementVNode$1("header", { class: "editor-section__head" }, [
                              _createElementVNode$1("div", null, [
                                _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "下载器适配"),
                                _createElementVNode$1("div", { class: "text-body-2 text-medium-emphasis" }, "保留原有分类、提示跳过和自动归档能力")
                              ])
                            ], -1)),
                            _createVNode$1(_component_VRow, null, {
                              default: _withCtx$1(() => [
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.qb_category,
                                      "onUpdate:modelValue": _cache[39] || (_cache[39] = $event => ((localTask.value.qb_category) = $event)),
                                      label: "qBittorrent 分类"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode$1(_component_VCol, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createVNode$1(_component_VTextField, {
                                      modelValue: localTask.value.auto_archive_days,
                                      "onUpdate:modelValue": _cache[40] || (_cache[40] = $event => ((localTask.value.auto_archive_days) = $event)),
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
                            _createElementVNode$1("div", _hoisted_13$1, [
                              _createVNode$1(_component_VSwitch, {
                                modelValue: localTask.value.site_skip_tips,
                                "onUpdate:modelValue": _cache[41] || (_cache[41] = $event => ((localTask.value.site_skip_tips) = $event)),
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
                  _createVNode$1(_component_VSheet, {
                    tag: "aside",
                    class: "brushflow-editor__summary"
                  }, {
                    default: _withCtx$1(() => [
                      _cache[70] || (_cache[70] = _createElementVNode$1("div", { class: "text-subtitle-1 font-weight-medium" }, "配置摘要", -1)),
                      _createElementVNode$1("dl", null, [
                        _createElementVNode$1("div", null, [
                          _cache[62] || (_cache[62] = _createElementVNode$1("dt", null, "站点", -1)),
                          _createElementVNode$1("dd", null, _toDisplayString$1(siteName.value), 1)
                        ]),
                        _createElementVNode$1("div", null, [
                          _cache[63] || (_cache[63] = _createElementVNode$1("dt", null, "下载器", -1)),
                          _createElementVNode$1("dd", null, _toDisplayString$1(localTask.value.downloader || '未选择'), 1)
                        ]),
                        _createElementVNode$1("div", null, [
                          _cache[64] || (_cache[64] = _createElementVNode$1("dt", null, "刷新", -1)),
                          _createElementVNode$1("dd", null, _toDisplayString$1(scheduleText.value), 1)
                        ]),
                        _createElementVNode$1("div", null, [
                          _cache[65] || (_cache[65] = _createElementVNode$1("dt", null, "检查", -1)),
                          _createElementVNode$1("dd", null, "每 " + _toDisplayString$1(localTask.value.check_interval || 5) + " 分钟", 1)
                        ]),
                        _createElementVNode$1("div", null, [
                          _cache[66] || (_cache[66] = _createElementVNode$1("dt", null, "时段", -1)),
                          _createElementVNode$1("dd", null, _toDisplayString$1(localTask.value.active_time_range || '全天'), 1)
                        ]),
                        _createElementVNode$1("div", null, [
                          _cache[67] || (_cache[67] = _createElementVNode$1("dt", null, "促销", -1)),
                          _createElementVNode$1("dd", null, _toDisplayString$1(localTask.value.freeleech === '2xfree' ? '2X 免费' : localTask.value.freeleech === 'free' ? '免费' : '全部'), 1)
                        ]),
                        _createElementVNode$1("div", null, [
                          _cache[68] || (_cache[68] = _createElementVNode$1("dt", null, "保种上限", -1)),
                          _createElementVNode$1("dd", null, _toDisplayString$1(localTask.value.disksize ? `${localTask.value.disksize} GB` : '不限'), 1)
                        ]),
                        _createElementVNode$1("div", null, [
                          _cache[69] || (_cache[69] = _createElementVNode$1("dt", null, "删除", -1)),
                          _createElementVNode$1("dd", null, _toDisplayString$1(localTask.value.proxy_delete ? '动态删种' : '按条件删除'), 1)
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
const TaskEditorDialog = /*#__PURE__*/_export_sfc(_sfc_main$1, [['__scopeId',"data-v-81d96958"]]);

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,mergeProps:_mergeProps,createElementBlock:_createElementBlock,unref:_unref,renderList:_renderList,Fragment:_Fragment,normalizeClass:_normalizeClass,normalizeStyle:_normalizeStyle} = await importShared('vue');


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
const _hoisted_18 = { class: "brushflow-overview-grid" };
const _hoisted_19 = { class: "brushflow-panel__head" };
const _hoisted_20 = { class: "brushflow-facts" };
const _hoisted_21 = { class: "brushflow-panel__head" };
const _hoisted_22 = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_23 = { class: "brushflow-run-summary" };
const _hoisted_24 = { class: "brushflow-panel__head" };
const _hoisted_25 = { class: "brushflow-panel__title-row" };
const _hoisted_26 = { class: "torrent-title-cell" };
const _hoisted_27 = { class: "brushflow-mobile-torrents" };
const _hoisted_28 = { class: "brushflow-mobile-torrent__head" };
const _hoisted_29 = { class: "brushflow-mobile-torrent__meta" };
const _hoisted_30 = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_31 = {
  key: 0,
  class: "brushflow-table-empty"
};
const _hoisted_32 = { class: "brushflow-diagnostic-head" };
const _hoisted_33 = { class: "text-subtitle-1 font-weight-medium" };
const _hoisted_34 = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_35 = { class: "brushflow-diagnostic-grid" };
const _hoisted_36 = { class: "brushflow-pipeline" };
const _hoisted_37 = { class: "brushflow-pipeline__index" };
const _hoisted_38 = {
  key: 0,
  class: "brushflow-reasons"
};
const _hoisted_39 = { class: "brushflow-reason__track" };
const _hoisted_40 = {
  key: 1,
  class: "brushflow-table-empty"
};
const _hoisted_41 = { class: "brushflow-events" };
const _hoisted_42 = {
  key: 0,
  class: "text-error"
};
const _hoisted_43 = {
  key: 0,
  class: "brushflow-table-empty"
};
const _hoisted_44 = { class: "brushflow-config-grid" };
const _hoisted_45 = { class: "brushflow-facts brushflow-facts--two" };
const _hoisted_46 = { class: "brushflow-config-actions" };

const {computed,inject,onMounted,onUnmounted,ref,watch} = await importShared('vue');


const _sfc_main = {
  __name: 'BrushFlowWorkbench',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'BrushFlow' },
  initialTab: { type: String, default: 'overview' },
  showClose: { type: Boolean, default: false },
  showSwitch: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
},
  emits: ['close', 'switch', 'action'],
  setup(__props, { expose: __expose, emit: __emit }) {

const props = __props;

const emit = __emit;
const loading = ref(false);
const taskLoading = ref(false);
const saving = ref(false);
const error = ref('');
const status = ref({
  enabled: false,
  show_sidebar_nav: true,
  summary: {},
  tasks: [],
  options: { sites: [], downloaders: [] },
});
const taskDetail = ref(null);
const selectedTaskId = ref('');
const activeTab = ref(props.initialTab);
const torrentState = ref('active');
const torrentPage = ref(1);
const editorOpen = ref(false);
const editorTask = ref(cloneTask());
const deleteDialog = ref(false);
const clearDialog = ref(false);
const settingsMenu = ref(false);
const settingsDraft = ref({ enabled: false, show_sidebar_nav: true });
const hostToast = inject('moviepilot:toast', null);
let refreshTimer;

const pluginBase = computed(() => `plugin/${props.pluginId || 'BrushFlow'}`);
const tasks = computed(() => status.value.tasks || []);
const selectedTask = computed(() => tasks.value.find(item => item.id === selectedTaskId.value) || null);
const selectedState = computed(() => taskStateMeta(selectedTask.value?.state));
const taskConfig = computed(() => taskDetail.value?.task || {});
const taskRuns = computed(() => taskDetail.value?.runs || []);
const latestBrushRun = computed(() => taskRuns.value.find(item => item.kind === 'brush') || null);
const torrentData = computed(() => taskDetail.value?.torrents || { items: [], total: 0, page: 1, page_size: 50 });
const totalTorrentPages = computed(() => Math.max(Math.ceil(torrentData.value.total / torrentData.value.page_size), 1));
const seedingPercent = computed(() => {
  const limit = Number(taskConfig.value.disksize || 0) * 1024 ** 3;
  if (!limit) return 0
  return Math.min(Math.round((Number(selectedTask.value?.seeding_size || 0) * 100) / limit), 100)
});
const reasonEntries = computed(() => {
  const reasons = latestBrushRun.value?.reason_counts || {};
  return Object.entries(reasons)
    .map(([label, count]) => ({ label, count: Number(count || 0) }))
    .sort((left, right) => right.count - left.count)
});
const maxReasonCount = computed(() => Math.max(1, ...reasonEntries.value.map(item => item.count)));
const pipelineStages = computed(() => {
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
    status.value = unwrapResponse(await props.api.post(`${pluginBase.value}/settings`, settingsDraft.value));
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

watch(
  () => props.initialTab,
  value => {
    if (value) activeTab.value = value;
  },
);

onMounted(async () => {
  await loadStatus({ preserveSelection: false });
  refreshTimer = window.setInterval(() => {
    if (!editorOpen.value && document.visibilityState === 'visible') loadStatus();
  }, 30000);
});

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});

__expose({ loadStatus, refreshAll, loading, saving });

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VMenu = _resolveComponent("VMenu");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSkeletonLoader = _resolveComponent("VSkeletonLoader");
  const _component_VListItem = _resolveComponent("VListItem");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VSheet = _resolveComponent("VSheet");
  const _component_VAvatar = _resolveComponent("VAvatar");
  const _component_VTooltip = _resolveComponent("VTooltip");
  const _component_VTab = _resolveComponent("VTab");
  const _component_VTabs = _resolveComponent("VTabs");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VBtnToggle = _resolveComponent("VBtnToggle");
  const _component_VDataTable = _resolveComponent("VDataTable");
  const _component_VPagination = _resolveComponent("VPagination");
  const _component_VWindowItem = _resolveComponent("VWindowItem");
  const _component_VWindow = _resolveComponent("VWindow");
  const _component_VDialog = _resolveComponent("VDialog");

  return (_openBlock(), _createElementBlock("div", {
    class: _normalizeClass(["brushflow-page", { 'brushflow-page--compact': __props.compact }])
  }, [
    _createElementVNode("header", _hoisted_1, [
      _createElementVNode("div", _hoisted_2, [
        _createVNode(_component_VIcon, {
          icon: "mdi-sync",
          color: "primary",
          size: "28"
        }),
        _cache[18] || (_cache[18] = _createElementVNode("div", null, [
          _createElementVNode("h1", null, "站点刷流"),
          _createElementVNode("p", null, "多站点任务独立调度与托管")
        ], -1))
      ]),
      _createElementVNode("div", _hoisted_3, [
        (status.value.summary.task_count)
          ? (_openBlock(), _createBlock(_component_VChip, {
              key: 0,
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(status.value.summary.enabled_count || 0) + " / " + _toDisplayString(status.value.summary.task_count) + " 运行 ", 1)
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_VMenu, {
          modelValue: settingsMenu.value,
          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((settingsMenu).value = $event)),
          "close-on-content-click": false,
          location: "bottom end"
        }, {
          activator: _withCtx(({ props: menuProps }) => [
            _createVNode(_component_VBtn, _mergeProps(menuProps, {
              icon: "mdi-tune-variant",
              variant: "text",
              "aria-label": "全局设置"
            }), null, 16)
          ]),
          default: _withCtx(() => [
            _createVNode(_component_VCard, {
              "min-width": "300",
              title: "全局设置"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VCardText, { class: "settings-menu__body" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VSwitch, {
                      modelValue: settingsDraft.value.enabled,
                      "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((settingsDraft.value.enabled) = $event)),
                      label: "启用插件",
                      color: "primary",
                      "hide-details": "",
                      inset: ""
                    }, null, 8, ["modelValue"]),
                    _createVNode(_component_VSwitch, {
                      modelValue: settingsDraft.value.show_sidebar_nav,
                      "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((settingsDraft.value.show_sidebar_nav) = $event)),
                      label: "显示侧栏入口",
                      color: "primary",
                      "hide-details": "",
                      inset: ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_VCardActions, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_VSpacer),
                    _createVNode(_component_VBtn, {
                      color: "primary",
                      variant: "flat",
                      loading: saving.value,
                      onClick: saveSettings
                    }, {
                      default: _withCtx(() => _cache[19] || (_cache[19] = [
                        _createTextVNode("保存")
                      ])),
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
        (__props.showSwitch)
          ? (_openBlock(), _createBlock(_component_VBtn, {
              key: 1,
              icon: "mdi-cog-outline",
              variant: "text",
              "aria-label": "切换配置",
              onClick: _cache[3] || (_cache[3] = $event => (emit('switch')))
            }))
          : _createCommentVNode("", true),
        (__props.showClose)
          ? (_openBlock(), _createBlock(_component_VBtn, {
              key: 2,
              icon: "mdi-close",
              variant: "text",
              "aria-label": "关闭",
              onClick: _cache[4] || (_cache[4] = $event => (emit('close')))
            }))
          : _createCommentVNode("", true)
      ])
    ]),
    (error.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 0,
          type: "error",
          variant: "tonal",
          closable: "",
          "onClick:close": _cache[5] || (_cache[5] = $event => (error.value = ''))
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (!status.value.enabled)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 1,
          type: "warning",
          variant: "tonal"
        }, {
          default: _withCtx(() => _cache[20] || (_cache[20] = [
            _createTextVNode(" 插件当前未启用，任务配置与历史仍可查看，启用后才会注册刷新和检查服务。 ")
          ])),
          _: 1
        }))
      : _createCommentVNode("", true),
    (loading.value && !tasks.value.length)
      ? (_openBlock(), _createElementBlock("div", _hoisted_4, [
          _createVNode(_component_VSkeletonLoader, { type: "list-item-three-line, list-item-three-line, article" })
        ]))
      : (!tasks.value.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_5, [
            _createVNode(_component_VIcon, {
              icon: "mdi-sync-off",
              size: "52",
              color: "medium-emphasis"
            }),
            _cache[22] || (_cache[22] = _createElementVNode("div", { class: "text-h6" }, "还没有刷流任务", -1)),
            _cache[23] || (_cache[23] = _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "创建任务后可为每个站点分别设置刷新、筛选和删种规则", -1)),
            _createVNode(_component_VBtn, {
              color: "primary",
              variant: "flat",
              "prepend-icon": "mdi-plus",
              onClick: openCreateTask
            }, {
              default: _withCtx(() => _cache[21] || (_cache[21] = [
                _createTextVNode("创建第一个任务")
              ])),
              _: 1
            })
          ]))
        : (_openBlock(), _createElementBlock(_Fragment, { key: 4 }, [
            _createVNode(_component_VSelect, {
              class: "brushflow-mobile-select",
              "model-value": selectedTaskId.value,
              items: tasks.value,
              "item-title": "name",
              "item-value": "id",
              label: "当前任务",
              "hide-details": "",
              "onUpdate:modelValue": selectTask
            }, {
              item: _withCtx(({ props: itemProps, item }) => [
                _createVNode(_component_VListItem, _mergeProps(itemProps, {
                  subtitle: item.raw.site_name
                }), {
                  prepend: _withCtx(() => [
                    _createVNode(_component_VIcon, {
                      icon: _unref(taskStateMeta)(item.raw.state).icon,
                      color: _unref(taskStateMeta)(item.raw.state).color
                    }, null, 8, ["icon", "color"])
                  ]),
                  _: 2
                }, 1040, ["subtitle"])
              ]),
              _: 1
            }, 8, ["model-value", "items"]),
            _createElementVNode("div", _hoisted_6, [
              _createVNode(_component_VSheet, {
                tag: "aside",
                class: "brushflow-task-rail app-surface-static"
              }, {
                default: _withCtx(() => [
                  _createElementVNode("div", _hoisted_7, [
                    _cache[24] || (_cache[24] = _createElementVNode("span", { class: "text-subtitle-2" }, "刷流任务", -1)),
                    _createVNode(_component_VChip, {
                      size: "x-small",
                      variant: "tonal"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(tasks.value.length), 1)
                      ]),
                      _: 1
                    })
                  ]),
                  _createElementVNode("div", _hoisted_8, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(tasks.value, (task) => {
                      return (_openBlock(), _createElementBlock("button", {
                        key: task.id,
                        type: "button",
                        class: _normalizeClass(["brushflow-task-item", { 'brushflow-task-item--selected': task.id === selectedTaskId.value }]),
                        "aria-pressed": task.id === selectedTaskId.value,
                        onClick: $event => (selectTask(task.id))
                      }, [
                        _createElementVNode("span", _hoisted_10, [
                          _createElementVNode("strong", null, _toDisplayString(task.name), 1),
                          _createElementVNode("span", {
                            class: _normalizeClass(["brushflow-status-dot", `brushflow-status-dot--${_unref(taskStateMeta)(task.state).color}`])
                          }, null, 2)
                        ]),
                        _createElementVNode("span", null, _toDisplayString(task.site_name) + " · " + _toDisplayString(task.downloader), 1),
                        _createElementVNode("span", _hoisted_11, [
                          _createElementVNode("span", null, _toDisplayString(task.statistic.active || 0) + " 个种子", 1),
                          _createElementVNode("span", null, _toDisplayString(task.next_run_at ? _unref(formatDateTime)(task.next_run_at) : '暂无计划'), 1)
                        ])
                      ], 10, _hoisted_9))
                    }), 128))
                  ]),
                  _createVNode(_component_VBtn, {
                    block: "",
                    variant: "tonal",
                    "prepend-icon": "mdi-plus",
                    onClick: openCreateTask
                  }, {
                    default: _withCtx(() => _cache[25] || (_cache[25] = [
                      _createTextVNode("新建任务")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              }),
              (selectedTask.value)
                ? (_openBlock(), _createElementBlock("main", _hoisted_12, [
                    _createElementVNode("section", _hoisted_13, [
                      _createElementVNode("div", _hoisted_14, [
                        _createVNode(_component_VAvatar, {
                          color: "primary",
                          variant: "tonal",
                          rounded: "",
                          size: "42"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_VIcon, { icon: "mdi-web" })
                          ]),
                          _: 1
                        }),
                        _createElementVNode("div", null, [
                          _createElementVNode("div", _hoisted_15, [
                            _createElementVNode("h2", null, _toDisplayString(selectedTask.value.name), 1),
                            _createVNode(_component_VChip, {
                              color: selectedState.value.color,
                              size: "small",
                              variant: "tonal",
                              "prepend-icon": selectedState.value.icon
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(selectedState.value.text), 1)
                              ]),
                              _: 1
                            }, 8, ["color", "prepend-icon"])
                          ]),
                          _createElementVNode("p", null, _toDisplayString(selectedTask.value.site_name) + " · 最近 " + _toDisplayString(selectedTask.value.last_run ? _unref(formatDateTime)(selectedTask.value.last_run.started_at) : '尚未运行') + " · 下次 " + _toDisplayString(selectedTask.value.next_run_at ? _unref(formatDateTime)(selectedTask.value.next_run_at) : '暂无计划'), 1)
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_16, [
                        _createVNode(_component_VTooltip, { text: "立即刷新" }, {
                          activator: _withCtx(({ props: tipProps }) => [
                            _createVNode(_component_VBtn, _mergeProps(tipProps, {
                              icon: "mdi-sync",
                              variant: "text",
                              loading: selectedTask.value.operation === 'brush',
                              onClick: _cache[6] || (_cache[6] = $event => (runOperation('brush')))
                            }), null, 16, ["loading"])
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_VTooltip, { text: "检查种子" }, {
                          activator: _withCtx(({ props: tipProps }) => [
                            _createVNode(_component_VBtn, _mergeProps(tipProps, {
                              icon: "mdi-progress-check",
                              variant: "text",
                              loading: selectedTask.value.operation === 'check',
                              onClick: _cache[7] || (_cache[7] = $event => (runOperation('check')))
                            }), null, 16, ["loading"])
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_VTooltip, {
                          text: selectedTask.value.enabled ? '暂停任务' : '启用任务'
                        }, {
                          activator: _withCtx(({ props: tipProps }) => [
                            _createVNode(_component_VBtn, _mergeProps(tipProps, {
                              icon: selectedTask.value.enabled ? 'mdi-pause' : 'mdi-play',
                              variant: "text",
                              onClick: toggleSelectedTask
                            }), null, 16, ["icon"])
                          ]),
                          _: 1
                        }, 8, ["text"]),
                        _createVNode(_component_VTooltip, { text: "编辑任务" }, {
                          activator: _withCtx(({ props: tipProps }) => [
                            _createVNode(_component_VBtn, _mergeProps(tipProps, {
                              icon: "mdi-pencil-outline",
                              variant: "text",
                              onClick: openEditTask
                            }), null, 16)
                          ]),
                          _: 1
                        })
                      ])
                    ]),
                    _createVNode(_component_VTabs, {
                      modelValue: activeTab.value,
                      "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((activeTab).value = $event)),
                      color: "primary",
                      class: "brushflow-tabs"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTab, { value: "overview" }, {
                          default: _withCtx(() => _cache[26] || (_cache[26] = [
                            _createTextVNode("任务概览")
                          ])),
                          _: 1
                        }),
                        _createVNode(_component_VTab, { value: "diagnostics" }, {
                          default: _withCtx(() => _cache[27] || (_cache[27] = [
                            _createTextVNode("运行诊断")
                          ])),
                          _: 1
                        }),
                        _createVNode(_component_VTab, { value: "config" }, {
                          default: _withCtx(() => _cache[28] || (_cache[28] = [
                            _createTextVNode("任务配置")
                          ])),
                          _: 1
                        })
                      ]),
                      _: 1
                    }, 8, ["modelValue"]),
                    _createVNode(_component_VDivider),
                    _createVNode(_component_VWindow, {
                      modelValue: activeTab.value,
                      "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((activeTab).value = $event)),
                      touch: false,
                      class: "brushflow-window"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VWindowItem, { value: "overview" }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_17, [
                              _createVNode(_component_VSheet, { class: "brushflow-stat app-surface-static" }, {
                                default: _withCtx(() => [
                                  _cache[29] || (_cache[29] = _createElementVNode("span", null, "活跃种子", -1)),
                                  _createElementVNode("strong", null, _toDisplayString(selectedTask.value.statistic.active || 0), 1),
                                  _createElementVNode("small", null, _toDisplayString(selectedTask.value.statistic.unarchived || 0) + " 个待归档", 1)
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_VSheet, { class: "brushflow-stat app-surface-static" }, {
                                default: _withCtx(() => [
                                  _cache[30] || (_cache[30] = _createElementVNode("span", null, "累计上传 / 下载", -1)),
                                  _createElementVNode("strong", null, _toDisplayString(_unref(formatBytes)(selectedTask.value.statistic.uploaded)) + " / " + _toDisplayString(_unref(formatBytes)(selectedTask.value.statistic.downloaded)), 1),
                                  _cache[31] || (_cache[31] = _createElementVNode("small", null, "当前任务累计", -1))
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_VSheet, { class: "brushflow-stat app-surface-static" }, {
                                default: _withCtx(() => [
                                  _cache[32] || (_cache[32] = _createElementVNode("span", null, "当前做种", -1)),
                                  _createElementVNode("strong", null, _toDisplayString(_unref(formatBytes)(selectedTask.value.seeding_size)), 1),
                                  _createElementVNode("small", null, _toDisplayString(taskConfig.value.disksize ? `上限 ${taskConfig.value.disksize} GB` : '未设置体积上限'), 1),
                                  (taskConfig.value.disksize)
                                    ? (_openBlock(), _createBlock(_component_VProgressLinear, {
                                        key: 0,
                                        "model-value": seedingPercent.value,
                                        height: "4",
                                        color: "primary"
                                      }, null, 8, ["model-value"]))
                                    : _createCommentVNode("", true)
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_VSheet, { class: "brushflow-stat app-surface-static" }, {
                                default: _withCtx(() => [
                                  _cache[33] || (_cache[33] = _createElementVNode("span", null, "最近刷新", -1)),
                                  _createElementVNode("strong", null, _toDisplayString(latestBrushRun.value ? `${latestBrushRun.value.added_count || 0} / ${latestBrushRun.value.source_count || 0}` : '-'), 1),
                                  _cache[34] || (_cache[34] = _createElementVNode("small", null, "新增 / 候选", -1))
                                ]),
                                _: 1
                              })
                            ]),
                            _createElementVNode("div", _hoisted_18, [
                              _createVNode(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: _withCtx(() => [
                                  _createElementVNode("header", _hoisted_19, [
                                    _cache[35] || (_cache[35] = _createElementVNode("div", null, [
                                      _createElementVNode("div", { class: "text-subtitle-1 font-weight-medium" }, "运行状态"),
                                      _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "当前任务调度与核心策略")
                                    ], -1)),
                                    _createVNode(_component_VChip, {
                                      color: selectedState.value.color,
                                      size: "small",
                                      variant: "tonal"
                                    }, {
                                      default: _withCtx(() => [
                                        _createTextVNode(_toDisplayString(selectedState.value.text), 1)
                                      ]),
                                      _: 1
                                    }, 8, ["color"])
                                  ]),
                                  _createElementVNode("dl", _hoisted_20, [
                                    _createElementVNode("div", null, [
                                      _cache[36] || (_cache[36] = _createElementVNode("dt", null, "刷新周期", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.cron || `每 ${selectedTask.value.brush_interval} 分钟`), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[37] || (_cache[37] = _createElementVNode("dt", null, "检查周期", -1)),
                                      _createElementVNode("dd", null, "每 " + _toDisplayString(selectedTask.value.check_interval) + " 分钟", 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[38] || (_cache[38] = _createElementVNode("dt", null, "开启时段", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.active_time_range || '全天'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[39] || (_cache[39] = _createElementVNode("dt", null, "选种来源", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.rss_support ? 'RSS' : '站点列表页'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[40] || (_cache[40] = _createElementVNode("dt", null, "促销要求", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.freeleech === '2xfree' ? '2X 免费' : taskConfig.value.freeleech === 'free' ? '免费' : '全部'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[41] || (_cache[41] = _createElementVNode("dt", null, "删种策略", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.proxy_delete ? `动态 ${taskConfig.value.delete_size_range || '-' } GB` : '满足任一条件'), 1)
                                    ])
                                  ])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: _withCtx(() => [
                                  _createElementVNode("header", _hoisted_21, [
                                    _createElementVNode("div", null, [
                                      _cache[42] || (_cache[42] = _createElementVNode("div", { class: "text-subtitle-1 font-weight-medium" }, "最近一次刷新", -1)),
                                      _createElementVNode("div", _hoisted_22, _toDisplayString(latestBrushRun.value ? `${_unref(formatDateTime)(latestBrushRun.value.started_at)} · ${_unref(formatDuration)(latestBrushRun.value.started_at, latestBrushRun.value.finished_at)}` : '暂无运行记录'), 1)
                                    ]),
                                    (latestBrushRun.value)
                                      ? (_openBlock(), _createBlock(_component_VChip, {
                                          key: 0,
                                          color: latestBrushRun.value.success === false ? 'error' : 'success',
                                          size: "small",
                                          variant: "tonal"
                                        }, {
                                          default: _withCtx(() => [
                                            _createTextVNode(_toDisplayString(latestBrushRun.value.success === false ? '失败' : '完成'), 1)
                                          ]),
                                          _: 1
                                        }, 8, ["color"]))
                                      : _createCommentVNode("", true)
                                  ]),
                                  _createElementVNode("div", _hoisted_23, [
                                    _createElementVNode("div", null, [
                                      _cache[43] || (_cache[43] = _createElementVNode("span", null, "站点候选", -1)),
                                      _createElementVNode("strong", null, _toDisplayString(latestBrushRun.value?.source_count || 0), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[44] || (_cache[44] = _createElementVNode("span", null, "规则过滤", -1)),
                                      _createElementVNode("strong", null, _toDisplayString(latestBrushRun.value?.filtered_count || 0), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[45] || (_cache[45] = _createElementVNode("span", null, "新增下载", -1)),
                                      _createElementVNode("strong", null, _toDisplayString(latestBrushRun.value?.added_count || 0), 1)
                                    ])
                                  ]),
                                  (latestBrushRun.value?.error)
                                    ? (_openBlock(), _createBlock(_component_VAlert, {
                                        key: 0,
                                        type: "error",
                                        variant: "tonal",
                                        density: "compact"
                                      }, {
                                        default: _withCtx(() => [
                                          _createTextVNode(_toDisplayString(latestBrushRun.value.error), 1)
                                        ]),
                                        _: 1
                                      }))
                                    : _createCommentVNode("", true),
                                  _createVNode(_component_VBtn, {
                                    variant: "text",
                                    color: "primary",
                                    "append-icon": "mdi-arrow-right",
                                    onClick: _cache[9] || (_cache[9] = $event => (activeTab.value = 'diagnostics'))
                                  }, {
                                    default: _withCtx(() => _cache[46] || (_cache[46] = [
                                      _createTextVNode(" 查看运行诊断 ")
                                    ])),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              })
                            ]),
                            _createVNode(_component_VSheet, {
                              tag: "section",
                              class: "brushflow-panel brushflow-torrents app-surface-static"
                            }, {
                              default: _withCtx(() => [
                                _createElementVNode("header", _hoisted_24, [
                                  _createElementVNode("div", null, [
                                    _createElementVNode("div", _hoisted_25, [
                                      _cache[47] || (_cache[47] = _createElementVNode("span", { class: "text-subtitle-1 font-weight-medium" }, "托管种子", -1)),
                                      _createVNode(_component_VChip, {
                                        size: "x-small",
                                        variant: "tonal"
                                      }, {
                                        default: _withCtx(() => [
                                          _createTextVNode(_toDisplayString(torrentData.value.total), 1)
                                        ]),
                                        _: 1
                                      })
                                    ]),
                                    _cache[48] || (_cache[48] = _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "当前任务独立记录", -1))
                                  ]),
                                  _createVNode(_component_VBtnToggle, {
                                    "model-value": torrentState.value,
                                    mandatory: "",
                                    color: "primary",
                                    density: "compact",
                                    "onUpdate:modelValue": changeTorrentState
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_VBtn, { value: "active" }, {
                                        default: _withCtx(() => _cache[49] || (_cache[49] = [
                                          _createTextVNode("活跃")
                                        ])),
                                        _: 1
                                      }),
                                      _createVNode(_component_VBtn, { value: "deleted" }, {
                                        default: _withCtx(() => _cache[50] || (_cache[50] = [
                                          _createTextVNode("已删除")
                                        ])),
                                        _: 1
                                      }),
                                      _createVNode(_component_VBtn, { value: "all" }, {
                                        default: _withCtx(() => _cache[51] || (_cache[51] = [
                                          _createTextVNode("全部")
                                        ])),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  }, 8, ["model-value"])
                                ]),
                                _createVNode(_component_VDataTable, {
                                  class: "brushflow-torrent-table",
                                  headers: torrentHeaders,
                                  items: torrentData.value.items,
                                  loading: taskLoading.value,
                                  "items-per-page": -1,
                                  "hide-default-footer": "",
                                  density: "comfortable"
                                }, {
                                  "item.title": _withCtx(({ item }) => [
                                    _createElementVNode("div", _hoisted_26, [
                                      _createElementVNode("strong", null, _toDisplayString(item.title || '未知种子'), 1),
                                      _createElementVNode("span", null, _toDisplayString(item.site_name) + " · " + _toDisplayString(_unref(formatDateTime)((item.time || 0) * 1000)), 1)
                                    ])
                                  ]),
                                  "item.status": _withCtx(({ item }) => [
                                    _createVNode(_component_VChip, {
                                      size: "small",
                                      color: item.deleted ? 'secondary' : _unref(torrentProgress)(item) >= 100 ? 'success' : 'info',
                                      variant: "tonal"
                                    }, {
                                      default: _withCtx(() => [
                                        _createTextVNode(_toDisplayString(torrentStateText(item)), 1)
                                      ]),
                                      _: 2
                                    }, 1032, ["color"])
                                  ]),
                                  "item.size": _withCtx(({ item }) => [
                                    _createTextVNode(_toDisplayString(_unref(formatBytes)(item.size)), 1)
                                  ]),
                                  "item.uploaded": _withCtx(({ item }) => [
                                    _createTextVNode(_toDisplayString(_unref(formatBytes)(item.uploaded)), 1)
                                  ]),
                                  "item.ratio": _withCtx(({ item }) => [
                                    _createTextVNode(_toDisplayString(Number(item.ratio || 0).toFixed(2)), 1)
                                  ]),
                                  "item.policy": _withCtx(({ item }) => [
                                    _createTextVNode(_toDisplayString(torrentPolicy(item)), 1)
                                  ]),
                                  "no-data": _withCtx(() => _cache[52] || (_cache[52] = [
                                    _createElementVNode("div", { class: "brushflow-table-empty" }, "当前筛选下没有种子记录", -1)
                                  ])),
                                  _: 1
                                }, 8, ["items", "loading"]),
                                _createElementVNode("div", _hoisted_27, [
                                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(torrentData.value.items, (item) => {
                                    return (_openBlock(), _createElementBlock("article", {
                                      key: `${item.task_id}-${item.title}-${item.time}`,
                                      class: "brushflow-mobile-torrent"
                                    }, [
                                      _createElementVNode("div", _hoisted_28, [
                                        _createElementVNode("strong", null, _toDisplayString(item.title || '未知种子'), 1),
                                        _createVNode(_component_VChip, {
                                          size: "x-small",
                                          variant: "tonal"
                                        }, {
                                          default: _withCtx(() => [
                                            _createTextVNode(_toDisplayString(torrentStateText(item)), 1)
                                          ]),
                                          _: 2
                                        }, 1024)
                                      ]),
                                      _createElementVNode("div", _hoisted_29, [
                                        _createElementVNode("span", null, _toDisplayString(_unref(formatBytes)(item.size)), 1),
                                        _createElementVNode("span", null, "上传 " + _toDisplayString(_unref(formatBytes)(item.uploaded)), 1),
                                        _createElementVNode("span", null, "分享率 " + _toDisplayString(Number(item.ratio || 0).toFixed(2)), 1)
                                      ]),
                                      _createElementVNode("div", _hoisted_30, _toDisplayString(torrentPolicy(item)), 1)
                                    ]))
                                  }), 128)),
                                  (!torrentData.value.items.length)
                                    ? (_openBlock(), _createElementBlock("div", _hoisted_31, "当前筛选下没有种子记录"))
                                    : _createCommentVNode("", true)
                                ]),
                                (totalTorrentPages.value > 1)
                                  ? (_openBlock(), _createBlock(_component_VPagination, {
                                      key: 0,
                                      "model-value": torrentPage.value,
                                      length: totalTorrentPages.value,
                                      "total-visible": 5,
                                      density: "comfortable",
                                      "onUpdate:modelValue": changeTorrentPage
                                    }, null, 8, ["model-value", "length"]))
                                  : _createCommentVNode("", true)
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_VWindowItem, { value: "diagnostics" }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_32, [
                              _createElementVNode("div", null, [
                                _createElementVNode("div", _hoisted_33, _toDisplayString(latestBrushRun.value ? `刷流刷新 #${latestBrushRun.value.id.slice(0, 8)}` : '暂无刷流刷新记录'), 1),
                                _createElementVNode("div", _hoisted_34, _toDisplayString(latestBrushRun.value ? `${_unref(formatDateTime)(latestBrushRun.value.started_at)} · ${_unref(formatDuration)(latestBrushRun.value.started_at, latestBrushRun.value.finished_at)}` : '执行一次任务后将显示筛选流水线和过滤原因'), 1)
                              ]),
                              (latestBrushRun.value)
                                ? (_openBlock(), _createBlock(_component_VChip, {
                                    key: 0,
                                    color: latestBrushRun.value.success === false ? 'error' : 'success',
                                    variant: "tonal"
                                  }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(latestBrushRun.value.success === false ? '失败' : '完成'), 1)
                                    ]),
                                    _: 1
                                  }, 8, ["color"]))
                                : _createCommentVNode("", true)
                            ]),
                            _createElementVNode("div", _hoisted_35, [
                              _createVNode(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: _withCtx(() => [
                                  _cache[53] || (_cache[53] = _createElementVNode("header", { class: "brushflow-panel__head" }, [
                                    _createElementVNode("div", null, [
                                      _createElementVNode("div", { class: "text-subtitle-1 font-weight-medium" }, "选种流水线"),
                                      _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "本轮候选在各阶段的剩余数量")
                                    ])
                                  ], -1)),
                                  _createElementVNode("ol", _hoisted_36, [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(pipelineStages.value, (stage, index) => {
                                      return (_openBlock(), _createElementBlock("li", {
                                        key: stage.title
                                      }, [
                                        _createElementVNode("span", _hoisted_37, _toDisplayString(index + 1), 1),
                                        _createElementVNode("div", null, [
                                          _createElementVNode("strong", null, _toDisplayString(stage.title), 1),
                                          _createElementVNode("span", null, _toDisplayString(stage.detail), 1)
                                        ]),
                                        _createVNode(_component_VChip, {
                                          size: "small",
                                          variant: "tonal"
                                        }, {
                                          default: _withCtx(() => [
                                            _createTextVNode(_toDisplayString(stage.count), 1)
                                          ]),
                                          _: 2
                                        }, 1024)
                                      ]))
                                    }), 128))
                                  ])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: _withCtx(() => [
                                  _cache[54] || (_cache[54] = _createElementVNode("header", { class: "brushflow-panel__head" }, [
                                    _createElementVNode("div", null, [
                                      _createElementVNode("div", { class: "text-subtitle-1 font-weight-medium" }, "过滤原因"),
                                      _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "本轮未进入下载器的候选分布")
                                    ])
                                  ], -1)),
                                  (reasonEntries.value.length)
                                    ? (_openBlock(), _createElementBlock("div", _hoisted_38, [
                                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(reasonEntries.value, (item) => {
                                          return (_openBlock(), _createElementBlock("div", {
                                            key: item.label,
                                            class: "brushflow-reason"
                                          }, [
                                            _createElementVNode("div", null, [
                                              _createElementVNode("span", null, _toDisplayString(item.label), 1),
                                              _createElementVNode("strong", null, _toDisplayString(item.count), 1)
                                            ]),
                                            _createElementVNode("span", _hoisted_39, [
                                              _createElementVNode("i", {
                                                style: _normalizeStyle({ width: `${(item.count / maxReasonCount.value) * 100}%` })
                                              }, null, 4)
                                            ])
                                          ]))
                                        }), 128))
                                      ]))
                                    : (_openBlock(), _createElementBlock("div", _hoisted_40, "本轮没有记录过滤原因"))
                                ]),
                                _: 1
                              })
                            ]),
                            _createVNode(_component_VSheet, {
                              tag: "section",
                              class: "brushflow-panel app-surface-static"
                            }, {
                              default: _withCtx(() => [
                                _cache[55] || (_cache[55] = _createElementVNode("header", { class: "brushflow-panel__head" }, [
                                  _createElementVNode("div", null, [
                                    _createElementVNode("div", { class: "text-subtitle-1 font-weight-medium" }, "最近事件"),
                                    _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "刷流刷新与种子检查独立记录")
                                  ])
                                ], -1)),
                                _createElementVNode("div", _hoisted_41, [
                                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(taskRuns.value, (run) => {
                                    return (_openBlock(), _createElementBlock("article", {
                                      key: run.id
                                    }, [
                                      _createVNode(_component_VIcon, {
                                        icon: run.success === false ? 'mdi-alert-circle-outline' : run.kind === 'brush' ? 'mdi-sync' : 'mdi-progress-check',
                                        color: run.success === false ? 'error' : run.kind === 'brush' ? 'primary' : 'info'
                                      }, null, 8, ["icon", "color"]),
                                      _createElementVNode("div", null, [
                                        _createElementVNode("strong", null, _toDisplayString(run.kind === 'brush' ? '刷流刷新' : '种子检查'), 1),
                                        _createElementVNode("span", null, _toDisplayString(_unref(formatDateTime)(run.started_at)) + " · " + _toDisplayString(_unref(formatDuration)(run.started_at, run.finished_at)) + " · " + _toDisplayString(run.kind === 'brush' ? `新增 ${run.added_count || 0}，过滤 ${run.filtered_count || 0}` : `活跃 ${run.active_count || 0}，删除 ${run.deleted_count || 0}`), 1),
                                        (run.error)
                                          ? (_openBlock(), _createElementBlock("span", _hoisted_42, _toDisplayString(run.error), 1))
                                          : _createCommentVNode("", true)
                                      ])
                                    ]))
                                  }), 128)),
                                  (!taskRuns.value.length)
                                    ? (_openBlock(), _createElementBlock("div", _hoisted_43, "暂无运行事件"))
                                    : _createCommentVNode("", true)
                                ])
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_VWindowItem, { value: "config" }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_44, [
                              _createVNode(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: _withCtx(() => [
                                  _cache[68] || (_cache[68] = _createElementVNode("header", { class: "brushflow-panel__head" }, [
                                    _createElementVNode("div", null, [
                                      _createElementVNode("div", { class: "text-subtitle-1 font-weight-medium" }, "任务规则"),
                                      _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "当前服务端生效配置")
                                    ])
                                  ], -1)),
                                  _createElementVNode("dl", _hoisted_45, [
                                    _createElementVNode("div", null, [
                                      _cache[56] || (_cache[56] = _createElementVNode("dt", null, "任务状态", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(selectedTask.value.enabled ? '启用' : '暂停'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[57] || (_cache[57] = _createElementVNode("dt", null, "通知", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.notify ? '发送' : '关闭'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[58] || (_cache[58] = _createElementVNode("dt", null, "站点", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(selectedTask.value.site_name), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[59] || (_cache[59] = _createElementVNode("dt", null, "下载器", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(selectedTask.value.downloader), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[60] || (_cache[60] = _createElementVNode("dt", null, "种子大小", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.size || '不限'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[61] || (_cache[61] = _createElementVNode("dt", null, "做种人数", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.seeder || '不限'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[62] || (_cache[62] = _createElementVNode("dt", null, "发布时间", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.pubtime ? `${taskConfig.value.pubtime} 分钟` : '不限'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[63] || (_cache[63] = _createElementVNode("dt", null, "排除 H&R", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.hr === 'yes' ? '是' : '否'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[64] || (_cache[64] = _createElementVNode("dt", null, "包含规则", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.include || '无'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[65] || (_cache[65] = _createElementVNode("dt", null, "排除规则", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.exclude || '无'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[66] || (_cache[66] = _createElementVNode("dt", null, "保种上限", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.disksize ? `${taskConfig.value.disksize} GB` : '不限'), 1)
                                    ]),
                                    _createElementVNode("div", null, [
                                      _cache[67] || (_cache[67] = _createElementVNode("dt", null, "归档天数", -1)),
                                      _createElementVNode("dd", null, _toDisplayString(taskConfig.value.auto_archive_days || '不自动归档'), 1)
                                    ])
                                  ])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_VSheet, {
                                tag: "section",
                                class: "brushflow-panel app-surface-static"
                              }, {
                                default: _withCtx(() => [
                                  _cache[75] || (_cache[75] = _createElementVNode("header", { class: "brushflow-panel__head" }, [
                                    _createElementVNode("div", null, [
                                      _createElementVNode("div", { class: "text-subtitle-1 font-weight-medium" }, "任务数据"),
                                      _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "以下操作只影响当前任务")
                                    ])
                                  ], -1)),
                                  _createElementVNode("div", _hoisted_46, [
                                    _createElementVNode("div", null, [
                                      _cache[70] || (_cache[70] = _createElementVNode("strong", null, "清除统计与记录", -1)),
                                      _cache[71] || (_cache[71] = _createElementVNode("span", null, "下载器中的任务标签种子会在下次检查时重新纳入", -1)),
                                      _createVNode(_component_VBtn, {
                                        color: "warning",
                                        variant: "tonal",
                                        "prepend-icon": "mdi-eraser",
                                        onClick: _cache[10] || (_cache[10] = $event => (clearDialog.value = true))
                                      }, {
                                        default: _withCtx(() => _cache[69] || (_cache[69] = [
                                          _createTextVNode("清除数据")
                                        ])),
                                        _: 1
                                      })
                                    ]),
                                    _createVNode(_component_VDivider),
                                    _createElementVNode("div", null, [
                                      _cache[73] || (_cache[73] = _createElementVNode("strong", null, "删除任务", -1)),
                                      _cache[74] || (_cache[74] = _createElementVNode("span", null, "存在活跃种子时后端会拒绝删除，避免留下失管任务", -1)),
                                      _createVNode(_component_VBtn, {
                                        color: "error",
                                        variant: "tonal",
                                        "prepend-icon": "mdi-delete-outline",
                                        onClick: _cache[11] || (_cache[11] = $event => (deleteDialog.value = true))
                                      }, {
                                        default: _withCtx(() => _cache[72] || (_cache[72] = [
                                          _createTextVNode("删除任务")
                                        ])),
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
                : _createCommentVNode("", true)
            ])
          ], 64)),
    _createVNode(TaskEditorDialog, {
      modelValue: editorOpen.value,
      "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((editorOpen).value = $event)),
      task: editorTask.value,
      sites: status.value.options.sites,
      downloaders: status.value.options.downloaders,
      saving: saving.value,
      onSave: saveTask
    }, null, 8, ["modelValue", "task", "sites", "downloaders", "saving"]),
    _createVNode(_component_VDialog, {
      modelValue: deleteDialog.value,
      "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((deleteDialog).value = $event)),
      "max-width": "28rem"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, { title: "删除刷流任务" }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardText, null, {
              default: _withCtx(() => [
                _createTextVNode("确认删除“" + _toDisplayString(selectedTask.value?.name) + "”？存在活跃种子时不会执行删除。", 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VCardActions, null, {
              default: _withCtx(() => [
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  onClick: _cache[14] || (_cache[14] = $event => (deleteDialog.value = false))
                }, {
                  default: _withCtx(() => _cache[76] || (_cache[76] = [
                    _createTextVNode("取消")
                  ])),
                  _: 1
                }),
                _createVNode(_component_VBtn, {
                  color: "error",
                  variant: "flat",
                  loading: saving.value,
                  onClick: confirmDeleteTask
                }, {
                  default: _withCtx(() => _cache[77] || (_cache[77] = [
                    _createTextVNode("删除")
                  ])),
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
    _createVNode(_component_VDialog, {
      modelValue: clearDialog.value,
      "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((clearDialog).value = $event)),
      "max-width": "28rem"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, { title: "清除任务数据" }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardText, null, {
              default: _withCtx(() => _cache[78] || (_cache[78] = [
                _createTextVNode("将清除当前任务的统计、运行诊断、托管和归档记录，下载器内的种子与文件不会删除。")
              ])),
              _: 1
            }),
            _createVNode(_component_VCardActions, null, {
              default: _withCtx(() => [
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  onClick: _cache[16] || (_cache[16] = $event => (clearDialog.value = false))
                }, {
                  default: _withCtx(() => _cache[79] || (_cache[79] = [
                    _createTextVNode("取消")
                  ])),
                  _: 1
                }),
                _createVNode(_component_VBtn, {
                  color: "warning",
                  variant: "flat",
                  loading: saving.value,
                  onClick: confirmClearTask
                }, {
                  default: _withCtx(() => _cache[80] || (_cache[80] = [
                    _createTextVNode("清除")
                  ])),
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
const BrushFlowWorkbench = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-0ad7c951"]]);

export { BrushFlowWorkbench as B };
