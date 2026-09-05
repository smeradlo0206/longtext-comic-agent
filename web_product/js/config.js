import { DEPLOY_CONFIG } from './deploy-config.js';
export const CONNECTION_KEY = 'huijuan.connection:' + new URL('../', import.meta.url).pathname;
let connection = {};
try { connection = JSON.parse(localStorage.getItem(CONNECTION_KEY) || '{}'); } catch { /* defaults */ }
const sameOrigin = location.pathname.startsWith('/product/') ? location.origin : '';
export const APP_CONFIG = {
  apiMode: connection.apiMode || (sameOrigin ? 'real' : DEPLOY_CONFIG.apiMode || 'mock'),
  apiBaseUrl: connection.apiBaseUrl || DEPLOY_CONFIG.apiBaseUrl || sameOrigin,
  storageKey: 'huijuan.comic.v1',
};

export function saveConnection(mode, address = '') {
  if (mode === 'real') {
    const url = new URL(address.trim());
    const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
    if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) ||
        url.username || url.password || url.search || url.hash) {
      throw new Error('请填写 HTTPS API 地址，或本机 http://127.0.0.1:8000 地址');
    }
    address = url.href.replace(/\/+$/, '');
  }
  localStorage.setItem(CONNECTION_KEY, JSON.stringify({ apiMode: mode, apiBaseUrl: address }));
}
