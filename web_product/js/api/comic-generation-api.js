/** Stable frontend API contract.
 *
 *  UI / 状态管理层只消费这个接口与它返回的前端 DTO，
 *  绝不接触真实后端 schema。真实实现见 real-comic-generation-api.js，
 *  Mock 实现见 mock-comic-generation-api.js。
 *
 *  DTO shapes（前端 ViewModel，非后端 canonical schema）：
 *
 *  input = { file, prompt, preferences }
 *  GenerationViewModel = {
 *    runId, status, stage, progress, current, total, message, createdAt,
 *    availablePages, fileName, title, preferences, previewPages?
 *  }
 *  ComicResultViewModel = {
 *    runId, title, pageCount, panelCount, pages: ComicPageViewModel[],
 *    sourceFile, prompt, preferences, createdAt
 *  }
 *  ComicPageViewModel = { id, number, imageUrl, thumbnailUrl, width, height, sceneTitle }
 */
export class ComicGenerationAPI {
  async createGeneration(_input) { throw new Error('Not implemented'); }
  async getGeneration(_runId) { throw new Error('Not implemented'); }
  async getGenerationResult(_runId) { throw new Error('Not implemented'); }
  async listGenerations() { throw new Error('Not implemented'); }
  async cancelGeneration(_runId) { throw new Error('Not implemented'); }
  async retryGeneration(_runId) { throw new Error('Not implemented'); }
  async downloadComic(_runId, _format) { throw new Error('Not implemented'); }
}
