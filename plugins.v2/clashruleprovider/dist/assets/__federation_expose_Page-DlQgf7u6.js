import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,withModifiers:_withModifiers,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1 = { class: "plugin-page" };
const _hoisted_2 = { key: 2 };
const _hoisted_3 = { class: "mb-6" };
const _hoisted_4 = { class: "d-flex justify-space-between align-center mb-4" };
const _hoisted_5 = ["onDragstart", "onDragover", "onDrop"];
const _hoisted_6 = { class: "mb-6" };
const _hoisted_7 = { class: "d-flex justify-space-between align-center mb-4" };
const _hoisted_8 = ["onDragstart", "onDragover", "onDrop"];
const _hoisted_9 = { class: "d-flex justify-space-between mb-2" };
const _hoisted_10 = { class: "d-flex justify-space-between mb-2" };
const _hoisted_11 = { class: "d-flex justify-space-between text-caption text-grey" };
const _hoisted_12 = { class: "d-flex justify-space-between align-center mb-2" };
const _hoisted_13 = {
  key: 0,
  class: "url-display"
};
const _hoisted_14 = ["href"];
const _hoisted_15 = {
  key: 1,
  class: "text-grey"
};

const {ref,onMounted,computed} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
  props: {
  model: {
    type: Object,
    default: () => {
    },
  },
  api: {
    type: Object,
    default: () => {
    },
  },
},
  emits: ['action', 'switch', 'close'],
  setup(__props, { emit: __emit }) {

const expansionPanels = ref(null);
const snackbar = ref({
  show: false,
  message: '',
  color: 'success'
});
const dragItem = ref(null);
// 添加自定义出站状态
const customOutbounds = ref([]);
const additionalParamOptions = ref([
  {title: '无', value: ''},
  {title: 'no-resolve', value: 'no-resolve'},
  {title: 'src', value: 'src'}
]);
// 新增状态变量
const subUrl = ref('');

function dragStart(event, priority, type = 'top') {
  dragItem.value = {priority, type};
  event.dataTransfer.effectAllowed = 'move';
}

function dragOver(event, priority, type = 'top') {
  event.preventDefault();
  const currentRules = type === 'top' ? rules.value : ruleset_rules.value;
  // 高亮当前悬停行
  currentRules.forEach(rule => {
    rule._isHovered = (rule.priority === priority);
  });
}

async function drop(event, targetPriority, type = 'top') {
  // 5. 调用 API 提交
  await props.api.put('/plugin/ClashRuleProvider/reorder-rules', {
    moved_priority: dragItem.value.priority,
    target_priority: targetPriority,
    rule_data: dragItem.value,
    type: type
  });
  await refreshData(); // 失败时恢复数据
  dragItem.value = null;
}

// 接收初始配置
const props = __props;

// 组件状态
const loading = ref(true);
const error = ref(null);
const rules = ref([]);
const ruleset_rules = ref([]);
const status = ref('running');
const rulesetPrefix = ref('Custom_');
const lastUpdated = ref('');
const updatingSubscription = ref(false);
const subscriptionUrl = ref('');

// 规则编辑相关状态
const ruleDialog = ref(false);
const editingPriority = ref(null);
const editingType = ref('top'); // 记录当前编辑的规则类型（'top' 或 'ruleset'）
const newRule = ref({
  type: 'DOMAIN-SUFFIX',
  payload: '',
  action: 'DIRECT',
  additional_params: '',
  priority: 0
});

// 排序后的规则
const sortedRules = computed(() => [...rules.value].sort((a, b) => a.priority - b.priority));
const sortedRulesetRules = computed(() => [...ruleset_rules.value].sort((a, b) => a.priority - b.priority));
const showAdditionalParams = computed(() => {
  return ['IP-CIDR', 'IP-CIDR6', 'IP-ASN', 'GEOIP'].includes(newRule.value.type);
});
const ruleProviders = ref([]);
const ruleProviderNames = computed(() => Object.keys(ruleProviders.value));
// 规则类型和动作选项
const ruleTypes = computed(() => {
  const allTypes = [
    'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'DOMAIN-REGEX', 'GEOSITE',
    'IP-CIDR', 'IP-CIDR6', 'IP-SUFFIX', 'IP-ASN', 'GEOIP',
    'SRC-GEOIP', 'SRC-IP-ASN', 'SRC-IP-CIDR', 'SRC-IP-SUFFIX',
    'DST-PORT', 'SRC-PORT', 'IN-PORT', 'IN-TYPE', 'IN-USER', 'IN-NAME',
    'PROCESS-PATH', 'PROCESS-PATH-REGEX', 'PROCESS-NAME', 'PROCESS-NAME-REGEX',
    'UID', 'NETWORK', 'DSCP', 'RULE-SET', 'AND', 'OR', 'NOT', 'SUB-RULE', 'MATCH'
  ];

  // 如果是 ruleset 规则，过滤掉 SUB-RULE 和 RULE-SET
  if (editingType.value === 'ruleset') {
    return allTypes.filter(type => !['SUB-RULE', 'RULE-SET'].includes(type));
  }

  return allTypes;
});
// 修改actions为计算属性，合并内置动作和自定义出站
const actions = computed(() => [
  'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS', 'COMPATIBLE',
  ...customOutbounds.value.map(outbound => outbound.name)
]);
const subscriptionInfo = ref({
  download: 0,
  upload: 0,
  total: 0,
  expire: 0,
  last_update: 0,
  used_percentage: 0,
  rule_size: 0
});
// 自定义事件，用于通知主应用刷新数据
const emit = __emit;

// 格式化字节为易读单位（如 1.5 GB）
function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 在工具函数中添加时间戳转换
function formatTimestamp(timestamp) {
  if (!timestamp) return 'N/A';
  const date = new Date(timestamp * 1000); // 注意：JS时间戳是毫秒，需乘以1000
  return date.toLocaleString(); // 或使用其他格式如 date.toISOString().split('T')[0]
}

// 更新过期时间颜色判断（基于时间戳）
function getExpireColor(timestamp) {
  if (!timestamp) return 'grey';
  const secondsLeft = timestamp - Math.floor(Date.now() / 1000);
  const daysLeft = secondsLeft / 86400;
  return daysLeft < 7 ? 'error' : daysLeft < 30 ? 'warning' : 'success';
}

// 复制功能
function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    snackbar.value = {
      show: true,
      message: '已复制到剪贴板',
      color: 'success'
    };
  }).catch(() => {
    snackbar.value = {
      show: true,
      message: '复制失败',
      color: 'error'
    };
  });
}

// 计算已用流量百分比
function calculatePercentage(download, total) {
  return total > 0 ? Math.round((download / total) * 100) : 0;
}

// 根据流量百分比获取颜色
function getUsageColor(percentage) {
  return percentage > 90 ? 'error' : percentage > 70 ? 'warning' : 'success';
}

// 获取动作对应的颜色
function getActionColor(action) {
  const colors = {
    'DIRECT': 'success',
    'REJECT': 'error',
    'REJECT-DROP': 'error',
    'PASS': 'warning',
    'COMPATIBLE': 'info'
  };
  return colors[action] || 'primary'
}

function isSystemRule(rule) {
  return rule.payload?.startsWith(rulesetPrefix.value);
}

// 打开添加规则对话框
function openAddRuleDialog(type = 'top') {
  editingPriority.value = null;
  editingType.value = type;
  const currentRules = type === 'top' ? sortedRules.value : sortedRulesetRules.value;
  const nextPriority = currentRules.length > 0
      ? Math.max(...currentRules.map(r => r.priority)) + 1
      : 0;

  newRule.value = {
    type: 'DOMAIN-SUFFIX',
    payload: '',
    action: 'DIRECT',
    additional_params: '',
    priority: nextPriority
  };

  ruleDialog.value = true;
}

// 编辑规则
function editRule(priority, type = 'top') {
  editingType.value = type; // 记录当前编辑的类型
  const currentRules = type === 'top' ? sortedRules.value : sortedRulesetRules.value;
  const rule = currentRules.find(r => r.priority === priority);

  if (rule) {
    editingPriority.value = priority;
    newRule.value = {
      type: rule.type,
      payload: rule.payload,
      action: rule.action,
      additional_params: rule.additional_params?.join(', ') || '',
      priority: rule.priority
    };
    ruleDialog.value = true;
  }
}

// 保存规则
async function saveRule() {
  try {
    const requestData = {
      type: editingType.value, // "top" 或 "ruleset"
      rule_data: {
        ...newRule.value,
        additional_params: newRule.value.additional_params
            ? newRule.value.additional_params.split(',').map(param => param.trim()).filter(param => param)
            : []
      }
    };

    const method = editingPriority.value === null ? 'post' : 'put';
    await props.api[method]('/plugin/ClashRuleProvider/rule', requestData);

    ruleDialog.value = false;
    await refreshData();

    // 显示成功提示
    snackbar.value = {
      show: true,
      message: editingPriority.value === null ? '规则添加成功' : '规则更新成功',
      color: 'success'
    };
  } catch (err) {
    console.error('保存规则失败:', err);
    error.value = err.message || '保存规则失败';
    snackbar.value = {
      show: true,
      message: '保存规则失败: ' + (err.message || '未知错误'),
      color: 'error'
    };
  }
}

// 删除规则
async function deleteRule(priority, type = 'top') {
  try {
    await props.api.delete('/plugin/ClashRuleProvider/rule', {
      data: {
        type: type,          // 规则类型
        priority: priority   // 要删除的规则优先级
      }
    });
    await refreshData();
  } catch (err) {
    error.value = err.message || '删除规则失败';
  }
}


// 更新订阅
async function updateSubscription() {
  if (!subscriptionUrl.value) {
    error.value = '请先输入订阅URL';
    return
  }

  updatingSubscription.value = true;
  try {
    await props.api.put('plugin/ClashRuleProvider/subscription', {
      url: subscriptionUrl.value
    });
    // 显示成功提示
    snackbar.value = {
      show: true,
      message: '订阅更新成功',
      color: 'success'
    };
    await refreshData();
  } catch (err) {
    console.error('更新订阅失败:', err);
    error.value = err.message;
  } finally {
    updatingSubscription.value = false;
  }
}


// 获取和刷新数据
async function refreshData() {
  loading.value = true;
  error.value = null;
  const wasPanelOpen = expansionPanels.value === (0); // 检查订阅面板是否展开
  try {
    const state = await props.api.get('/plugin/ClashRuleProvider/status');
    status.value = state?.data?.state ? 'running' : 'disabled';
    subUrl.value = state?.data?.sub_url || ''; // 从API获取订阅URL
    // 更新订阅信息
    if (state?.data?.subscription_info) {
      subscriptionInfo.value = {
        ...state.data.subscription_info,
        used_percentage: calculatePercentage(
            state.data.subscription_info.download,
            state.data.subscription_info.total
        ),
        rule_size: state?.data?.clash?.rule_size
      };
    }
    rulesetPrefix.value = state?.data?.ruleset_prefix || 'Custom_';
    // 直接从响应中获取规则数组
    const response = await props.api.get('/plugin/ClashRuleProvider/rules?rule_type=top');
    rules.value = response?.data.rules || [];

    const response_ruleset = await props.api.get('/plugin/ClashRuleProvider/rules?rule_type=ruleset');
    ruleset_rules.value = response_ruleset?.data.rules || [];

    // 获取订阅信息
    const subscription = await props.api.get('/plugin/ClashRuleProvider/subscription');
    subscriptionUrl.value = subscription?.data.url;
    // 获取自定义出站
    const outboundsResponse = await props.api.get('/plugin/ClashRuleProvider/clash_outbound');
    customOutbounds.value = outboundsResponse?.data.outbound || [];

    const providersResponse = await props.api.get('/plugin/ClashRuleProvider/rule_providers');
    ruleProviders.value = providersResponse?.data || {};

    lastUpdated.value = new Date().toLocaleString();
    // 刷新后恢复面板状态
    if (wasPanelOpen && !(expansionPanels.value === 0)) {
      expansionPanels.value = 0;
    }
  } catch (err) {
    console.error('获取数据失败:', err);
    error.value = err.message || '获取数据失败';
    status.value = 'error';
  } finally {
    loading.value = false;
    emit('action');
  }
}

// 通知主应用切换到配置页面
function notifySwitch() {
  emit('switch');
}

// 通知主应用关闭组件
function notifyClose() {
  emit('close');
}

// 组件挂载时加载数据
onMounted(() => {
  refreshData();
});

return (_ctx, _cache) => {
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_skeleton_loader = _resolveComponent("v-skeleton-loader");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_table = _resolveComponent("v-table");
  const _component_v_tooltip = _resolveComponent("v-tooltip");
  const _component_v_expansion_panel_title = _resolveComponent("v-expansion-panel-title");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_expansion_panel_text = _resolveComponent("v-expansion-panel-text");
  const _component_v_expansion_panel = _resolveComponent("v-expansion-panel");
  const _component_v_expansion_panels = _resolveComponent("v-expansion-panels");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
  const _component_v_snackbar = _resolveComponent("v-snackbar");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_dialog = _resolveComponent("v-dialog");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, null, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_item, null, {
          append: _withCtx(() => [
            _createVNode(_component_v_btn, {
              icon: "",
              color: "primary",
              variant: "text",
              onClick: notifyClose
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, { left: "" }, {
                  default: _withCtx(() => _cache[15] || (_cache[15] = [
                    _createTextVNode("mdi-close")
                  ])),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, null, {
              default: _withCtx(() => _cache[14] || (_cache[14] = [
                _createTextVNode("Clash Rule Provider")
              ])),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_text, null, {
          default: _withCtx(() => [
            (error.value)
              ? (_openBlock(), _createBlock(_component_v_alert, {
                  key: 0,
                  type: "error",
                  class: "mb-4"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(error.value), 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (loading.value)
              ? (_openBlock(), _createBlock(_component_v_skeleton_loader, {
                  key: 1,
                  type: "card"
                }))
              : (_openBlock(), _createElementBlock("div", _hoisted_2, [
                  _createElementVNode("div", _hoisted_3, [
                    _createElementVNode("div", _hoisted_4, [
                      _cache[18] || (_cache[18] = _createElementVNode("div", { class: "text-h6" }, "规则集规则", -1)),
                      _createVNode(_component_v_btn, {
                        color: "primary",
                        onClick: _cache[0] || (_cache[0] = $event => (openAddRuleDialog('ruleset')))
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { left: "" }, {
                            default: _withCtx(() => _cache[16] || (_cache[16] = [
                              _createTextVNode("mdi-plus")
                            ])),
                            _: 1
                          }),
                          _cache[17] || (_cache[17] = _createTextVNode(" 添加规则 "))
                        ]),
                        _: 1
                      })
                    ]),
                    _createVNode(_component_v_table, {
                      density: "compact",
                      hover: ""
                    }, {
                      default: _withCtx(() => [
                        _cache[22] || (_cache[22] = _createElementVNode("thead", null, [
                          _createElementVNode("tr", null, [
                            _createElementVNode("th", null, "优先级"),
                            _createElementVNode("th", null, "类型"),
                            _createElementVNode("th", null, "内容"),
                            _createElementVNode("th", null, "出站"),
                            _createElementVNode("th", null, "规则集"),
                            _createElementVNode("th", null, "操作")
                          ])
                        ], -1)),
                        _createElementVNode("tbody", null, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(sortedRulesetRules.value, (rule) => {
                            return (_openBlock(), _createElementBlock("tr", {
                              key: rule.priority,
                              class: _normalizeClass({ 'bg-blue-lighten-5': rule._isHovered }),
                              draggable: "true",
                              onDragstart: $event => (dragStart($event, rule.priority, 'ruleset')),
                              onDragover: _withModifiers($event => (dragOver($event, rule.priority, 'ruleset')), ["prevent"]),
                              onDrop: $event => (drop($event, rule.priority, 'ruleset'))
                            }, [
                              _createElementVNode("td", null, [
                                _createVNode(_component_v_icon, { class: "drag-handle" }, {
                                  default: _withCtx(() => _cache[19] || (_cache[19] = [
                                    _createTextVNode("mdi-drag")
                                  ])),
                                  _: 1
                                }),
                                _createTextVNode(" " + _toDisplayString(rule.priority), 1)
                              ]),
                              _createElementVNode("td", null, _toDisplayString(rule.type), 1),
                              _createElementVNode("td", null, _toDisplayString(rule.payload), 1),
                              _createElementVNode("td", null, [
                                _createVNode(_component_v_chip, {
                                  color: getActionColor(rule.action),
                                  size: "small"
                                }, {
                                  default: _withCtx(() => [
                                    _createTextVNode(_toDisplayString(rule.action), 1)
                                  ]),
                                  _: 2
                                }, 1032, ["color"])
                              ]),
                              _createElementVNode("td", null, _toDisplayString(rulesetPrefix.value) + _toDisplayString(rule.action), 1),
                              _createElementVNode("td", null, [
                                _createVNode(_component_v_btn, {
                                  icon: "",
                                  size: "small",
                                  color: "primary",
                                  variant: "text",
                                  onClick: $event => (editRule(rule.priority, 'ruleset'))
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_icon, null, {
                                      default: _withCtx(() => _cache[20] || (_cache[20] = [
                                        _createTextVNode("mdi-pencil")
                                      ])),
                                      _: 1
                                    })
                                  ]),
                                  _: 2
                                }, 1032, ["onClick"]),
                                _createVNode(_component_v_btn, {
                                  icon: "",
                                  size: "small",
                                  color: "error",
                                  variant: "text",
                                  onClick: $event => (deleteRule(rule.priority, 'ruleset'))
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_icon, null, {
                                      default: _withCtx(() => _cache[21] || (_cache[21] = [
                                        _createTextVNode("mdi-delete")
                                      ])),
                                      _: 1
                                    })
                                  ]),
                                  _: 2
                                }, 1032, ["onClick"])
                              ])
                            ], 42, _hoisted_5))
                          }), 128))
                        ])
                      ]),
                      _: 1
                    }),
                    _cache[23] || (_cache[23] = _createElementVNode("div", { class: "text-caption text-grey mt-2" }, " *对规则集中规则的修改可以在Clash中立即生效。 ", -1))
                  ]),
                  _createElementVNode("div", _hoisted_6, [
                    _createElementVNode("div", _hoisted_7, [
                      _cache[26] || (_cache[26] = _createElementVNode("div", { class: "text-h6" }, "置顶规则", -1)),
                      _createVNode(_component_v_btn, {
                        color: "primary",
                        onClick: _cache[1] || (_cache[1] = $event => (openAddRuleDialog('top')))
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { left: "" }, {
                            default: _withCtx(() => _cache[24] || (_cache[24] = [
                              _createTextVNode("mdi-plus")
                            ])),
                            _: 1
                          }),
                          _cache[25] || (_cache[25] = _createTextVNode(" 添加规则 "))
                        ]),
                        _: 1
                      })
                    ]),
                    _createVNode(_component_v_table, {
                      density: "compact",
                      hover: ""
                    }, {
                      default: _withCtx(() => [
                        _cache[31] || (_cache[31] = _createElementVNode("thead", null, [
                          _createElementVNode("tr", null, [
                            _createElementVNode("th", null, "优先级"),
                            _createElementVNode("th", null, "类型"),
                            _createElementVNode("th", null, "内容"),
                            _createElementVNode("th", null, "出站"),
                            _createElementVNode("th", null, "操作")
                          ])
                        ], -1)),
                        _createElementVNode("tbody", null, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(sortedRules.value, (rule) => {
                            return (_openBlock(), _createElementBlock("tr", {
                              key: rule.priority,
                              class: _normalizeClass({ 'bg-blue-lighten-5': rule._isHovered }),
                              draggable: "true",
                              onDragstart: $event => (dragStart($event, rule.priority, 'top')),
                              onDragover: _withModifiers($event => (dragOver($event, rule.priority, 'top')), ["prevent"]),
                              onDrop: $event => (drop($event, rule.priority, 'top'))
                            }, [
                              _createElementVNode("td", null, [
                                _createVNode(_component_v_icon, { class: "drag-handle" }, {
                                  default: _withCtx(() => _cache[27] || (_cache[27] = [
                                    _createTextVNode("mdi-drag")
                                  ])),
                                  _: 1
                                }),
                                _createTextVNode(" " + _toDisplayString(rule.priority), 1)
                              ]),
                              _createElementVNode("td", null, _toDisplayString(rule.type), 1),
                              _createElementVNode("td", null, _toDisplayString(rule.payload), 1),
                              _createElementVNode("td", null, [
                                _createVNode(_component_v_chip, {
                                  color: getActionColor(rule.action),
                                  size: "small"
                                }, {
                                  default: _withCtx(() => [
                                    _createTextVNode(_toDisplayString(rule.action), 1)
                                  ]),
                                  _: 2
                                }, 1032, ["color"])
                              ]),
                              _createElementVNode("td", null, [
                                _createVNode(_component_v_btn, {
                                  icon: "",
                                  size: "small",
                                  color: "primary",
                                  variant: "text",
                                  onClick: $event => (editRule(rule.priority, 'top')),
                                  disabled: isSystemRule(rule)
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_icon, null, {
                                      default: _withCtx(() => _cache[28] || (_cache[28] = [
                                        _createTextVNode("mdi-pencil")
                                      ])),
                                      _: 1
                                    })
                                  ]),
                                  _: 2
                                }, 1032, ["onClick", "disabled"]),
                                _createVNode(_component_v_btn, {
                                  icon: "",
                                  size: "small",
                                  color: "error",
                                  variant: "text",
                                  onClick: $event => (deleteRule(rule.priority, 'top')),
                                  disabled: isSystemRule(rule)
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_icon, null, {
                                      default: _withCtx(() => _cache[29] || (_cache[29] = [
                                        _createTextVNode("mdi-delete")
                                      ])),
                                      _: 1
                                    })
                                  ]),
                                  _: 2
                                }, 1032, ["onClick", "disabled"]),
                                (isSystemRule(rule))
                                  ? (_openBlock(), _createBlock(_component_v_tooltip, {
                                      key: 0,
                                      activator: "parent",
                                      location: "top"
                                    }, {
                                      default: _withCtx(() => _cache[30] || (_cache[30] = [
                                        _createTextVNode(" 根据规则集自动添加 ")
                                      ])),
                                      _: 1
                                    }))
                                  : _createCommentVNode("", true)
                              ])
                            ], 42, _hoisted_8))
                          }), 128))
                        ])
                      ]),
                      _: 1
                    }),
                    _cache[32] || (_cache[32] = _createElementVNode("div", { class: "text-caption text-grey mt-2" }, " *置顶规则用于管理来自规则集的匹配规则，这些规则会动态更新。 ", -1)),
                    _cache[33] || (_cache[33] = _createElementVNode("div", { class: "text-caption text-grey mt-2" }, " *对置顶规则的修改只有Clash更新配置后才会生效。 ", -1))
                  ]),
                  _createVNode(_component_v_expansion_panels, {
                    modelValue: expansionPanels.value,
                    "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((expansionPanels).value = $event))
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_expansion_panel, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_expansion_panel_title, null, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_icon, { left: "" }, {
                                default: _withCtx(() => _cache[34] || (_cache[34] = [
                                  _createTextVNode("mdi-cloud-download")
                                ])),
                                _: 1
                              }),
                              _cache[35] || (_cache[35] = _createElementVNode("span", null, "订阅管理", -1)),
                              (subscriptionInfo.value.last_update)
                                ? (_openBlock(), _createBlock(_component_v_chip, {
                                    key: 0,
                                    size: "small",
                                    color: "light-blue",
                                    class: "ml-2"
                                  }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(formatTimestamp(subscriptionInfo.value.last_update)), 1)
                                    ]),
                                    _: 1
                                  }))
                                : _createCommentVNode("", true),
                              (subscriptionInfo.value.expire)
                                ? (_openBlock(), _createBlock(_component_v_chip, {
                                    key: 1,
                                    size: "small",
                                    color: getExpireColor(subscriptionInfo.value.expire),
                                    class: "ml-2"
                                  }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(formatTimestamp(subscriptionInfo.value.expire)), 1)
                                    ]),
                                    _: 1
                                  }, 8, ["color"]))
                                : _createCommentVNode("", true)
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_expansion_panel_text, null, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_text_field, {
                                modelValue: subscriptionUrl.value,
                                "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((subscriptionUrl).value = $event)),
                                label: "订阅URL",
                                placeholder: "https://example.com/clash-rules.txt",
                                class: "mb-4",
                                readonly: "",
                                loading: loading.value
                              }, null, 8, ["modelValue", "loading"]),
                              _createVNode(_component_v_card, {
                                variant: "outlined",
                                class: "mb-4"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_card_text, null, {
                                    default: _withCtx(() => [
                                      _createElementVNode("div", _hoisted_9, [
                                        _cache[36] || (_cache[36] = _createElementVNode("span", null, "已用流量：", -1)),
                                        _createElementVNode("strong", null, _toDisplayString(formatBytes(subscriptionInfo.value.download + subscriptionInfo.value.upload)), 1)
                                      ]),
                                      _createElementVNode("div", _hoisted_10, [
                                        _cache[37] || (_cache[37] = _createElementVNode("span", null, "剩余流量：", -1)),
                                        _createElementVNode("strong", null, _toDisplayString(formatBytes(subscriptionInfo.value.total - subscriptionInfo.value.download)), 1)
                                      ]),
                                      _createVNode(_component_v_progress_linear, {
                                        "model-value": subscriptionInfo.value.used_percentage,
                                        color: getUsageColor(subscriptionInfo.value.used_percentage),
                                        height: "10",
                                        class: "mb-2"
                                      }, null, 8, ["model-value", "color"]),
                                      _createElementVNode("div", _hoisted_11, [
                                        _createElementVNode("span", null, "下载：" + _toDisplayString(formatBytes(subscriptionInfo.value.download)), 1),
                                        _createElementVNode("span", null, "上传：" + _toDisplayString(formatBytes(subscriptionInfo.value.upload)), 1),
                                        _createElementVNode("span", null, "总量：" + _toDisplayString(formatBytes(subscriptionInfo.value.total)), 1)
                                      ])
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_btn, {
                                color: "primary",
                                onClick: updateSubscription,
                                loading: updatingSubscription.value
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_icon, { left: "" }, {
                                    default: _withCtx(() => _cache[38] || (_cache[38] = [
                                      _createTextVNode("mdi-cloud-sync")
                                    ])),
                                    _: 1
                                  }),
                                  _cache[39] || (_cache[39] = _createTextVNode(" 更新订阅 "))
                                ]),
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
                  _createVNode(_component_v_row, null, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_col, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_card, { class: "flex-grow-1" }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_card_text, { class: "text-subtitle-2" }, {
                                default: _withCtx(() => [
                                  _cache[45] || (_cache[45] = _createElementVNode("div", { class: "text-h6 mb-2" }, "状态信息", -1)),
                                  _createElementVNode("div", null, [
                                    _cache[40] || (_cache[40] = _createElementVNode("strong", null, "状态: ", -1)),
                                    _createVNode(_component_v_chip, {
                                      size: "small",
                                      color: status.value === 'running' ? 'success' : 'warning'
                                    }, {
                                      default: _withCtx(() => [
                                        _createTextVNode(_toDisplayString(status.value), 1)
                                      ]),
                                      _: 1
                                    }, 8, ["color"])
                                  ]),
                                  _createElementVNode("div", null, [
                                    _cache[41] || (_cache[41] = _createElementVNode("strong", null, "订阅配置规则数量:", -1)),
                                    _createTextVNode(" " + _toDisplayString(subscriptionInfo.value.rule_size), 1)
                                  ]),
                                  _createElementVNode("div", null, [
                                    _cache[42] || (_cache[42] = _createElementVNode("strong", null, "置顶规则数量:", -1)),
                                    _createTextVNode(" " + _toDisplayString(sortedRules.value.length), 1)
                                  ]),
                                  _createElementVNode("div", null, [
                                    _cache[43] || (_cache[43] = _createElementVNode("strong", null, "规则集规则数量:", -1)),
                                    _createTextVNode(" " + _toDisplayString(sortedRulesetRules.value.length), 1)
                                  ]),
                                  _createElementVNode("div", null, [
                                    _cache[44] || (_cache[44] = _createElementVNode("strong", null, "最后更新:", -1)),
                                    _createTextVNode(" " + _toDisplayString(lastUpdated.value), 1)
                                  ])
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_col, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_card, { class: "flex-grow-1" }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_card_text, { class: "text-subtitle-2" }, {
                                default: _withCtx(() => [
                                  _createElementVNode("div", _hoisted_12, [
                                    _cache[48] || (_cache[48] = _createElementVNode("div", { class: "text-h6" }, "订阅链接", -1)),
                                    (subUrl.value)
                                      ? (_openBlock(), _createBlock(_component_v_btn, {
                                          key: 0,
                                          icon: "",
                                          size: "small",
                                          variant: "text",
                                          color: "primary",
                                          onClick: _cache[4] || (_cache[4] = $event => (copyToClipboard(subUrl.value)))
                                        }, {
                                          default: _withCtx(() => [
                                            _createVNode(_component_v_icon, null, {
                                              default: _withCtx(() => _cache[46] || (_cache[46] = [
                                                _createTextVNode("mdi-content-copy")
                                              ])),
                                              _: 1
                                            }),
                                            _createVNode(_component_v_tooltip, {
                                              activator: "parent",
                                              location: "top"
                                            }, {
                                              default: _withCtx(() => _cache[47] || (_cache[47] = [
                                                _createTextVNode("复制链接")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        }))
                                      : _createCommentVNode("", true)
                                  ]),
                                  (subUrl.value)
                                    ? (_openBlock(), _createElementBlock("div", _hoisted_13, [
                                        _createElementVNode("a", {
                                          href: subUrl.value,
                                          target: "_blank",
                                          class: "text-primary"
                                        }, _toDisplayString(subUrl.value), 9, _hoisted_14)
                                      ]))
                                    : (_openBlock(), _createElementBlock("div", _hoisted_15, "未配置订阅URL"))
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]))
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_actions, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_btn, {
              color: "primary",
              onClick: refreshData,
              loading: loading.value
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, { left: "" }, {
                  default: _withCtx(() => _cache[49] || (_cache[49] = [
                    _createTextVNode("mdi-refresh")
                  ])),
                  _: 1
                }),
                _cache[50] || (_cache[50] = _createTextVNode(" 刷新数据 "))
              ]),
              _: 1
            }, 8, ["loading"]),
            _createVNode(_component_v_spacer),
            _createVNode(_component_v_btn, {
              color: "primary",
              onClick: notifySwitch
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, { left: "" }, {
                  default: _withCtx(() => _cache[51] || (_cache[51] = [
                    _createTextVNode("mdi-cog")
                  ])),
                  _: 1
                }),
                _cache[52] || (_cache[52] = _createTextVNode(" 配置 "))
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_snackbar, {
          modelValue: snackbar.value.show,
          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((snackbar.value.show) = $event)),
          color: snackbar.value.color,
          location: "bottom",
          class: "mb-2"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(snackbar.value.message), 1)
          ]),
          _: 1
        }, 8, ["modelValue", "color"])
      ]),
      _: 1
    }),
    _createVNode(_component_v_dialog, {
      modelValue: ruleDialog.value,
      "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((ruleDialog).value = $event)),
      "max-width": "600"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, null, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(editingPriority.value === null ? '添加规则' : '编辑规则'), 1)
              ]),
              _: 1
            }),
            _createVNode(_component_v_card_text, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_select, {
                  modelValue: newRule.value.type,
                  "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((newRule.value.type) = $event)),
                  items: ruleTypes.value,
                  label: "规则类型",
                  required: "",
                  class: "mb-4"
                }, null, 8, ["modelValue", "items"]),
                (newRule.value.type !== 'RULE-SET')
                  ? (_openBlock(), _createBlock(_component_v_text_field, {
                      key: 0,
                      modelValue: newRule.value.payload,
                      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((newRule.value.payload) = $event)),
                      label: "内容",
                      required: "",
                      class: "mb-4"
                    }, null, 8, ["modelValue"]))
                  : (_openBlock(), _createBlock(_component_v_select, {
                      key: 1,
                      modelValue: newRule.value.payload,
                      "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((newRule.value.payload) = $event)),
                      items: ruleProviderNames.value,
                      label: "选择规则集",
                      required: "",
                      class: "mb-4"
                    }, null, 8, ["modelValue", "items"])),
                _createVNode(_component_v_select, {
                  modelValue: newRule.value.action,
                  "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((newRule.value.action) = $event)),
                  items: actions.value,
                  label: "出站",
                  required: "",
                  class: "mb-4"
                }, null, 8, ["modelValue", "items"]),
                (showAdditionalParams.value)
                  ? (_openBlock(), _createBlock(_component_v_select, {
                      key: 2,
                      modelValue: newRule.value.additional_params,
                      "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((newRule.value.additional_params) = $event)),
                      label: "附加参数",
                      items: additionalParamOptions.value,
                      clearable: "",
                      hint: "可选参数",
                      "persistent-hint": "",
                      class: "mb-4"
                    }, null, 8, ["modelValue", "items"]))
                  : _createCommentVNode("", true),
                (editingPriority.value !== null)
                  ? (_openBlock(), _createBlock(_component_v_text_field, {
                      key: 3,
                      modelValue: newRule.value.priority,
                      "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((newRule.value.priority) = $event)),
                      modelModifiers: { number: true },
                      type: "number",
                      label: "优先级",
                      hint: "数字越小优先级越高",
                      "persistent-hint": ""
                    }, null, 8, ["modelValue"]))
                  : _createCommentVNode("", true)
              ]),
              _: 1
            }),
            _createVNode(_component_v_card_actions, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_btn, {
                  color: "secondary",
                  onClick: _cache[12] || (_cache[12] = $event => (ruleDialog.value = false))
                }, {
                  default: _withCtx(() => _cache[53] || (_cache[53] = [
                    _createTextVNode("取消")
                  ])),
                  _: 1
                }),
                _createVNode(_component_v_btn, {
                  color: "primary",
                  onClick: saveRule
                }, {
                  default: _withCtx(() => _cache[54] || (_cache[54] = [
                    _createTextVNode("保存")
                  ])),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"])
  ]))
}
}

};
const PageComponent = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-d5e502a5"]]);

export { PageComponent as default };
