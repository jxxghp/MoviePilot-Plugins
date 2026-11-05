const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/index-pSqlufH5.js","assets/index-Cezq_yMy.js"])))=>i.map(i=>d[i]);
import { _ as __vitePreload } from './vite-preload-helper-BelkbqnE.js';

const __mfCacheGlobalKey = "__mf_module_cache__";
globalThis[__mfCacheGlobalKey] ||= { share: {}, remote: {} };
globalThis[__mfCacheGlobalKey].share ||= {};
globalThis[__mfCacheGlobalKey].remote ||= {};
const __mfModuleCache = globalThis[__mfCacheGlobalKey];
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

    const __mfGetSharedCacheDescriptor = function createSharedCacheDescriptor(pkg, singleton, version, scope) {
	const scopeName = (Array.isArray(scope) ? scope[0] : scope) || "default";
	const id = singleton || !version ? pkg : pkg + "@" + version;
	const descriptor = { canonical: scopeName + ":" + id };
	if (scopeName === "default") descriptor.aliases = [id];
	return descriptor;
};
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
    const __mfPendingShareImports = [];
    async function preloadPendingShares() {
      if (__mfPendingShareImports.length === 0) return;
      const __mfRendererShare = "react-dom/client";
      const __mfRendererParent = "react-dom";
      const {usedShared} = await __vitePreload(async () => { const {usedShared} = await import('./_virtual_mf-localSharedImportMap___mfe_internal__BrushFlow__mf_owner__1-C6y-c5Nn.js');return {usedShared}},true?__vite__mapDeps([0,1]):void 0);
      await Promise.all(__mfPendingShareImports.map(async ([pkg, load]) => {
        const exactShare = usedShared[pkg];
        const share = exactShare ?? (pkg === __mfRendererShare ? usedShared[__mfRendererParent] : undefined);
        if (!share || share.treeShaking || share.shareConfig?.import === false) return;
        // The collapsed parent does not mark the renderer subpath materialized until the entry
        // imports it, and that import map can be emitted first. The deferred renderer wrapper
        // still has to run before a standalone entry reads createRoot. A cache hit (the host
        // renderer) skips load(), so a nested leaf does not import its own client.
        if (exactShare && exactShare.materialize === false && pkg !== __mfRendererShare) return;
        const cacheDescriptor = __mfGetSharedCacheDescriptor(pkg, share.shareConfig?.singleton, share.version, share.scope);
        if (__mfReadSharedCache(__mfModuleCache.share, cacheDescriptor) !== undefined) return;
        await load().catch((err) => console.warn("[module-federation] shared preload failed:", pkg, err));
      }));
    }

export { preloadPendingShares };
