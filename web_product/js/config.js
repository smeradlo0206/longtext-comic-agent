/** Global frontend configuration.
 *
 *  GitHub Pages 只托管静态资源，无法运行 Python 后端。
 *  因此默认 `apiMode` 为 "mock"，全部客户流程由 MockComicGenerationAPI 完成。
 *
 *  未来真实后端上线后，只需改这里（并实现 RealComicGenerationAPI 的请求），
 *  页面 / 状态管理 / 组件无需重写：
 *
 *      export const APP_CONFIG = {
 *        apiMode: "real",
 *        apiBaseUrl: "https://api.example.com",
 *      };
 */
export const APP_CONFIG = {
  apiMode: "mock",
  apiBaseUrl: "",
  /** localStorage 键名（隔离命名，避免与其它站点冲突） */
  storageKey: "huijuan.comic.v1",
};
