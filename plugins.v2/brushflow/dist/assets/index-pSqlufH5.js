import { C as CurrentGlobal, M as ModuleFederation, g as getGlobalFederationConstructor, s as setGlobalFederationInstance, a as setGlobalFederationConstructor } from './index-Cezq_yMy.js';

//#region src/utils.ts
function getBuilderId() {
	return typeof FEDERATION_BUILD_IDENTIFIER !== "undefined" ? FEDERATION_BUILD_IDENTIFIER : "";
}
function getGlobalFederationInstance(name, version) {
	const buildId = getBuilderId();
	return CurrentGlobal.__FEDERATION__.__INSTANCES__.find((GMInstance) => {
		if (buildId && GMInstance.options.id === buildId) return true;
		if (GMInstance.options.name === name && !GMInstance.options.version && !version) return true;
		if (GMInstance.options.name === name && version && GMInstance.options.version === version) return true;
		return false;
	});
}

//#region src/index.ts
function createInstance(options) {
	const instance = new ((getGlobalFederationConstructor()) || ModuleFederation)({
		id: `${options.name}@${options.version || Date.now()}`,
		...options
	});
	setGlobalFederationInstance(instance);
	return instance;
}
let FederationInstance = null;
function init(options) {
	const instance = getGlobalFederationInstance(options.name, options.version);
	const normalizedOptions = {
		...options,
		id: options.id || ""
	};
	if (!instance) {
		FederationInstance = createInstance(normalizedOptions);
		return FederationInstance;
	} else {
		instance.initOptions(normalizedOptions);
		if (!FederationInstance) FederationInstance = instance;
		return instance;
	}
}
setGlobalFederationConstructor(ModuleFederation);

export { init as i };
