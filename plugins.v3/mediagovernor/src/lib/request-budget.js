export function createRequestBudget () {
  const waiters = new Set()
  const run = async (operation, timeout, label) => {
    let timer, cancellationReject
    const cancellation = new Promise((resolve, reject) => { cancellationReject = reject; waiters.add(reject) })
    try {
      return await Promise.race([
        Promise.resolve(operation),
        new Promise((resolve, reject) => { timer = setTimeout(() => reject(new Error(`${label}超过 ${Math.ceil(timeout / 1000)} 秒，已跳过`)), timeout) }),
        cancellation,
      ])
    } finally {
      clearTimeout(timer)
      waiters.delete(cancellationReject)
    }
  }
  const cancel = (message = '检查已停止') => {
    for (const reject of [...waiters]) reject(new Error(message))
    waiters.clear()
  }
  return { run, cancel, pending: () => waiters.size }
}

export async function settledResults (operations = []) {
  const rows = await Promise.allSettled(operations)
  return {
    values: rows.filter(row => row.status === 'fulfilled').map(row => row.value),
    errors: rows.filter(row => row.status === 'rejected').map(row => row.reason),
  }
}

export async function runBatchesUntilFailure (items = [], options = {}) {
  const pending = [...items]
  const completed = []
  while (pending.length && !options.stopped?.()) {
    const batch = []; let chars = 0
    while (pending.length && batch.length < options.maxItems) {
      const next = pending[0]; const cost = options.cost(next)
      if (batch.length && chars + cost > options.maxChars) break
      pending.shift(); batch.push(next); chars += cost
    }
    try {
      const result = await options.run(batch)
      completed.push(...batch)
      options.success?.(batch, result)
    } catch (error) {
      const failed = [...batch, ...pending]
      options.failure?.(failed, error)
      return { completed, failed, error }
    }
  }
  return { completed, failed: [], error: null }
}
