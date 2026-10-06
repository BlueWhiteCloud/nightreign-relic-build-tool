import axios from 'axios'
import type { AxiosRequestConfig } from 'axios'

/**
 * axios 实例：所有后端请求都从这里走。
 * baseURL 取环境变量（开发态是 /api，由 vite 转发到 Python 后端）。
 */
const instance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
})

instance.interceptors.response.use(
  // 直接把 data 抛出去，业务里 await http.get<T>() 拿到的就是 T
  (response) => response.data,
  (error) => {
    // FastAPI 的报错放在 detail 里，不读它的话界面只剩一句
    // 「Request failed with status code 500」，用户根本不知道发生了什么。
    const data = error.response?.data as { detail?: unknown; message?: unknown } | undefined
    const detail =
      typeof data?.detail === 'string'
        ? data.detail
        : typeof data?.message === 'string'
          ? data.message
          : ''
    return Promise.reject(new Error(detail || error.message || '请求失败'))
  },
)

/** 用法：const plans = await http.post<Plan[]>('/recommend', { heroType: 3 }) */
export const http = {
  get: <T>(url: string, config?: AxiosRequestConfig) => instance.get<T, T>(url, config),
  post: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    instance.post<T, T>(url, data, config),
  put: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    instance.put<T, T>(url, data, config),
  delete: <T>(url: string, config?: AxiosRequestConfig) => instance.delete<T, T>(url, config),
}

export default instance
