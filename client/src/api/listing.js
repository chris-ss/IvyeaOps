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
export const generateImage = async (id, prompt, slot, size) => (await api.post(`/projects/${id}/generate-image`, { prompt, slot, size })).data;
// 套图美术指导:一次 AI 规划整套主图(自适应张数,每张角度/卖点/文案/构图)
export const planImageSet = async (id, { target_count = 0, color_scheme = "" } = {}) =>
    (await api.post(`/projects/${id}/plan-image-set`, { target_count, color_scheme }, { timeout: 300000 })).data;
// 把卖点文案清晰排版叠加到已渲染(无字)的图上;改文案后可重叠,无需重渲染
export const overlayCallout = async (id, { url, callout, text_pos = "bottom-center", color = "#FFFFFF" }) =>
    (await api.post(`/projects/${id}/overlay-callout`, { url, callout, text_pos, color }, { timeout: 120000 })).data;
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
