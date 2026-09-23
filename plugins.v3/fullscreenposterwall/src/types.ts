/** 全屏海报墙前端共享类型定义。 */

export interface PosterItem {
  source: string;          // "trending" | "tmdb_movies" | "tmdb_tvs"
  title: string;
  year?: string;
  type?: string;           // "电影" | "电视剧"
  overview?: string;
  vote_average?: number;
  poster_path?: string | null;
  backdrop_path?: string | null;
  logo_path?: string | null;
  thumb_path?: string | null;          // Fanart 原生带 Logo 的横图
  fanart_poster_path?: string | null;  // Fanart 带片名海报
  tmdb_id?: number | null;
  release_date?: string | null;
  /** 内部标记：logo 模式下原生带字图加载失败、主图实际已回退为普通图（需恢复 Logo 叠层） */
  __native_failed?: boolean;
}

export interface PluginConfig {
  enabled: boolean;
  sources: string[];
  effect: 'photos' | 'floating' | 'vintage' | 'lightdance' | 'shiftingtiles' | 'slidingpanels' | 'ring3d' | 'depthtunnel' | string;
  interval: number;        // 秒
  image_type: 'backdrop' | 'poster' | string;
  refresh_minutes: number;
  autoplay: boolean;
  tmdb_image_domain: string;
}

/** 取图片完整 URL：TMDB 路径需要拼域名；豆瓣/其他已经是完整 URL。
 *  logo 模式 = 带 Logo 的背景大图：主图用 backdrop，片名艺术字由 pickLogoUrl 叠层显示。 */
export function pickImageUrl(item: PosterItem, type: 'backdrop' | 'poster' | 'logo' | string, domain: string): string {
  return pickImageCandidates(item, type, domain)[0] || '';
}

/**
 * 按优先级返回某条目的全部候选图 URL（去重）。
 * 用途：预加载失败时在同一条目内逐级回退——
 * 例如 Fanart CDN（assets.fanart.tv）在浏览器侧不可达时，
 * 自动降级到 TMDB backdrop，而不是整条跳过导致整面墙黑屏。
 */
export function pickImageCandidates(item: PosterItem, type: 'backdrop' | 'poster' | 'logo' | string, domain: string): string[] {
  if (!item) return [];
  let paths = type === 'poster'
    ? [item.poster_path, item.backdrop_path]
    : type === 'logo'
      ? [item.thumb_path, item.fanart_poster_path, item.backdrop_path, item.poster_path]
      : [item.backdrop_path, item.poster_path];
  // 竖屏优化：竖屏设备 poster（2:3 竖图）优先，横屏行为完全不变
  if (type !== 'poster'
      && typeof window !== 'undefined'
      && window.innerWidth < window.innerHeight) {
    paths = [item.poster_path, ...paths.filter(p => p && p !== item.poster_path)];
  }
  const base = domain || 'https://image.tmdb.org/t/p/original';
  const urls = paths
    .filter((p): p is string => !!p)
    // '/api/...' 开头 = 本插件代理等站内路径，原样使用（不能拼 TMDB 域名）
    .map(p => (/^https?:\/\//.test(p) ? p : p.startsWith('/api/') ? p : p.startsWith('/') ? base + p : base + '/' + p));
  return [...new Set(urls)];
}

/** 死主机记忆：同一主机连续失败 2 次即标记，后续候选直接跳过（页面会话内有效）。
 *  解决 Fanart CDN（assets.fanart.tv）不可达时每张图都白等网络层超时、
 *  整面墙黑屏 ~30 秒的问题。 */
const hostFailCount = new Map<string, number>();
const deadHosts = new Set<string>();
function hostOf(url: string): string {
  try { return new URL(url).host; } catch { return ''; }
}
function noteHostFail(url: string) {
  const h = hostOf(url);
  if (!h) return;
  const n = (hostFailCount.get(h) || 0) + 1;
  hostFailCount.set(h, n);
  if (n >= 2) deadHosts.add(h);
}

/**
 * 按优先级加载候选图，返回首个成功的 URL（失败返回 ''）：
 * - 死主机候选直接跳过（若全部已标记则照旧尝试，保底不空）
 * - 每个候选最多等 timeoutMs，超时按失败处理并记该主机一次失败
 */
export function loadImageWithFallback(urls: string[], timeoutMs = 1500): Promise<string> {
  const live = urls.filter(u => !deadHosts.has(hostOf(u)));
  const list = live.length ? live : [...urls];
  return new Promise(resolve => {
    const tryAt = (i: number): void => {
      if (i >= list.length) return resolve('');
      const url = list[i];
      let settled = false;
      const img = new Image();
      const fail = () => {
        if (settled) return;
        settled = true; clearTimeout(timer); img.src = '';
        noteHostFail(url); tryAt(i + 1);
      };
      const timer = setTimeout(fail, timeoutMs);
      img.onload = () => { if (settled) return; settled = true; clearTimeout(timer); resolve(url); };
      img.onerror = fail;
      img.src = url;
    };
    tryAt(0);
  });
}

/** 是否已有「原生带 Logo 的图」（有则主图自带片名，无需再叠透明 Logo）。
 *  原生图声明存在但加载失败、实际已回退到普通图（__native_failed）时按没有处理。 */
export function hasNativeLogoImage(item: PosterItem): boolean {
  if (item.__native_failed) return false;
  return !!(item.thumb_path || item.fanart_poster_path);
}

/** 记录条目实际加载成功的主图 URL，维护 __native_failed 标记：
 *  logo 模式下成功的 URL 不是原生带字候选（thumb/fanart_poster）时置位，
 *  后续 hasNativeLogoImage 据此恢复 Logo 叠层（按实际加载结果而非声明判断）。 */
export function noteLoadedMainUrl(item: PosterItem, type: 'backdrop' | 'poster' | 'logo' | string, url: string, domain: string): void {
  if (!item || type !== 'logo' || !url) return;
  const base = domain || 'https://image.tmdb.org/t/p/original';
  const natives = [item.thumb_path, item.fanart_poster_path]
    .filter((p): p is string => !!p)
    .map(p => (/^https?:\/\//.test(p) ? p : p.startsWith('/api/') ? p : p.startsWith('/') ? base + p : base + '/' + p));
  item.__native_failed = !natives.includes(url);
}

/** 取片名 Logo（透明艺术字图）URL；没有则返回空串。 */
export function pickLogoUrl(item: PosterItem, domain: string): string {
  const path = item.logo_path;
  if (!path) return '';
  if (/^https?:\/\//.test(path)) return path;
  if (path.startsWith('/api/')) return path;
  if (path.startsWith('/')) return domain + path;
  return domain + '/' + path;
}