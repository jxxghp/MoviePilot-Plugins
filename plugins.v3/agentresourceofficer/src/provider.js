export const CLIENT_TYPES = [
  { title: '支付宝', label: '支付宝', value: 'alipaymini' },
  { title: '微信', label: '微信', value: 'wechatmini' },
  { title: '安卓', label: '安卓', value: '115android' },
  { title: 'iOS', label: 'iOS', value: '115ios' },
  { title: '网页', label: '网页', value: 'web' },
  { title: 'PAD', label: 'PAD', value: '115ipad' },
  { title: 'TV', label: 'TV', value: 'tv' },
]

export function cloneConfig(config) {
  return JSON.parse(JSON.stringify(config || {}))
}

export function unwrapResponse(response) {
  if (!response) return response
  if (Object.prototype.hasOwnProperty.call(response, 'success')) return response
  if (Object.prototype.hasOwnProperty.call(response, 'data')) return response.data
  return response
}

export function maskSecret(value, visible) {
  const text = String(value || '')
  if (visible || !text) return text
  return '•'.repeat(Math.min(Math.max(text.length, 8), 24))
}
