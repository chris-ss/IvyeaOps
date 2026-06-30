import axios from "axios";
const api = axios.create({ baseURL: "/api/listing", withCredentials: true });
export const listProjects = async () => (await api.get("/projects")).data;
export const createProject = async (asin, marketplace) => (await api.post("/projects", { asin, marketplace })).data;
export const getProject = async (id) => (await api.get(`/projects/${id}`)).data;
export const deleteProject = async (id) => api.delete(`/projects/${id}`);
export const scrapeProject = async (id) => (await api.post(`/projects/${id}/scrape`)).data;
export const imgflowStatus = async () => (await api.get("/imgflow/status")).data;
export const imgflowStart = async () => (await api.post("/imgflow/start")).data;
export const saveProductInfo = async (id, info) => (await api.post(`/projects/${id}/product-info`, info)).data;
export const aiAnalyze = async (id) => (await api.post(`/projects/${id}/ai-analyze`)).data;
export const generateCopy = async (id, type, context) => (await api.post(`/projects/${id}/copy`, { type, context })).data;
export const generateImagePrompt = async (id, payload) => {
    const body = typeof payload === "string" ? { slot: payload } : payload;
    return (await api.post(`/projects/${id}/generate-image-prompt`, body)).data;
};
export const generateImage = async (
    id, prompt, slot, size, use_reference = true, reference_urls = [], reference_mode = "product",
) => {
    const submitted = (await api.post(`/projects/${id}/generate-image`, {
        prompt, slot, size, use_reference, reference_urls, reference_mode,
    }, { timeout: 90000 })).data;
    // Backward compatibility with servers that still wait and return the image.
    if (submitted.url || submitted.imageUrl) return submitted;
    if (!submitted.task_id) throw new Error("生图服务未返回任务 ID");

    // Keep every HTTP request below the proxy timeout. Apimart often needs more
    // than 100 seconds when a product reference is attached.
    const deadline = Date.now() + 8 * 60 * 1000;
    while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 5000));
        try {
            const state = (await api.post(`/projects/${id}/image-task-status`, {
                task_id: submitted.task_id, slot, size,
            }, { timeout: 90000 })).data;
            if (state.status === "completed" && (state.url || state.imageUrl)) return state;
            if (state.status === "failed") throw new Error(state.error || "上游生图任务失败");
        } catch (error) {
            // A declared provider failure is terminal. Network/5xx failures of a
            // single status request are transient; retry without resubmitting and
            // charging for another image.
            if (!error?.response && error?.message && !/Network Error|timeout/i.test(error.message)) throw error;
            if (error?.response?.status && error.response.status < 500) throw error;
        }
    }
    throw new Error("生图任务等待超过 8 分钟，任务未重复提交，可稍后再试");
};
// 套图美术指导:一次 AI 规划整套主图(自适应张数,每张版式原型/角度/卖点/文案/构图)
export const planImageSet = async (id, {
    target_count = 0, color_scheme = "", deliverable = "gallery",
    visual_tone = "natural", language = "en", brief = "",
} = {}) => (await api.post(`/projects/${id}/plan-image-set`, {
    target_count, color_scheme, deliverable, visual_tone, language, brief,
}, { timeout: 600000 })).data;
export const saveCreativeSet = async (id, deliverable, plan) =>
    (await api.post(`/projects/${id}/creative-set`, { deliverable, plan }, { timeout: 120000 })).data;
// 历史兼容接口：新视觉工作台由图片模型图文整图直出，不再调用本地叠字。
export const overlayCallout = async (id, payload) =>
    (await api.post(`/projects/${id}/overlay-callout`, payload, { timeout: 120000 })).data;
export const prepareAsset = async (id, payload) =>
    (await api.post(`/projects/${id}/prepare-asset`, payload, { timeout: 120000 })).data;
export const compositeProduct = async (id, payload) =>
    (await api.post(`/projects/${id}/composite-product`, payload, { timeout: 120000 })).data;
export const renderBlueprint = async (id, payload) =>
    (await api.post(`/projects/${id}/render-blueprint`, payload, { timeout: 180000 })).data;
export const reviewRender = async (id, payload) =>
    (await api.post(`/projects/${id}/review-render`, payload, { timeout: 180000 })).data;
export const reviewImageSet = async (id, deliverable) =>
    (await api.post(`/projects/${id}/review-image-set`, { deliverable }, { timeout: 180000 })).data;
// New APIs
export const uploadImage = async (id, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return (await api.post(`/projects/${id}/upload-image`, fd, { headers: { "Content-Type": "multipart/form-data" } })).data;
};
export const getReferenceImages = async (id) => (await api.get(`/projects/${id}/reference-images`)).data;
export const deleteUploadedImage = async (id, filename) => (await api.delete(`/projects/${id}/uploaded-image/${encodeURIComponent(filename)}`)).data;
export const generateAllPrompts = async (id, sizes) => (await api.post(`/projects/${id}/generate-all-prompts`, { sizes })).data;
export const downloadPsd = async (id, url, slot) => {
    const resp = await api.post(`/projects/${id}/download-psd`, { url, slot }, { responseType: "blob" });
    const blob = new Blob([resp.data], { type: "application/octet-stream" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${id}_${slot}.psd`;
    a.click();
    URL.revokeObjectURL(a.href);
};
export const generateMainPrompts = async (id, { sizes, color_scheme, slots } = {}) => (await api.post(`/projects/${id}/generate-main-prompts`, { sizes, color_scheme, slots }, { timeout: 900000 })).data;
export const saveImageSlots = async (id, slots) => (await api.post(`/projects/${id}/image-slots`, slots)).data;
export const generateAplusPrompts = async (id, { sizes, color_scheme, slots } = {}) => (await api.post(`/projects/${id}/generate-aplus-prompts`, { sizes, color_scheme, slots }, { timeout: 900000 })).data;
export const saveTemplate = async (id, { name, content }) => (await api.post(`/projects/${id}/templates`, { name, content }, { timeout: 900000 })).data;
export const getTemplates = async (id) => (await api.get(`/projects/${id}/templates`)).data;
export const applyTemplate = async (id, { template_id, slot, color_scheme, target_group, slots }) => (await api.post(`/projects/${id}/apply-template`, { template_id, slot, color_scheme, target_group, slots }, { timeout: 900000 })).data;
export const reviewImagePrompt = async (id, payload) => (await api.post(`/projects/${id}/review-image-prompt`, payload, { timeout: 900000 })).data;
